"""PathForge FastAPI application: authentication, jobs, applications, learning, and employer APIs."""

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Dict
from functools import lru_cache
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import zipfile
from html import unescape, escape
from xml.etree import ElementTree

import auth as auth_service
from app_config import apply_security_headers, configure_http_middleware
from auth_routes import create_auth_router
from database import DB_NAME, get_connection, initialize_database
from job_discovery import age_eligibility, discover_jobs
from job_history import record_job_changes
from job_sources.common import classify_category
from job_routes import PUBLIC_JOB_ELIGIBILITY_SQL, create_job_router
from saved_job_routes import create_saved_job_router
from schemas import (
    ApplicationAnswerInput, ApplicationCreate, ApplicationFormUpdate,
    ApplicationQuestionInput, ApplicationUpdate, ChatMessage,
    CompanyProfileUpdate, ConversationBlockUpdate, ConversationCreate,
    DirectMessageCreate, EmployerApplicationUpdate, EmployerCodeRedemption,
    EmployerWorkspaceCreate, ExternalApplicationCapture,
    InternalApplicationSubmit, Job, JobStatusUpdate,
    LearningAssistantDocument, LearningAssistantMessage,
    LearningProgressUpdate, MessageReportCreate, MockInterviewMessage,
    PrivacySettingsUpdate, ResumeEvaluationRequest, SavedSearchInput,
    UserProfileUpdate,
)


# Production mode removes developer-only discovery surfaces. Development keeps
# FastAPI's interactive documentation available for local coursework and QA.
PATHFORGE_ENV = os.environ.get("PATHFORGE_ENV", "development").strip().lower()
IS_PRODUCTION = PATHFORGE_ENV == "production"
app = FastAPI(
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
@app.get("/health/email")
def get_email_health():
    """Return only a non-sensitive availability signal for connectivity checks."""
    return {
        "status": "available" if (
            os.environ.get("RESEND_API_KEY", "").strip()
            and os.environ.get("PATHFORGE_FROM_EMAIL", "").strip()
        ) else "not_configured"
    }

# Development frontends use a separate origin from FastAPI. Keep this list
# explicit because credentialed CORS requests must not use a wildcard origin.
development_origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5501",
    "http://localhost:5501",
]
configured_origins = [
    origin.strip()
    for origin in os.environ.get("PATHFORGE_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
configure_http_middleware(
    app,
    IS_PRODUCTION,
    configured_origins,
    development_origins,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    return await apply_security_headers(
        request, call_next, IS_PRODUCTION, configured_origins
    )

# Apply idempotent schema setup before any request handler opens the database.
initialize_database()
# The callback resolves DB_NAME at request time so isolated tests and maintenance
# environments can safely substitute a temporary database.
app.include_router(create_auth_router(lambda: DB_NAME))

# Compatibility wrappers keep route code and external maintenance tests stable
# while the implementation lives in the focused authentication module.
DUMMY_PASSWORD_HASH = auth_service.DUMMY_PASSWORD_HASH


def enforce_authentication_rate_limit(action: str, request: Request, subject: str):
    return auth_service.enforce_authentication_rate_limit(action, request, subject, DB_NAME)


def record_authentication_attempt(action: str, request: Request, subject: str, succeeded: bool):
    return auth_service.record_authentication_attempt(action, request, subject, succeeded, DB_NAME)


def validate_password_strength(password: str, username: str = "", email: str = ""):
    return auth_service.validate_password_strength(password, username, email)


def hash_password(password: str):
    return auth_service.hash_password(password)


def verify_password(plain_password: str, stored_password: str):
    return auth_service.verify_password(plain_password, stored_password)


def password_hash_needs_upgrade(stored_password: str):
    return auth_service.password_hash_needs_upgrade(stored_password)

def hash_access_code(code: str):
    normalized_code = code.strip().upper()

    return hashlib.sha256(
        normalized_code.encode("utf-8")
    ).hexdigest()

def get_authenticated_user(request: Request):
    return auth_service.get_authenticated_user(request, DB_NAME)


def require_recent_sensitive_verification(request: Request):
    return auth_service.require_recent_sensitive_verification(request, DB_NAME)


def require_employer(request: Request):
    return auth_service.require_role(request, DB_NAME, "employer")


def require_admin(request: Request):
    return auth_service.require_role(request, DB_NAME, "admin")


@app.get("/admin/health/email")
def get_admin_email_health(request: Request):
    """Expose provider diagnostics only to authenticated administrators."""
    require_admin(request)
    return auth_service.get_email_diagnostics()

LEARNING_LESSON_IDS = {
    "career-exploration",
    "career-goals",
    "job-search-readiness",
    "career-transitions",
    "interview-foundations",
    "behavioral-interviews",
    "interview-formats",
    "interview-day-follow-up",
    "resume-fundamentals",
    "resume-skills-experience",
    "resume-education-projects",
    "resume-tailoring"
}

LEARNING_PROGRESS_STATUSES = {
    "started",
    "completed",
    "not_completed"
}

APPLICATION_METHODS = {
    "pathforge",
    "employer_website"
}

JOB_STATUSES = {
    "active",
    "closed",
    "draft"
}


def clean_application_deadline(
    application_deadline: Optional[str]
):
    if not application_deadline:
        return None

    cleaned_deadline = application_deadline.strip()

    try:
        parsed_deadline = date.fromisoformat(cleaned_deadline)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Application deadline must be a valid date."
        )

    return parsed_deadline.isoformat()


def deadline_has_passed(application_deadline):
    if not application_deadline:
        return False

    try:
        return date.fromisoformat(application_deadline) < date.today()
    except ValueError:
        return False

APPLICATION_QUESTION_TYPES = {
    "short_text",
    "long_text",
    "yes_no"
}

INTERVIEW_FORMATS = {
    "In Person",
    "Phone",
    "Video"
}

APPLICATION_STATUSES = {
    "Interested",
    "Applied",
    "Application Viewed",
    "Under Review",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Extended",
    "Accepted",
    "Rejected",
    "Withdrawn"
}


def record_application_history(
    cursor,
    application_id,
    event_type,
    field_name,
    old_value,
    new_value,
    changed_by_type,
    changed_by_user_id
):
    if old_value == new_value and event_type != "application_created":
        return

    cursor.execute(
        """
        INSERT INTO application_history (
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            changed_by_type,
            changed_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            changed_by_type,
            changed_by_user_id
        )
    )

@app.get("/")
def home():
    return {"message": "Job hunting website backend is running"}


def build_job_trust_information(job):
    if (
        job.get("application_method") == "employer_website"
        and job.get("verification_status") == "verified"
        and job.get("source_url")
    ):
        trust_level = "official_source"
        trust_label = "Verified Source"
        trust_explanation = (
            "PathForge imported this listing from an employer-controlled "
            "hiring source and recorded when that source was last checked. "
            "This does not verify every claim or guarantee the job is still open."
        )
    elif (
        job.get("application_method") == "pathforge"
        and job.get("employer_id")
    ):
        trust_level = "pathforge_access"
        trust_label = "PathForge Employer Access"
        trust_explanation = (
            "This listing was created by an account that redeemed PathForge "
            "employer access. That confirms platform access, not independent "
            "verification of the company or every statement in the listing."
        )
    else:
        trust_level = "limited_information"
        trust_label = "Limited Verification"
        trust_explanation = (
            "PathForge has limited source-verification information for this "
            "listing. Confirm the employer, role, and application destination "
            "before sharing personal information."
        )

    link_status = job.get("link_status") or "unknown"
    if job.get("verification_status") in {"expired", "removed"}:
        link_status = "unavailable"

    return {
        "trust_level": trust_level,
        "trust_label": trust_label,
        "trust_explanation": trust_explanation,
        "link_status": link_status,
        "last_link_checked_at": job.get("last_link_checked_at")
    }


def detect_job_safety_signals(job):
    job_text = " ".join(
        str(job.get(field) or "")
        for field in (
            "title", "description", "requirements",
            "preferred_qualifications"
        )
    ).lower()
    signals = []

    signal_rules = (
        (
            "money_request",
            r"\b(gift cards?|wire transfer|cryptocurrency|crypto payment|"
            r"pay(?:ment)? fee|send money|transfer funds)\b",
            "Money-transfer language detected",
            "Legitimate employers generally do not require applicants to send "
            "money, buy gift cards, or transfer cryptocurrency."
        ),
        (
            "banking_information",
            r"\b(bank account|routing number|online banking credentials|"
            r"bank login)\b",
            "Banking information mentioned",
            "Do not provide banking credentials during recruiting. Payroll "
            "details should only be handled after independently confirming an offer."
        ),
        (
            "identity_documents",
            r"\b(social security number|\bssn\b|passport copy|driver'?s license)\b",
            "Sensitive identity information mentioned",
            "Confirm the employer and hiring stage before sharing government "
            "identifiers or identity documents."
        ),
        (
            "off_platform_contact",
            r"\b(telegram|whatsapp|signal app)\b",
            "Off-platform messaging mentioned",
            "Be cautious if a recruiter insists on moving immediately to an "
            "unverified messaging account."
        ),
        (
            "personal_email",
            r"[a-z0-9._%+-]+@(gmail|yahoo|outlook|hotmail)\.com",
            "Personal email address mentioned",
            "Confirm that recruiting communication belongs to the employer "
            "before sharing personal information."
        )
    )

    for code, pattern, label, explanation in signal_rules:
        if re.search(pattern, job_text, re.IGNORECASE):
            signals.append({
                "code": code,
                "label": label,
                "explanation": explanation
            })

    return signals


def enrich_job_trust_data(job):
    enriched_job = dict(job)
    enriched_job.update(build_job_trust_information(enriched_job))
    enriched_job.update(age_eligibility(enriched_job))
    enriched_job["safety_signals"] = detect_job_safety_signals(enriched_job)
    return enriched_job


# Job and bookmark routes retain late-bound access to DB_NAME so integration
# tests can replace the database without rebuilding the FastAPI application.
app.include_router(create_job_router(lambda: DB_NAME, enrich_job_trust_data))
app.include_router(create_saved_job_router(lambda: DB_NAME))


US_STATE_NAMES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona",
    "AR": "arkansas", "CA": "california", "CO": "colorado",
    "CT": "connecticut", "DE": "delaware", "FL": "florida",
    "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts",
    "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska",
    "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey",
    "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island",
    "SC": "south carolina", "SD": "south dakota",
    "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
    "DC": "district of columbia"
}

NON_US_LOCATION_MARKERS = {
    "australia", "austria", "belgium", "brazil", "canada",
    "colombia", "denmark", "finland", "france", "germany",
    "india", "ireland", "israel", "italy", "japan", "mexico",
    "netherlands", "norway", "philippines", "poland", "portugal",
    "romania", "singapore", "spain", "sweden", "switzerland",
    "united kingdom"
}


def normalize_saved_search_location(value):
    normalized = str(value or "").strip().lower()

    for code, state_name in US_STATE_NAMES.items():
        pattern = (
            rf"(^|[,;/]\s*){code.lower()}"
            rf"(?=\s+\d{{5}}(?:-\d{{4}})?\b|\s*(?:$|[,;/]))"
        )
        normalized = re.sub(pattern, rf"\1{state_name}", normalized)

    return normalized


def normalize_saved_employment_type(value):
    normalized = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"full-time", "fulltime"}:
        return "full-time"
    if normalized in {"part-time", "parttime", "12-39-hours-per-week"}:
        return "part-time"
    return normalized


def normalize_saved_experience(value):
    normalized = str(value or "").strip().lower()
    if "entry" in normalized or "no experience" in normalized:
        return "entry-level"
    if "experienced" in normalized:
        return "experienced"
    return normalized


def is_united_states_job_location(location):
    raw_location = str(location or "").strip()
    normalized = raw_location.lower()

    if not normalized:
        return False

    if re.search(
        r"\b(united states|united states of america|usa|u\.s\.a\.?|u\.s\.)\b",
        normalized
    ):
        return True

    state_codes = "|".join(US_STATE_NAMES)
    state_code_pattern = (
        rf"(?:^|[,;/]\s*)({state_codes})"
        rf"(?=\s+\d{{5}}(?:-\d{{4}})?\b|\s*(?:$|[,;/]))"
    )

    if re.search(state_code_pattern, raw_location, re.IGNORECASE):
        return True

    if any(marker in normalized for marker in NON_US_LOCATION_MARKERS):
        return False

    return any(
        state_name in normalized
        for state_name in US_STATE_NAMES.values()
    )


def saved_search_matches_job(saved_search, job):
    criteria = dict(saved_search)
    return bool(discover_jobs(
        [dict(job)],
        query=criteria.get("keyword", ""),
        query_mode=criteria.get("query_mode", "broad"),
        location=criteria.get("location", ""),
        location_scope=criteria.get("location_scope", "us"),
        location_mode=criteria.get("location_mode", "nearby"),
        category=criteria.get("category", "all"),
        employment_type=criteria.get("employment_type", "all"),
        remote=criteria.get("remote_filter", "all"),
        remote_eligibility=criteria.get("remote_eligibility", "all"),
        experience=criteria.get("experience", "all"),
        age_fit=criteria.get("age_fit", "all"),
        date_posted=criteria.get("date_posted", "all"),
        listing_quality=criteria.get("listing_quality", "all"),
        application_feature=criteria.get("application_feature", "all"),
        minimum_pay=float(criteria.get("minimum_pay", 0) or 0),
        exclusions=criteria.get("exclusions", ""),
        exclude_terms=criteria.get("exclude_terms", ""),
    ))


def validate_saved_search_input(saved_search):
    values = {
        "name": saved_search.name.strip(),
        "keyword": saved_search.keyword.strip(),
        "query_mode": saved_search.query_mode.strip().lower(),
        "location": saved_search.location.strip(),
        "location_scope": saved_search.location_scope.strip().lower(),
        "category": saved_search.category.strip() or "all",
        "employment_type": (
            saved_search.employment_type.strip() or "all"
        ),
        "remote_filter": saved_search.remote_filter.strip().lower(),
        "experience": saved_search.experience.strip() or "all",
        "location_mode": saved_search.location_mode.strip().lower(),
        "remote_eligibility": saved_search.remote_eligibility.strip().lower(),
        "age_fit": saved_search.age_fit.strip().lower(),
        "date_posted": saved_search.date_posted.strip().lower(),
        "listing_quality": saved_search.listing_quality.strip().lower(),
        "application_feature": saved_search.application_feature.strip().lower(),
        "minimum_pay": saved_search.minimum_pay,
        "exclusions": saved_search.exclusions.strip().lower(),
        "exclude_terms": saved_search.exclude_terms.strip(),
        "frequency": saved_search.frequency.strip().lower(),
        "is_enabled": 1 if saved_search.is_enabled else 0
    }

    if not values["name"] or len(values["name"]) > 80:
        raise HTTPException(
            status_code=400,
            detail="Search name must be between 1 and 80 characters."
        )

    if len(values["keyword"]) > 120 or len(values["location"]) > 120:
        raise HTTPException(
            status_code=400,
            detail="Search keyword and location must be 120 characters or fewer."
        )

    if values["query_mode"] not in {"broad", "strict"}:
        raise HTTPException(status_code=400, detail="Invalid search matching mode.")

    if values["location_scope"] not in {"us", "all"}:
        raise HTTPException(status_code=400, detail="Invalid location scope.")
    if values["remote_filter"] not in {"all", "remote", "hybrid", "onsite"}:
        raise HTTPException(status_code=400, detail="Invalid remote filter.")
    if values["location_mode"] not in {"nearby", "exact"}:
        raise HTTPException(status_code=400, detail="Invalid location match mode.")
    if values["remote_eligibility"] not in {"all", "us", "anywhere"}:
        raise HTTPException(status_code=400, detail="Invalid remote eligibility.")
    if values["age_fit"] not in {"all", "age-14", "age-15", "age-16-17", "age-18-plus"}:
        raise HTTPException(status_code=400, detail="Invalid age fit.")
    if values["date_posted"] not in {"all", "1", "3", "7", "14", "30", "60", "90"}:
        raise HTTPException(status_code=400, detail="Invalid posting age.")
    if values["listing_quality"] not in {
        "all", "pay", "deadline", "accommodation", "complete"
    }:
        raise HTTPException(status_code=400, detail="Invalid listing quality.")
    if values["application_feature"] not in {
        "all", "direct_apply", "no_cover_letter", "accommodation_contact"
    }:
        raise HTTPException(status_code=400, detail="Invalid application feature.")
    if values["minimum_pay"] < 0 or values["minimum_pay"] > 10_000_000:
        raise HTTPException(status_code=400, detail="Minimum pay is out of range.")
    valid_exclusions = {"senior", "staffing", "commission", "clearance", "unpaid"}
    selected_exclusions = {item for item in values["exclusions"].split(",") if item}
    if not selected_exclusions <= valid_exclusions or len(values["exclusions"]) > 100:
        raise HTTPException(status_code=400, detail="Invalid exclusions.")
    if len(values["exclude_terms"]) > 200:
        raise HTTPException(status_code=400, detail="Excluded words must be 200 characters or fewer.")
    if values["frequency"] not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="Invalid alert frequency.")

    return values


def next_saved_search_check(frequency, current_time=None):
    current_time = current_time or datetime.now(timezone.utc)
    interval = timedelta(days=1 if frequency == "daily" else 7)
    return (current_time + interval).strftime("%Y-%m-%d %H:%M:%S")


def evaluate_saved_search(cursor, saved_search, force=False):
    if not saved_search["is_enabled"]:
        return 0

    now = datetime.now(timezone.utc)
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    next_check_at = saved_search["next_check_at"]

    if not force and next_check_at and next_check_at > now_text:
        return 0

    cursor.execute(
        """
        SELECT *
        FROM jobs
        WHERE id > ?
          AND status = 'active'
          AND (
              application_method = 'pathforge'
              OR verification_status = 'verified'
          )
          AND (expires_at IS NULL OR date(expires_at) >= date('now'))
          AND (
              application_deadline IS NULL
              OR date(application_deadline) >= date('now')
          )
        ORDER BY id ASC
        """,
        (saved_search["baseline_job_id"],)
    )
    jobs = cursor.fetchall()
    match_count = 0

    for job in jobs:
        if saved_search_matches_job(saved_search, job):
            cursor.execute(
                """
                INSERT OR IGNORE INTO saved_search_matches (
                    saved_search_id,
                    job_id
                )
                VALUES (?, ?)
                """,
                (saved_search["id"], job["id"])
            )
            match_count += cursor.rowcount

    cursor.execute("SELECT COALESCE(MAX(id), 0) FROM jobs")
    newest_job_id = cursor.fetchone()[0]
    cursor.execute(
        """
        UPDATE saved_searches
        SET baseline_job_id = ?,
            last_checked_at = ?,
            next_check_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            newest_job_id,
            now_text,
            next_saved_search_check(saved_search["frequency"], now),
            saved_search["id"]
        )
    )

    return match_count


def saved_search_response(cursor, saved_search):
    cursor.execute(
        """
        SELECT
            COUNT(*) AS match_count,
            SUM(CASE WHEN seen_at IS NULL THEN 1 ELSE 0 END) AS unread_count
        FROM saved_search_matches
        WHERE saved_search_id = ?
        """,
        (saved_search["id"],)
    )
    counts = cursor.fetchone()
    result = dict(saved_search)
    result["is_enabled"] = bool(result["is_enabled"])
    result["match_count"] = counts["match_count"] or 0
    result["unread_count"] = counts["unread_count"] or 0
    return result


# Saved searches also drive matching notifications for authenticated job seekers.
@app.get("/saved-searches")
def get_saved_searches(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id DESC",
        (user["id"],)
    )
    searches = cursor.fetchall()

    for saved_search in searches:
        evaluate_saved_search(cursor, saved_search)

    conn.commit()
    cursor.execute(
        "SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id DESC",
        (user["id"],)
    )
    response = [
        saved_search_response(cursor, saved_search)
        for saved_search in cursor.fetchall()
    ]
    conn.close()
    return {"saved_searches": response}


@app.post("/saved-searches", status_code=201)
def create_saved_search(saved_search: SavedSearchInput, request: Request):
    user = get_authenticated_user(request)
    values = validate_saved_search_input(saved_search)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(id), 0) FROM jobs")
    baseline_job_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO saved_searches (
            user_id, name, keyword, query_mode, location, location_scope,
            category, employment_type, remote_filter, experience,
            location_mode, remote_eligibility, age_fit, date_posted,
            listing_quality, application_feature, minimum_pay, exclusions, exclude_terms,
            frequency, is_enabled, baseline_job_id, next_check_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user["id"], values["name"], values["keyword"], values["query_mode"],
            values["location"], values["location_scope"],
            values["category"], values["employment_type"],
            values["remote_filter"], values["experience"],
            values["location_mode"], values["remote_eligibility"],
            values["age_fit"], values["date_posted"],
            values["listing_quality"], values["application_feature"],
            values["minimum_pay"],
            values["exclusions"], values["exclude_terms"],
            values["frequency"], values["is_enabled"], baseline_job_id,
            next_saved_search_check(values["frequency"])
        )
    )
    saved_search_id = cursor.lastrowid
    conn.commit()
    cursor.execute("SELECT * FROM saved_searches WHERE id = ?", (saved_search_id,))
    response = saved_search_response(cursor, cursor.fetchone())
    conn.close()
    return {"message": "Saved search created.", "saved_search": response}


@app.put("/saved-searches/{saved_search_id}")
def update_saved_search(
    saved_search_id: int,
    saved_search: SavedSearchInput,
    request: Request
):
    user = get_authenticated_user(request)
    values = validate_saved_search_input(saved_search)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM saved_searches WHERE id = ? AND user_id = ?",
        (saved_search_id, user["id"])
    )
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Saved search not found.")

    criteria_fields = (
        "keyword", "query_mode", "location", "location_scope", "category",
        "employment_type", "remote_filter", "experience", "location_mode",
        "remote_eligibility", "age_fit", "date_posted", "listing_quality",
        "application_feature",
        "minimum_pay", "exclusions", "exclude_terms"
    )
    criteria_changed = any(
        existing[field] != values[field]
        for field in criteria_fields
    )
    baseline_job_id = existing["baseline_job_id"]

    if criteria_changed:
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM jobs")
        baseline_job_id = cursor.fetchone()[0]
        cursor.execute(
            "DELETE FROM saved_search_matches WHERE saved_search_id = ?",
            (saved_search_id,)
        )

    cursor.execute(
        """
        UPDATE saved_searches
        SET name = ?, keyword = ?, query_mode = ?, location = ?, location_scope = ?,
            category = ?, employment_type = ?, remote_filter = ?,
            experience = ?, location_mode = ?, remote_eligibility = ?,
            age_fit = ?, date_posted = ?, listing_quality = ?,
            application_feature = ?, minimum_pay = ?, exclusions = ?, exclude_terms = ?,
            frequency = ?, is_enabled = ?,
            baseline_job_id = ?, next_check_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (
            values["name"], values["keyword"], values["query_mode"], values["location"],
            values["location_scope"], values["category"],
            values["employment_type"], values["remote_filter"],
            values["experience"], values["location_mode"],
            values["remote_eligibility"], values["age_fit"],
            values["date_posted"], values["listing_quality"],
            values["application_feature"],
            values["minimum_pay"], values["exclusions"],
            values["exclude_terms"], values["frequency"],
            values["is_enabled"], baseline_job_id,
            next_saved_search_check(values["frequency"]),
            saved_search_id, user["id"]
        )
    )
    conn.commit()
    cursor.execute("SELECT * FROM saved_searches WHERE id = ?", (saved_search_id,))
    response = saved_search_response(cursor, cursor.fetchone())
    conn.close()
    return {"message": "Saved search updated.", "saved_search": response}


@app.delete("/saved-searches/{saved_search_id}")
def delete_saved_search(saved_search_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM saved_searches WHERE id = ? AND user_id = ?",
        (saved_search_id, user["id"])
    )
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Saved search not found.")
    cursor.execute(
        "DELETE FROM saved_search_matches WHERE saved_search_id = ?",
        (saved_search_id,)
    )
    cursor.execute(
        "DELETE FROM saved_searches WHERE id = ? AND user_id = ?",
        (saved_search_id, user["id"])
    )
    conn.commit()
    conn.close()
    return {"message": "Saved search deleted."}


@app.post("/saved-searches/{saved_search_id}/check")
def check_saved_search(saved_search_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM saved_searches WHERE id = ? AND user_id = ?",
        (saved_search_id, user["id"])
    )
    saved_search = cursor.fetchone()
    if not saved_search:
        conn.close()
        raise HTTPException(status_code=404, detail="Saved search not found.")
    new_matches = evaluate_saved_search(cursor, saved_search, force=True)
    conn.commit()
    conn.close()
    return {"message": "Saved search checked.", "new_matches": new_matches}


@app.get("/saved-searches/{saved_search_id}/matches")
def get_saved_search_matches(saved_search_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM saved_searches WHERE id = ? AND user_id = ?",
        (saved_search_id, user["id"])
    )
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Saved search not found.")
    cursor.execute(
        """
        SELECT jobs.*, saved_search_matches.first_matched_at,
               saved_search_matches.seen_at
        FROM saved_search_matches
        JOIN jobs ON jobs.id = saved_search_matches.job_id
        WHERE saved_search_matches.saved_search_id = ?
        ORDER BY saved_search_matches.first_matched_at DESC
        """,
        (saved_search_id,)
    )
    matches = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"matches": matches}


@app.post("/saved-searches/{saved_search_id}/mark-read")
def mark_saved_search_read(saved_search_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM saved_searches WHERE id = ? AND user_id = ?",
        (saved_search_id, user["id"])
    )
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Saved search not found.")
    cursor.execute(
        """
        UPDATE saved_search_matches
        SET seen_at = COALESCE(seen_at, CURRENT_TIMESTAMP)
        WHERE saved_search_id = ?
        """,
        (saved_search_id,)
    )
    cursor.execute(
        """
        UPDATE notifications
        SET is_read = 1,
            read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
        WHERE user_id = ?
          AND event_key IN (
              SELECT 'job-match:' || id
              FROM saved_search_matches
              WHERE saved_search_id = ?
          )
        """,
        (user["id"], saved_search_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Job alerts marked as read."}


def evaluate_user_saved_searches(cursor, user_id):
    cursor.execute(
        "SELECT * FROM saved_searches WHERE user_id = ?",
        (user_id,)
    )
    for saved_search in cursor.fetchall():
        evaluate_saved_search(cursor, saved_search)


def synchronize_user_notifications(cursor, user_id):
    def add_notification(kind, title, message, href, event_key, created_at=None):
        cursor.execute(
            """
            INSERT OR IGNORE INTO notifications (
                user_id, notification_type, title, message,
                href, event_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (user_id, kind, title, message, href, event_key, created_at)
        )

    rows = cursor.execute(
        """
        SELECT matches.id, matches.first_matched_at, jobs.id AS job_id,
               jobs.title, jobs.company, searches.name AS search_name
        FROM saved_search_matches AS matches
        JOIN saved_searches AS searches ON searches.id = matches.saved_search_id
        JOIN jobs ON jobs.id = matches.job_id
        WHERE searches.user_id = ?
        """,
        (user_id,)
    ).fetchall()
    for row in rows:
        add_notification(
            "job_match", f"New match: {row['title']}",
            f"{row['company']} matched your saved search “{row['search_name']}.”",
            f"jobs.html?job={row['job_id']}", f"job-match:{row['id']}",
            row["first_matched_at"]
        )

    rows = cursor.execute(
        """
        SELECT history.id, history.new_value AS new_status, history.created_at,
               applications.id AS application_id, jobs.title, jobs.company
        FROM application_history AS history
        JOIN applications ON applications.id = history.application_id
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND history.changed_by_type = 'employer'
          AND history.field_name = 'status'
        """,
        (user_id,)
    ).fetchall()
    for row in rows:
        add_notification(
            "application_update", f"Application update from {row['company']}",
            f"Your {row['title']} application is now marked {row['new_status']}.",
            "applications.html", f"application-update:{row['id']}",
            row["created_at"]
        )

    rows = cursor.execute(
        """
        SELECT applications.id, applications.interview_date,
               applications.interview_time, jobs.title, jobs.company
        FROM applications JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND applications.status = 'Interview Scheduled'
          AND date(applications.interview_date) >= date('now')
        """,
        (user_id,)
    ).fetchall()
    for row in rows:
        when = format_action_date(row["interview_date"])
        if row["interview_time"]:
            when += f" at {row['interview_time']}"
        add_notification(
            "interview", f"Upcoming interview with {row['company']}",
            f"Your interview for {row['title']} is scheduled for {when}.",
            "applications.html", f"interview:{row['id']}:{row['interview_date']}:{row['interview_time'] or ''}"
        )

    rows = cursor.execute(
        """
        SELECT applications.id, applications.follow_up_date,
               jobs.title, jobs.company
        FROM applications JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND date(applications.follow_up_date) <= date('now')
          AND applications.status NOT IN ('Accepted','Rejected','Withdrawn')
        """,
        (user_id,)
    ).fetchall()
    for row in rows:
        add_notification(
            "follow_up", f"Follow-up due for {row['company']}",
            f"Your follow-up for {row['title']} was due {format_action_date(row['follow_up_date'])}.",
            "applications.html", f"follow-up:{row['id']}:{str(row['follow_up_date'])[:10]}"
        )

    rows = cursor.execute(
        """
        SELECT jobs.id, jobs.title, jobs.company,
               COALESCE(jobs.application_deadline, jobs.expires_at) AS deadline
        FROM saved_jobs JOIN jobs ON jobs.id = saved_jobs.job_id
        WHERE saved_jobs.user_id = ?
          AND date(COALESCE(jobs.application_deadline, jobs.expires_at))
              BETWEEN date('now') AND date('now', '+7 day')
        """,
        (user_id,)
    ).fetchall()
    for row in rows:
        add_notification(
            "deadline", f"Deadline approaching: {row['title']}",
            f"{row['company']} lists a deadline of {format_action_date(row['deadline'])}. Confirm it on the official listing.",
            f"jobs.html?job={row['id']}", f"deadline:{row['id']}:{str(row['deadline'])[:10]}"
        )


@app.get("/notifications")
def get_notifications(request: Request, category: str = "all"):
    user = get_authenticated_user(request)
    if user["role"] != "job_seeker":
        raise HTTPException(status_code=403, detail="Job-seeker access is required.")
    allowed = {"all", "job_match", "application_update", "interview", "follow_up", "deadline", "account"}
    if category not in allowed:
        raise HTTPException(status_code=400, detail="Invalid notification category.")
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    preference = cursor.execute(
        "SELECT security_notifications FROM privacy_settings WHERE user_id = ?",
        (user["id"],),
    ).fetchone()
    notifications_enabled = preference is None or bool(preference[0])
    if not notifications_enabled:
        conn.close()
        empty_counts = {key: 0 for key in allowed}
        return {"notifications": [], "counts": empty_counts, "unread_count": 0, "notifications_enabled": False}
    evaluate_user_saved_searches(cursor, user["id"])
    synchronize_user_notifications(cursor, user["id"])
    conn.commit()
    clause = "" if category == "all" else "AND notification_type = ?"
    params = [user["id"]] + ([] if category == "all" else [category])
    rows = cursor.execute(
        f"""SELECT * FROM notifications WHERE user_id = ? {clause}
            ORDER BY is_read ASC, datetime(created_at) DESC, id DESC""",
        params
    ).fetchall()
    counts = {"all": 0, "job_match": 0, "application_update": 0, "interview": 0, "follow_up": 0, "deadline": 0, "account": 0}
    for row in cursor.execute(
        "SELECT notification_type, COUNT(*) total FROM notifications WHERE user_id = ? GROUP BY notification_type",
        (user["id"],)
    ).fetchall():
        counts[row["notification_type"]] = row["total"]
        counts["all"] += row["total"]
    unread = cursor.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
        (user["id"],)
    ).fetchone()[0]
    conn.close()
    return {"notifications": [dict(row) for row in rows], "counts": counts, "unread_count": unread, "notifications_enabled": True}


@app.get("/notifications/summary")
def get_notification_summary(request: Request):
    data = get_notifications(request, "all")
    return {"unread_count": data["unread_count"], "notifications_enabled": data.get("notifications_enabled", True)}


@app.post("/notifications/mark-read")
def mark_all_notifications_read(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE notifications SET is_read = 1, read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE user_id = ? AND is_read = 0",
        (user["id"],)
    )
    changed = cursor.rowcount
    conn.commit(); conn.close()
    return {"message": "Notifications marked as read.", "marked_read": changed}


@app.post("/notifications/{notification_id}/mark-read")
def mark_notification_read(notification_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE notifications SET is_read = 1, read_at = COALESCE(read_at, CURRENT_TIMESTAMP) WHERE id = ? AND user_id = ?",
        (notification_id, user["id"])
    )
    if cursor.rowcount == 0:
        conn.close(); raise HTTPException(status_code=404, detail="Notification not found.")
    conn.commit(); conn.close()
    return {"message": "Notification marked as read."}


@app.get("/job-alerts/summary")
def get_job_alert_summary(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    evaluate_user_saved_searches(cursor, user["id"])
    conn.commit()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM saved_search_matches
        JOIN saved_searches
            ON saved_searches.id = saved_search_matches.saved_search_id
        WHERE saved_searches.user_id = ?
          AND saved_search_matches.seen_at IS NULL
        """,
        (user["id"],)
    )
    unread_count = cursor.fetchone()[0]
    conn.close()
    return {"unread_count": unread_count}


@app.get("/job-alerts")
def get_job_alerts(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    evaluate_user_saved_searches(cursor, user["id"])
    conn.commit()
    cursor.execute(
        """
        SELECT
            saved_search_matches.id AS alert_id,
            saved_search_matches.first_matched_at,
            saved_search_matches.seen_at,
            saved_searches.id AS saved_search_id,
            saved_searches.name AS saved_search_name,
            saved_searches.frequency,
            jobs.id AS job_id,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.pay,
            jobs.salary_min,
            jobs.salary_max,
            jobs.salary_period,
            jobs.employment_type,
            jobs.is_remote,
            jobs.application_method,
            jobs.application_deadline,
            jobs.source_url,
            jobs.application_url
        FROM saved_search_matches
        JOIN saved_searches
            ON saved_searches.id = saved_search_matches.saved_search_id
        JOIN jobs
            ON jobs.id = saved_search_matches.job_id
        WHERE saved_searches.user_id = ?
        ORDER BY
            saved_search_matches.seen_at IS NULL DESC,
            saved_search_matches.first_matched_at DESC
        """,
        (user["id"],)
    )
    alerts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"alerts": alerts}


@app.post("/job-alerts/mark-read")
def mark_all_job_alerts_read(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE saved_search_matches
        SET seen_at = COALESCE(seen_at, CURRENT_TIMESTAMP)
        WHERE saved_search_id IN (
            SELECT id
            FROM saved_searches
            WHERE user_id = ?
        )
        """,
        (user["id"],)
    )
    marked_read = cursor.rowcount
    conn.commit()
    conn.close()
    return {
        "message": "Job alerts marked as read.",
        "marked_read": marked_read
    }


@app.post("/job-alerts/{alert_id}/mark-read")
def mark_job_alert_read(alert_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE saved_search_matches
        SET seen_at = COALESCE(seen_at, CURRENT_TIMESTAMP)
        WHERE id = ?
          AND saved_search_id IN (
              SELECT id
              FROM saved_searches
              WHERE user_id = ?
          )
        """,
        (alert_id, user["id"])
    )
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Job alert not found.")
    conn.commit()
    conn.close()
    return {"message": "Job alert marked as read."}


# Employer workspace endpoints require the employer role before reading or
# mutating company, posting, or applicant data.
@app.get("/employer/company-profile")
def get_employer_company_profile(request: Request):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            company_name,
            company_description,
            website,
            logo_url,
            brand_color,
            hiring_preferences,
            created_at,
            updated_at
        FROM company_profiles
        WHERE employer_id = ?
        """,
        (employer["id"],)
    )

    profile = cursor.fetchone()

    if profile:
        conn.close()

        return {
            "company_profile": dict(profile)
        }

    cursor.execute(
        """
        SELECT company_name
        FROM employer_access_codes
        WHERE redeemed_by_user_id = ?
        ORDER BY redeemed_at DESC
        LIMIT 1
        """,
        (employer["id"],)
    )

    access_code_record = cursor.fetchone()
    conn.close()

    company_name = ""

    if access_code_record and access_code_record["company_name"]:
        company_name = access_code_record["company_name"]

    return {
        "company_profile": {
            "company_name": company_name,
            "company_description": "",
            "website": "",
            "logo_url": "",
            "brand_color": "#2563eb",
            "hiring_preferences": "",
            "created_at": None,
            "updated_at": None
        }
    }


@app.post("/employer/workspace", status_code=201)
def create_employer_workspace(data: EmployerWorkspaceCreate, request: Request):
    user = get_authenticated_user(request)
    if user["role"] == "admin":
        raise HTTPException(status_code=400, detail="Administrator accounts cannot create employer workspaces.")
    if user["role"] == "employer":
        raise HTTPException(status_code=409, detail="This account already has an employer workspace.")
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Verify your account email before creating an employer workspace.")

    company_name = data.company_name.strip()
    website = (data.website or "").strip()
    contact_email = str(data.contact_email or user["email"]).strip().lower()
    if len(company_name) < 2 or len(company_name) > 120:
        raise HTTPException(status_code=400, detail="Enter a company name between 2 and 120 characters.")
    if website and not re.match(r"^https?://[^\s]+$", website, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Enter a complete website address beginning with http:// or https://.")

    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    saved = cursor.execute("SELECT password FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not saved or not verify_password(data.current_password, saved[0]):
        conn.close()
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")
    cursor.execute(
        """INSERT INTO company_profiles
           (employer_id, company_name, website, brand_color, contact_email, verification_status)
           VALUES (?, ?, ?, '#2563eb', ?, 'account_email_verified')
           ON CONFLICT(employer_id) DO UPDATE SET
             company_name = excluded.company_name,
             website = excluded.website,
             contact_email = excluded.contact_email,
             updated_at = CURRENT_TIMESTAMP""",
        (user["id"], company_name, website, contact_email),
    )
    cursor.execute("UPDATE users SET role = 'employer' WHERE id = ?", (user["id"],))
    cursor.execute(
        "INSERT INTO security_events (user_id, event_type, event_summary) VALUES (?, 'employer_workspace_created', ?)",
        (user["id"], f"Employer workspace created for {company_name}."),
    )
    conn.commit()
    conn.close()
    return {
        "message": "Employer workspace created. Your personal PathForge login now opens both your account and employer tools.",
        "contact_email": contact_email,
        "verification_status": "account_email_verified"
    }


@app.get("/employer/statistics")
def get_employer_statistics(request: Request):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(
                CASE
                    WHEN status = 'active'
                    THEN 1
                END
            ) AS active_jobs,

            COUNT(
                CASE
                    WHEN status = 'draft'
                    THEN 1
                END
            ) AS draft_jobs,

            COUNT(
                CASE
                    WHEN status = 'closed'
                    THEN 1
                END
            ) AS closed_jobs
        FROM jobs
        WHERE employer_id = ?
        """,
        (employer["id"],)
    )

    job_counts = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            COUNT(DISTINCT applications.id)
                AS total_applicants,

            COUNT(
                DISTINCT CASE
                    WHEN applications.status = 'Interview Scheduled'
                    THEN applications.id
                END
            ) AS scheduled_interviews,

            COUNT(
                DISTINCT CASE
                    WHEN applications.status = 'Accepted'
                    THEN applications.id
                END
            ) AS hires
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE jobs.employer_id = ?
          AND applications.application_method = 'pathforge'
        """,
        (employer["id"],)
    )

    application_counts = cursor.fetchone()
    conn.close()

    return {
        "statistics": {
            "active_jobs": job_counts["active_jobs"],
            "draft_jobs": job_counts["draft_jobs"],
            "closed_jobs": job_counts["closed_jobs"],
            "total_applicants": (
                application_counts["total_applicants"]
            ),
            "scheduled_interviews": (
                application_counts["scheduled_interviews"]
            ),
            "hires": application_counts["hires"]
        }
    }

@app.put("/employer/company-profile")
def update_employer_company_profile(
    profile: CompanyProfileUpdate,
    request: Request
):
    employer = require_employer(request)

    company_name = profile.company_name.strip()
    company_description = (
        profile.company_description or ""
    ).strip()
    website = (profile.website or "").strip()
    logo_url = (profile.logo_url or "").strip()
    brand_color = (profile.brand_color or "").strip()
    hiring_preferences = (
        profile.hiring_preferences or ""
    ).strip()

    if not company_name:
        raise HTTPException(
            status_code=400,
            detail="Company name is required."
        )

    if len(company_name) > 120:
        raise HTTPException(
            status_code=400,
            detail="Company name must be 120 characters or fewer."
        )

    if len(company_description) > 2000:
        raise HTTPException(
            status_code=400,
            detail="Company description must be 2,000 characters or fewer."
        )

    if website and not website.startswith(
        ("http://", "https://")
    ):
        raise HTTPException(
            status_code=400,
            detail="Company website must begin with http:// or https://."
        )

    if logo_url and not logo_url.startswith(
        ("http://", "https://")
    ):
        raise HTTPException(
            status_code=400,
            detail="Logo URL must begin with http:// or https://."
        )

    if brand_color:
        valid_brand_color = (
            len(brand_color) == 7
            and brand_color.startswith("#")
        )

        if valid_brand_color:
            try:
                int(brand_color[1:], 16)
            except ValueError:
                valid_brand_color = False

        if not valid_brand_color:
            raise HTTPException(
                status_code=400,
                detail="Brand color must be a valid hexadecimal color."
            )

    if len(hiring_preferences) > 1500:
        raise HTTPException(
            status_code=400,
            detail="Hiring preferences must be 1,500 characters or fewer."
        )

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO company_profiles (
            employer_id,
            company_name,
            company_description,
            website,
            logo_url,
            brand_color,
            hiring_preferences
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(employer_id)
        DO UPDATE SET
            company_name = excluded.company_name,
            company_description = excluded.company_description,
            website = excluded.website,
            logo_url = excluded.logo_url,
            brand_color = excluded.brand_color,
            hiring_preferences = excluded.hiring_preferences,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            employer["id"],
            company_name,
            company_description,
            website,
            logo_url,
            brand_color,
            hiring_preferences
        )
    )

    conn.commit()

    cursor.execute(
        """
        SELECT
            company_name,
            company_description,
            website,
            logo_url,
            brand_color,
            hiring_preferences,
            created_at,
            updated_at
        FROM company_profiles
        WHERE employer_id = ?
        """,
        (employer["id"],)
    )

    saved_profile = dict(cursor.fetchone())
    conn.close()

    return {
        "message": "Company profile saved successfully.",
        "company_profile": saved_profile
    }

@app.get("/employer/jobs")
def get_employer_jobs(request: Request):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM jobs
        WHERE employer_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (employer["id"],)
    )

    rows = cursor.fetchall()
    jobs = [dict(row) for row in rows]

    conn.close()

    return {
        "jobs": jobs
    }


@app.post("/jobs", status_code=201)
def add_job(job: Job, request: Request):
    employer = require_employer(request)

    if job.application_method not in APPLICATION_METHODS:
        raise HTTPException(
            status_code=400,
            detail="Invalid application method."
        )

    if job.status not in JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid job status."
        )

    cleaned_title = job.title.strip()
    cleaned_company = job.company.strip()
    cleaned_location = job.location.strip()
    cleaned_pay = job.pay.strip()
    cleaned_description = job.description.strip()
    cleaned_requirements = (job.requirements or "").strip()
    cleaned_preferred_qualifications = (
        job.preferred_qualifications or ""
    ).strip()
    cleaned_schedule = job.schedule.strip()
    cleaned_experience = job.experience.strip()
    cleaned_category = classify_category(
        cleaned_title,
        [job.category, cleaned_description[:500]]
    )
    cleaned_application_deadline = clean_application_deadline(
        job.application_deadline
    )

    if (
        cleaned_application_deadline
        and deadline_has_passed(cleaned_application_deadline)
    ):
        raise HTTPException(
            status_code=400,
            detail="Application deadline cannot be in the past."
        )

    required_values = [
        cleaned_title,
        cleaned_company,
        cleaned_location,
        cleaned_pay,
        cleaned_description,
        cleaned_schedule,
        cleaned_experience,
        cleaned_category
    ]

    if not all(required_values):
        raise HTTPException(
            status_code=400,
            detail="All job fields are required."
        )

    if len(cleaned_requirements) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Job requirements must be 5,000 characters or fewer."
        )

    if len(cleaned_preferred_qualifications) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Preferred qualifications must be 5,000 characters or fewer."
        )

    cleaned_application_url = (
        job.application_url.strip()
        if job.application_url
        else None
    )

    if (
        job.application_method == "employer_website"
        and not cleaned_application_url
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "An employer application URL is required "
                "for employer-website jobs."
            )
        )

    if job.application_method == "pathforge":
        cleaned_application_url = None

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO jobs (
            title,
            company,
            location,
            pay,
            description,
            requirements,
            preferred_qualifications,
            schedule,
            experience,
            category,
            application_method,
            application_url,
            employer_id,
            status,
            application_deadline,
            created_at,
            updated_at
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        (
            cleaned_title,
            cleaned_company,
            cleaned_location,
            cleaned_pay,
            cleaned_description,
            cleaned_requirements or None,
            cleaned_preferred_qualifications or None,
            cleaned_schedule,
            cleaned_experience,
            cleaned_category,
            job.application_method,
            cleaned_application_url,
            employer["id"],
            job.status,
            cleaned_application_deadline
        )
    )

    job_id = cursor.lastrowid

    cursor.execute(
        """
        SELECT *
        FROM jobs
        WHERE id = ?
        """,
        (job_id,)
    )

    created_job = dict(cursor.fetchone())

    conn.commit()
    conn.close()

    return {
        "message": "Job created successfully.",
        "job": created_job
    }


@app.put("/employer/jobs/{job_id}")
def update_employer_job(
    job_id: int,
    job: Job,
    request: Request
):
    employer = require_employer(request)

    if job.application_method not in APPLICATION_METHODS:
        raise HTTPException(
            status_code=400,
            detail="Invalid application method."
        )

    if job.status not in JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid job status."
        )

    cleaned_title = job.title.strip()
    cleaned_company = job.company.strip()
    cleaned_location = job.location.strip()
    cleaned_pay = job.pay.strip()
    cleaned_description = job.description.strip()
    cleaned_requirements = (job.requirements or "").strip()
    cleaned_preferred_qualifications = (
        job.preferred_qualifications or ""
    ).strip()
    cleaned_schedule = job.schedule.strip()
    cleaned_experience = job.experience.strip()
    cleaned_category = classify_category(
        cleaned_title,
        [job.category, cleaned_description[:500]]
    )
    cleaned_application_deadline = clean_application_deadline(
        job.application_deadline
    )

    required_values = [
        cleaned_title,
        cleaned_company,
        cleaned_location,
        cleaned_pay,
        cleaned_description,
        cleaned_schedule,
        cleaned_experience,
        cleaned_category
    ]

    if not all(required_values):
        raise HTTPException(
            status_code=400,
            detail="All job fields are required."
        )

    if len(cleaned_requirements) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Job requirements must be 5,000 characters or fewer."
        )

    if len(cleaned_preferred_qualifications) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Preferred qualifications must be 5,000 characters or fewer."
        )

    cleaned_application_url = (
        job.application_url.strip()
        if job.application_url
        else None
    )

    if (
        job.application_method == "employer_website"
        and not cleaned_application_url
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "An employer application URL is required "
                "for employer-website jobs."
            )
        )

    if job.application_method == "pathforge":
        cleaned_application_url = None

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    existing_job = cursor.execute(
        "SELECT * FROM jobs WHERE id = ? AND employer_id = ?",
        (job_id, employer["id"]),
    ).fetchone()
    if not existing_job:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found.")

    proposed_values = {
        "title": cleaned_title, "company": cleaned_company,
        "location": cleaned_location, "pay": cleaned_pay,
        "description": cleaned_description,
        "requirements": cleaned_requirements or None,
        "preferred_qualifications": cleaned_preferred_qualifications or None,
        "schedule": cleaned_schedule, "experience": cleaned_experience,
        "category": cleaned_category, "application_method": job.application_method,
        "application_url": cleaned_application_url, "status": job.status,
        "application_deadline": cleaned_application_deadline,
    }
    record_job_changes(cursor, job_id, existing_job, proposed_values, "employer")

    cursor.execute(
        """
        UPDATE jobs
        SET
            title = ?,
            company = ?,
            location = ?,
            pay = ?,
            description = ?,
            requirements = ?,
            preferred_qualifications = ?,
            schedule = ?,
            experience = ?,
            category = ?,
            application_method = ?,
            application_url = ?,
            status = ?,
            application_deadline = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            cleaned_title,
            cleaned_company,
            cleaned_location,
            cleaned_pay,
            cleaned_description,
            cleaned_requirements or None,
            cleaned_preferred_qualifications or None,
            cleaned_schedule,
            cleaned_experience,
            cleaned_category,
            job.application_method,
            cleaned_application_url,
            job.status,
            cleaned_application_deadline,
            job_id,
            employer["id"]
        )
    )

    if cursor.rowcount == 0:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    cursor.execute(
        """
        SELECT *
        FROM jobs
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            job_id,
            employer["id"]
        )
    )

    updated_job = dict(cursor.fetchone())

    conn.commit()
    conn.close()

    return {
        "message": "Job updated successfully.",
        "job": updated_job
    }


@app.patch("/employer/jobs/{job_id}/status")
def update_employer_job_status(
    job_id: int,
    status_update: JobStatusUpdate,
    request: Request
):
    employer = require_employer(request)

    if status_update.status not in JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid job status."
        )

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    existing_job = cursor.execute(
        "SELECT * FROM jobs WHERE id = ? AND employer_id = ?",
        (job_id, employer["id"]),
    ).fetchone()
    if not existing_job:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found.")
    record_job_changes(
        cursor, job_id, existing_job, {"status": status_update.status}, "employer"
    )

    cursor.execute(
        """
        UPDATE jobs
        SET
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            status_update.status,
            job_id,
            employer["id"]
        )
    )

    if cursor.rowcount == 0:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    conn.commit()
    conn.close()

    return {
        "message": "Job status updated successfully.",
        "job_id": job_id,
        "status": status_update.status
    }


@app.delete("/employer/jobs/{job_id}")
def delete_employer_job(
    job_id: int,
    request: Request
):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM jobs
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            job_id,
            employer["id"]
        )
    )

    owned_job = cursor.fetchone()

    if not owned_job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE job_id = ?
        """,
        (job_id,)
    )

    application_count = cursor.fetchone()[0]

    if application_count > 0:
        conn.close()

        raise HTTPException(
            status_code=409,
            detail=(
                "This job already has tracked applications. "
                "Close the job instead of deleting it."
            )
        )

    # SQLite foreign keys may not be enabled on older connections,
    # so saved-job relationships are removed explicitly.
    cursor.execute(
        """
        DELETE FROM saved_jobs
        WHERE job_id = ?
        """,
        (job_id,)
    )

    cursor.execute(
        """
        DELETE FROM jobs
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            job_id,
            employer["id"]
        )
    )

    conn.commit()
    conn.close()

    return {
        "message": "Job deleted successfully.",
        "job_id": job_id
    }

@app.get("/applications")
def get_applications(request: Request):
    user = get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.id,
            applications.job_id,
            applications.application_method,
            applications.status,
            applications.applied_at,
            applications.interview_date,
            applications.interview_time,
            applications.interview_format,
            applications.interview_location,
            applications.interview_details,
            applications.follow_up_date,
            applications.notes,
            applications.created_at,
            applications.updated_at,

            CASE
                WHEN applications.application_method = 'pathforge'
                 AND jobs.employer_id IS NOT NULL
                THEN 1
                ELSE 0
            END AS employer_managed,

            jobs.title,
            jobs.company,
            jobs.location,
            jobs.pay,
            jobs.schedule,
            jobs.experience,
            jobs.category,
            jobs.application_deadline
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
        ORDER BY applications.updated_at DESC
        """,
        (user["id"],)
    )

    applications = [
        dict(row)
        for row in cursor.fetchall()
    ]

    history_by_application = {
        application["id"]: []
        for application in applications
    }

    if applications:
        application_ids = [
            application["id"]
            for application in applications
        ]
        placeholders = ",".join("?" for _ in application_ids)

        cursor.execute(
            f"""
            SELECT
                id,
                application_id,
                event_type,
                field_name,
                old_value,
                new_value,
                changed_by_type,
                created_at
            FROM application_history
            WHERE application_id IN ({placeholders})
            ORDER BY created_at DESC, id DESC
            """,
            application_ids
        )

        for history_row in cursor.fetchall():
            history_entry = dict(history_row)
            history_by_application[
                history_entry["application_id"]
            ].append(history_entry)

    for application in applications:
        application_history = history_by_application[application["id"]]
        application["history"] = application_history
        application["last_update_source"] = (
            application_history[0]["changed_by_type"]
            if application_history
            else (
                "employer"
                if application["employer_managed"]
                else "user"
            )
        )

    conn.close()

    return {
        "applications": applications
    }


@app.put("/employer/jobs/{job_id}/application-form")
def update_job_application_form(
    job_id: int,
    form: ApplicationFormUpdate,
    request: Request
):
    employer = require_employer(request)

    if len(form.questions) > 10:
        raise HTTPException(
            status_code=400,
            detail=(
                "An application form can contain "
                "no more than 10 questions."
            )
        )

    cleaned_questions = []
    seen_questions = set()

    for index, question in enumerate(form.questions):
        cleaned_text = question.question_text.strip()

        if not cleaned_text:
            raise HTTPException(
                status_code=400,
                detail="Application questions cannot be blank."
            )

        if len(cleaned_text) > 300:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Application questions cannot exceed "
                    "300 characters."
                )
            )

        if question.field_type not in APPLICATION_QUESTION_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Invalid application question type."
            )

        normalized_text = cleaned_text.casefold()

        if normalized_text in seen_questions:
            raise HTTPException(
                status_code=400,
                detail="Duplicate application questions are not allowed."
            )

        seen_questions.add(normalized_text)

        cleaned_questions.append({
            "question_text": cleaned_text,
            "field_type": question.field_type,
            "is_required": 1 if question.is_required else 0,
            "display_order": index
        })

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            application_method
        FROM jobs
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            job_id,
            employer["id"]
        )
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    if job["application_method"] != "pathforge":
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Custom application forms are only available "
                "for jobs using PathForge applications."
            )
        )

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE job_id = ?
          AND application_method = 'pathforge'
        """,
        (job_id,)
    )

    existing_application_count = cursor.fetchone()[0]

    if existing_application_count > 0:
        conn.close()

        raise HTTPException(
            status_code=409,
            detail=(
                "This application form cannot be changed "
                "after candidates have applied."
            )
        )

    try:
        cursor.execute(
            """
            DELETE FROM application_questions
            WHERE job_id = ?
            """,
            (job_id,)
        )

        for question in cleaned_questions:
            cursor.execute(
                """
                INSERT INTO application_questions (
                    job_id,
                    question_text,
                    field_type,
                    is_required,
                    display_order
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    question["question_text"],
                    question["field_type"],
                    question["is_required"],
                    question["display_order"]
                )
            )

        conn.commit()

    except sqlite3.Error:
        conn.rollback()
        conn.close()

        raise HTTPException(
            status_code=500,
            detail="The application form could not be saved."
        )

    conn.close()

    return {
        "message": "Application form saved successfully.",
        "question_count": len(cleaned_questions)
    }


@app.get("/employer/jobs/{job_id}/application-form")
def get_employer_job_application_form(
    job_id: int,
    request: Request
):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM jobs
        WHERE id = ?
          AND employer_id = ?
        """,
        (
            job_id,
            employer["id"]
        )
    )

    if not cursor.fetchone():
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    cursor.execute(
        """
        SELECT
            id,
            question_text,
            field_type,
            is_required,
            display_order
        FROM application_questions
        WHERE job_id = ?
        ORDER BY display_order, id
        """,
        (job_id,)
    )

    questions = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "job_id": job_id,
        "questions": questions
    }


@app.get("/jobs/{job_id}/application-form")
def get_job_application_form(
    job_id: int,
    request: Request
):
    get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            title,
            company,
            application_method,
            employer_id,
            status,
            application_deadline
        FROM jobs
        WHERE id = ?
        """,
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    if job["status"] != "active":
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="This job is not currently accepting applications."
        )

    if deadline_has_passed(job["application_deadline"]):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="The application deadline for this job has passed."
        )

    if (
        job["application_method"] != "pathforge"
        or job["employer_id"] is None
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "This job does not use an internal "
                "PathForge application form."
            )
        )

    cursor.execute(
        """
        SELECT
            id,
            question_text,
            field_type,
            is_required,
            display_order
        FROM application_questions
        WHERE job_id = ?
        ORDER BY display_order, id
        """,
        (job_id,)
    )

    questions = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "job": {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"]
        },
        "questions": questions
    }


@app.post("/jobs/{job_id}/apply-internally", status_code=201)
def submit_internal_application(
    job_id: int,
    submission: InternalApplicationSubmit,
    request: Request
):
    user = get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            employer_id,
            application_method,
            status,
            application_deadline
        FROM jobs
        WHERE id = ?
        """,
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    if job["status"] != "active":
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="This job is not currently accepting applications."
        )

    if deadline_has_passed(job["application_deadline"]):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="The application deadline for this job has passed."
        )

    if (
        job["application_method"] != "pathforge"
        or job["employer_id"] is None
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "This job does not accept internal "
                "PathForge applications."
            )
        )

    if job["employer_id"] == user["id"]:
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="You cannot apply to your own job."
        )

    cursor.execute(
        """
        SELECT
            id,
            question_text,
            field_type,
            is_required
        FROM application_questions
        WHERE job_id = ?
        ORDER BY display_order, id
        """,
        (job_id,)
    )

    questions = cursor.fetchall()
    questions_by_id = {
        question["id"]: question
        for question in questions
    }

    submitted_answers = {}

    for answer in submission.answers:
        if answer.question_id not in questions_by_id:
            conn.close()

            raise HTTPException(
                status_code=400,
                detail="The application contains an invalid answer."
            )

        if answer.question_id in submitted_answers:
            conn.close()

            raise HTTPException(
                status_code=400,
                detail="A question was answered more than once."
            )

        cleaned_answer = (
            answer.answer_text.strip()
            if answer.answer_text
            else ""
        )

        question = questions_by_id[answer.question_id]

        if (
            question["field_type"] == "yes_no"
            and cleaned_answer not in {"Yes", "No"}
        ):
            conn.close()

            raise HTTPException(
                status_code=400,
                detail=(
                    "Yes-or-no questions must be answered "
                    "with Yes or No."
                )
            )

        if len(cleaned_answer) > 5000:
            conn.close()

            raise HTTPException(
                status_code=400,
                detail=(
                    "An application answer cannot exceed "
                    "5,000 characters."
                )
            )

        submitted_answers[answer.question_id] = cleaned_answer

    for question in questions:
        answer_text = submitted_answers.get(
            question["id"],
            ""
        )

        if question["is_required"] and not answer_text:
            conn.close()

            raise HTTPException(
                status_code=400,
                detail=(
                    "Please answer every required "
                    "application question."
                )
            )

    applied_at = datetime.now(
        timezone.utc
    ).date().isoformat()

    try:
        cursor.execute(
            """
            INSERT INTO applications (
                user_id,
                job_id,
                application_method,
                status,
                applied_at,
                interview_date,
                follow_up_date,
                notes
            )
            VALUES (?, ?, 'pathforge', 'Applied', ?, NULL, NULL, NULL)
            """,
            (
                user["id"],
                job_id,
                applied_at
            )
        )

        application_id = cursor.lastrowid

        record_application_history(
            cursor,
            application_id,
            "application_created",
            "status",
            None,
            "Applied",
            "user",
            user["id"]
        )

        for question in questions:
            answer_text = submitted_answers.get(
                question["id"],
                ""
            )

            cursor.execute(
                """
                INSERT INTO application_answers (
                    application_id,
                    question_id,
                    answer_text
                )
                VALUES (?, ?, ?)
                """,
                (
                    application_id,
                    question["id"],
                    answer_text
                )
            )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()

        raise HTTPException(
            status_code=409,
            detail="You have already applied to this job."
        )

    except sqlite3.Error:
        conn.rollback()
        conn.close()

        raise HTTPException(
            status_code=500,
            detail="Your application could not be submitted."
        )

    conn.close()

    return {
        "message": "Your application was submitted successfully.",
        "application_id": application_id,
        "status": "Applied",
        "applied_at": applied_at
    }


@app.get("/employer/applications")
def get_employer_applications(request: Request):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.id,
            applications.job_id,
            applications.status,
            applications.applied_at,
            applications.interview_date,
            applications.interview_time,
            applications.interview_format,
            applications.interview_location,
            applications.interview_details,
            applications.employer_notes,
            applications.created_at,
            applications.updated_at,
            users.id AS applicant_user_id,
            users.username,
            users.email,
            jobs.title AS job_title,
            jobs.company,
            jobs.application_deadline
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        JOIN users
            ON users.id = applications.user_id
        WHERE jobs.employer_id = ?
          AND applications.application_method = 'pathforge'
        ORDER BY applications.created_at DESC
        """,
        (employer["id"],)
    )

    application_rows = cursor.fetchall()
    employer_applications = []

    for application_row in application_rows:
        application = dict(application_row)

        cursor.execute(
            """
            SELECT
                application_questions.id AS question_id,
                application_questions.question_text,
                application_questions.field_type,
                application_questions.is_required,
                application_answers.answer_text
            FROM application_answers
            JOIN application_questions
                ON application_questions.id =
                   application_answers.question_id
            WHERE application_answers.application_id = ?
            ORDER BY
                application_questions.display_order,
                application_questions.id
            """,
            (application["id"],)
        )

        application["answers"] = [
            dict(answer)
            for answer in cursor.fetchall()
        ]

        employer_applications.append(application)

    conn.close()

    return {
        "applications": employer_applications
    }

@app.put("/employer/applications/{application_id}")
def update_employer_application(
    application_id: int,
    update: EmployerApplicationUpdate,
    request: Request
):
    employer = require_employer(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.id,
            applications.status,
            applications.interview_date,
            applications.interview_time,
            applications.interview_format,
            applications.interview_location,
            applications.interview_details,
            applications.employer_notes
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.id = ?
          AND jobs.employer_id = ?
          AND applications.application_method = 'pathforge'
        """,
        (
            application_id,
            employer["id"]
        )
    )

    existing = cursor.fetchone()

    if not existing:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    updated_status = (
        update.status
        if update.status is not None
        else existing["status"]
    )

    if updated_status not in APPLICATION_STATUSES:
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="Invalid application status."
        )

    updated_interview_date = (
        update.interview_date.strip()
        if update.interview_date is not None
        else existing["interview_date"]
    )

    updated_interview_time = (
        update.interview_time.strip()
        if update.interview_time is not None
        else existing["interview_time"]
    )

    updated_interview_format = (
        update.interview_format.strip()
        if update.interview_format is not None
        else existing["interview_format"]
    )

    updated_interview_location = (
        update.interview_location.strip()
        if update.interview_location is not None
        else existing["interview_location"]
    )

    updated_interview_details = (
        update.interview_details.strip()
        if update.interview_details is not None
        else existing["interview_details"]
    )

    updated_employer_notes = (
        update.employer_notes.strip()
        if update.employer_notes is not None
        else existing["employer_notes"]
    )

    # Converts blank optional values to NULL.
    updated_interview_date = (
        updated_interview_date or None
    )

    updated_interview_time = (
        updated_interview_time or None
    )

    updated_interview_format = (
        updated_interview_format or None
    )

    updated_interview_location = (
        updated_interview_location or None
    )

    updated_interview_details = (
        updated_interview_details or None
    )

    updated_employer_notes = (
        updated_employer_notes or None
    )

    if (
        updated_interview_format is not None
        and updated_interview_format not in INTERVIEW_FORMATS
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail="Invalid interview format."
        )

    if (
        updated_status == "Interview Scheduled"
        and (
            not updated_interview_date
            or not updated_interview_time
            or not updated_interview_format
        )
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Interview date, time, and format are required "
                "when scheduling an interview."
            )
        )

    if (
        updated_status == "Interview Scheduled"
        and updated_interview_format in {
            "In Person",
            "Video"
        }
        and not updated_interview_location
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Enter an interview address or video meeting link."
            )
        )

    if (
        updated_interview_location
        and len(updated_interview_location) > 500
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Interview location cannot exceed "
                "500 characters."
            )
        )

    if (
        updated_interview_details
        and len(updated_interview_details) > 2000
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Interview details cannot exceed "
                "2,000 characters."
            )
        )

    if (
        updated_employer_notes
        and len(updated_employer_notes) > 5000
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Employer notes cannot exceed "
                "5,000 characters."
            )
        )

    cursor.execute(
        """
        UPDATE applications
        SET
            status = ?,
            interview_date = ?,
            interview_time = ?,
            interview_format = ?,
            interview_location = ?,
            interview_details = ?,
            employer_notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            updated_status,
            updated_interview_date,
            updated_interview_time,
            updated_interview_format,
            updated_interview_location,
            updated_interview_details,
            updated_employer_notes,
            application_id
        )
    )

    employer_history_changes = [
        (
            "status_changed",
            "status",
            existing["status"],
            updated_status
        ),
        (
            "interview_updated",
            "interview_date",
            existing["interview_date"],
            updated_interview_date
        ),
        (
            "interview_updated",
            "interview_time",
            existing["interview_time"],
            updated_interview_time
        ),
        (
            "interview_updated",
            "interview_format",
            existing["interview_format"],
            updated_interview_format
        ),
        (
            "interview_updated",
            "interview_location",
            existing["interview_location"],
            updated_interview_location
        ),
        (
            "interview_updated",
            "interview_details",
            existing["interview_details"],
            updated_interview_details
        )
    ]

    for (
        event_type,
        field_name,
        old_value,
        new_value
    ) in employer_history_changes:
        record_application_history(
            cursor,
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            "employer",
            employer["id"]
        )

    conn.commit()

    cursor.execute(
        """
        SELECT
            id,
            job_id,
            status,
            applied_at,
            interview_date,
            interview_time,
            interview_format,
            interview_location,
            interview_details,
            employer_notes,
            updated_at
        FROM applications
        WHERE id = ?
        """,
        (application_id,)
    )

    updated_application = dict(cursor.fetchone())

    conn.close()

    return {
        "message": "Application updated successfully.",
        "application": updated_application
    }

@app.post("/applications/external-capture", status_code=201)
def capture_external_application(
    application: ExternalApplicationCapture,
    request: Request
):
    user = get_authenticated_user(request)
    title = application.title.strip()
    company = application.company.strip()
    location = application.location.strip() or "Not listed"
    application_url = (application.application_url or "").strip() or None
    notes = (application.notes or "").strip() or None

    if not title or not company:
        raise HTTPException(status_code=400, detail="Job title and company are required.")
    if len(title) > 180 or len(company) > 180 or len(location) > 240:
        raise HTTPException(status_code=400, detail="One or more job details are too long.")
    if application_url and not re.match(r"^https://[^\s]+$", application_url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Enter a complete HTTPS application link.")
    if application.status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid application status.")
    if notes and len(notes) > 5000:
        raise HTTPException(status_code=400, detail="Notes must be 5,000 characters or fewer.")

    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO jobs (
                title, company, location, pay, description, schedule,
                experience, category, application_method, application_url,
                owner_user_id, status, source, verification_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'Not listed', ?, 'Not listed', 'Not listed', ?,
                      'employer_website', ?, ?, 'active',
                      'User-provided external application', 'unverified',
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                title, company, location,
                "Private tracker reference entered by the user.",
                classify_category(title, []), application_url, user["id"]
            )
        )
        job_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO applications (
                user_id, job_id, application_method, status, applied_at,
                follow_up_date, notes
            ) VALUES (?, ?, 'employer_website', ?, ?, ?, ?)
            """,
            (
                user["id"], job_id, application.status,
                application.applied_at, application.follow_up_date, notes
            )
        )
        application_id = cursor.lastrowid
        record_application_history(
            cursor, application_id, "application_created", "status",
            None, application.status, "user", user["id"]
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "message": "External application added privately to your tracker.",
        "application_id": application_id
    }


@app.post("/applications")
def create_application(
    application: ApplicationCreate,
    request: Request
):
    user = get_authenticated_user(request)

    if application.application_method not in APPLICATION_METHODS:
        raise HTTPException(
            status_code=400,
            detail="Invalid application method."
        )

    if application.status not in APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid application status."
        )

    conn = get_connection(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            employer_id,
            application_method
        FROM jobs
        WHERE id = ?
        """,
        (application.job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    if (
        application.application_method == "pathforge"
        and job[1] is not None
    ):
        conn.close()

        raise HTTPException(
            status_code=400,
            detail=(
                "Submit this employer's PathForge "
                "application form to apply."
            )
        )

    try:
        cursor.execute(
            """
            INSERT INTO applications (
                user_id,
                job_id,
                application_method,
                status,
                applied_at,
                interview_date,
                follow_up_date,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                application.job_id,
                application.application_method,
                application.status,
                application.applied_at,
                application.interview_date,
                application.follow_up_date,
                application.notes
            )
        )

        application_id = cursor.lastrowid

        record_application_history(
            cursor,
            application_id,
            "application_created",
            "status",
            None,
            application.status,
            "user",
            user["id"]
        )
        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        raise HTTPException(
            status_code=409,
            detail="This job is already in your Application Tracker."
        )

    conn.close()

    return {
        "message": "Application added to your tracker.",
        "application_id": application_id
    }


@app.put("/applications/{application_id}")
def update_application(
    application_id: int,
    application: ApplicationUpdate,
    request: Request
):
    user = get_authenticated_user(request)

    if (
        application.status is not None
        and application.status not in APPLICATION_STATUSES
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid application status."
        )

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.*,
            jobs.employer_id
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.id = ?
          AND applications.user_id = ?
        """,
        (
            application_id,
            user["id"]
        )
    )

    existing_application = cursor.fetchone()

    if not existing_application:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    employer_managed = (
        existing_application["application_method"] == "pathforge"
        and existing_application["employer_id"] is not None
    )

    if (
        employer_managed
        and (
            application.status is not None
            or application.applied_at is not None
            or application.interview_date is not None
            or application.interview_time is not None
            or application.interview_format is not None
            or application.interview_location is not None
            or application.interview_details is not None
        )
    ):
        conn.close()

        raise HTTPException(
            status_code=403,
            detail=(
                "Status and interview details for this "
                "application are managed by the employer."
            )
        )

    updated_status = (
        application.status
        if application.status is not None
        else existing_application["status"]
    )

    updated_applied_at = (
        application.applied_at
        if application.applied_at is not None
        else existing_application["applied_at"]
    )

    updated_interview_date = (
        application.interview_date
        if application.interview_date is not None
        else existing_application["interview_date"]
    )

    updated_interview_time = (
        application.interview_time.strip()
        if application.interview_time is not None
        else existing_application["interview_time"]
    )

    updated_interview_format = (
        application.interview_format.strip()
        if application.interview_format is not None
        else existing_application["interview_format"]
    )

    updated_interview_location = (
        application.interview_location.strip()
        if application.interview_location is not None
        else existing_application["interview_location"]
    )

    updated_interview_details = (
        application.interview_details.strip()
        if application.interview_details is not None
        else existing_application["interview_details"]
    )

    updated_interview_time = updated_interview_time or None
    updated_interview_format = updated_interview_format or None
    updated_interview_location = updated_interview_location or None
    updated_interview_details = updated_interview_details or None

    if (
        updated_interview_format is not None
        and updated_interview_format not in INTERVIEW_FORMATS
    ):
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Invalid interview format."
        )

    if (
        updated_interview_location
        and len(updated_interview_location) > 500
    ):
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Interview location cannot exceed 500 characters."
        )

    if (
        updated_interview_details
        and len(updated_interview_details) > 2000
    ):
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Interview details cannot exceed 2,000 characters."
        )

    updated_follow_up_date = (
        application.follow_up_date
        if application.follow_up_date is not None
        else existing_application["follow_up_date"]
    )

    updated_notes = (
        application.notes
        if application.notes is not None
        else existing_application["notes"]
    )

    cursor.execute(
        """
        UPDATE applications
        SET
            status = ?,
            applied_at = ?,
            interview_date = ?,
            interview_time = ?,
            interview_format = ?,
            interview_location = ?,
            interview_details = ?,
            follow_up_date = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND user_id = ?
        """,
        (
            updated_status,
            updated_applied_at,
            updated_interview_date,
            updated_interview_time,
            updated_interview_format,
            updated_interview_location,
            updated_interview_details,
            updated_follow_up_date,
            updated_notes,
            application_id,
            user["id"]
        )
    )

    user_history_changes = [
        (
            "status_changed",
            "status",
            existing_application["status"],
            updated_status
        ),
        (
            "application_date_updated",
            "applied_at",
            existing_application["applied_at"],
            updated_applied_at
        ),
        (
            "interview_updated",
            "interview_date",
            existing_application["interview_date"],
            updated_interview_date
        ),
        (
            "interview_updated",
            "interview_time",
            existing_application["interview_time"],
            updated_interview_time
        ),
        (
            "interview_updated",
            "interview_format",
            existing_application["interview_format"],
            updated_interview_format
        ),
        (
            "interview_updated",
            "interview_location",
            existing_application["interview_location"],
            updated_interview_location
        ),
        (
            "interview_updated",
            "interview_details",
            existing_application["interview_details"],
            updated_interview_details
        ),
        (
            "follow_up_updated",
            "follow_up_date",
            existing_application["follow_up_date"],
            updated_follow_up_date
        )
    ]

    for (
        event_type,
        field_name,
        old_value,
        new_value
    ) in user_history_changes:
        record_application_history(
            cursor,
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            "user",
            user["id"]
        )

    conn.commit()

    cursor.execute(
        """
        SELECT
            id,
            application_id,
            event_type,
            field_name,
            old_value,
            new_value,
            changed_by_type,
            created_at
        FROM application_history
        WHERE application_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (application_id,)
    )
    application_history = [
        dict(history_row)
        for history_row in cursor.fetchall()
    ]

    conn.close()

    return {
        "message": "Application updated successfully.",
        "history": application_history,
        "last_update_source": "user"
    }


@app.delete("/applications/{application_id}")
def delete_application(
    application_id: int,
    request: Request
):
    user = get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.id,
            applications.job_id,
            applications.application_method,
            jobs.employer_id,
            jobs.owner_user_id
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.id = ?
          AND applications.user_id = ?
        """,
        (
            application_id,
            user["id"]
        )
    )

    existing_application = cursor.fetchone()

    if not existing_application:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    employer_managed = (
        existing_application["application_method"] == "pathforge"
        and existing_application["employer_id"] is not None
    )

    if employer_managed:
        conn.close()

        raise HTTPException(
            status_code=409,
            detail=(
                "Submitted PathForge applications cannot be "
                "removed from the tracker. Withdrawal support "
                "will be added to the hiring workflow."
            )
        )

    cursor.execute(
        """
        DELETE FROM applications
        WHERE id = ?
          AND user_id = ?
        """,
        (
            application_id,
            user["id"]
        )
    )

    removed = cursor.rowcount
    if removed and existing_application["owner_user_id"] == user["id"]:
        cursor.execute(
            "DELETE FROM jobs WHERE id = ? AND owner_user_id = ?",
            (existing_application["job_id"], user["id"])
        )
    conn.commit()
    conn.close()

    if removed == 0:
        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    return {
        "message": "Application removed from your tracker."
    }

@app.get("/account/security-events")
def get_security_events(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT event_type, event_summary, created_at FROM security_events WHERE user_id = ? ORDER BY id DESC LIMIT 25",
        (user["id"],),
    ).fetchall()
    conn.close()
    return {"events": [dict(row) for row in rows]}


@app.get("/account/data-download")
def download_account_data(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    export = {"generated_at": datetime.now(timezone.utc).isoformat(), "account": user}
    table_queries = {
        "profile": ("SELECT * FROM user_profiles WHERE user_id = ?",),
        "saved_jobs": ("SELECT * FROM saved_jobs WHERE user_id = ?",),
        "saved_searches": ("SELECT * FROM saved_searches WHERE user_id = ?",),
        "applications": ("SELECT * FROM applications WHERE user_id = ?",),
        "notifications": ("SELECT * FROM notifications WHERE user_id = ?",),
        "security_events": ("SELECT event_type, event_summary, created_at FROM security_events WHERE user_id = ?",),
    }
    for label, (query,) in table_queries.items():
        export[label] = [dict(row) for row in conn.execute(query, (user["id"],)).fetchall()]
    conn.close()
    return JSONResponse(
        content=export,
        headers={"Content-Disposition": "attachment; filename=pathforge-account-data.json"},
    )


@app.get("/account/privacy")
def get_privacy_settings(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT OR IGNORE INTO privacy_settings (user_id) VALUES (?)",
        (user["id"],),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM privacy_settings WHERE user_id = ?", (user["id"],)).fetchone()
    conn.close()
    return {
        "allow_personalized_guidance": bool(row["allow_personalized_guidance"]),
        "allow_employer_discovery": bool(row["allow_employer_discovery"]),
        "security_notifications": bool(row["security_notifications"]),
        "updated_at": row["updated_at"],
    }


@app.put("/account/privacy")
def update_privacy_settings(data: PrivacySettingsUpdate, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.execute(
        """
        INSERT INTO privacy_settings (
            user_id, allow_personalized_guidance, allow_employer_discovery,
            security_notifications, updated_at
        ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            allow_personalized_guidance = excluded.allow_personalized_guidance,
            allow_employer_discovery = excluded.allow_employer_discovery,
            security_notifications = excluded.security_notifications,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user["id"], int(data.allow_personalized_guidance),
            int(data.allow_employer_discovery), int(data.security_notifications),
        ),
    )
    conn.commit()
    conn.close()
    return {"message": "Privacy preferences saved."}


# Messaging access is limited to participants in an application conversation.
def get_message_conversation(cursor, conversation_id: int, user_id: int):
    row = cursor.execute(
        """
        SELECT message_conversations.*, applications.job_id, jobs.title, jobs.company,
               applicant.username AS applicant_username,
               employer.username AS employer_username
        FROM message_conversations
        JOIN applications ON applications.id = message_conversations.application_id
        JOIN jobs ON jobs.id = applications.job_id
        JOIN users applicant ON applicant.id = message_conversations.applicant_id
        JOIN users employer ON employer.id = message_conversations.employer_id
        WHERE message_conversations.id = ?
          AND (message_conversations.applicant_id = ? OR message_conversations.employer_id = ?)
        """,
        (conversation_id, user_id, user_id),
    ).fetchone()
    return row


@app.get("/messages/eligible")
def get_eligible_message_applications(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    if user["role"] == "employer":
        rows = conn.execute(
            """
            SELECT applications.id AS application_id, jobs.title, jobs.company,
                   applicants.username AS other_party,
                   message_conversations.id AS conversation_id
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            JOIN users applicants ON applicants.id = applications.user_id
            LEFT JOIN message_conversations ON message_conversations.application_id = applications.id
            WHERE jobs.employer_id = ? AND applications.application_method = 'pathforge'
            ORDER BY applications.updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT applications.id AS application_id, jobs.title, jobs.company,
                   employers.username AS other_party,
                   message_conversations.id AS conversation_id
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            JOIN users employers ON employers.id = jobs.employer_id
            LEFT JOIN message_conversations ON message_conversations.application_id = applications.id
            WHERE applications.user_id = ? AND applications.application_method = 'pathforge'
              AND jobs.employer_id IS NOT NULL
            ORDER BY applications.updated_at DESC
            """,
            (user["id"],),
        ).fetchall()
    conn.close()
    return {"applications": [dict(row) for row in rows]}


@app.post("/messages/conversations")
def create_message_conversation(data: ConversationCreate, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    application = cursor.execute(
        """
        SELECT applications.id, applications.user_id AS applicant_id,
               applications.application_method, jobs.employer_id
        FROM applications JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.id = ?
        """,
        (data.application_id,),
    ).fetchone()
    if not application or application["application_method"] != "pathforge" or not application["employer_id"]:
        conn.close()
        raise HTTPException(status_code=404, detail="Messaging is unavailable for this application.")
    if user["id"] not in {application["applicant_id"], application["employer_id"]}:
        conn.close()
        raise HTTPException(status_code=403, detail="You are not a participant in this application.")
    cursor.execute(
        """
        INSERT OR IGNORE INTO message_conversations (application_id, applicant_id, employer_id)
        VALUES (?, ?, ?)
        """,
        (application["id"], application["applicant_id"], application["employer_id"]),
    )
    conn.commit()
    conversation_id = cursor.execute(
        "SELECT id FROM message_conversations WHERE application_id = ?",
        (application["id"],),
    ).fetchone()[0]
    conn.close()
    return {"conversation_id": conversation_id}


@app.get("/messages/conversations")
def list_message_conversations(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT c.id, c.application_id, c.applicant_id, c.employer_id,
               c.applicant_blocked, c.employer_blocked, c.updated_at,
               jobs.title, jobs.company,
               CASE WHEN c.applicant_id = ? THEN employer.username ELSE applicant.username END AS other_party,
               (SELECT body FROM direct_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_message,
               (SELECT created_at FROM direct_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_message_at,
               (SELECT COUNT(*) FROM direct_messages WHERE conversation_id = c.id AND sender_id != ? AND is_read = 0) AS unread_count
        FROM message_conversations c
        JOIN applications ON applications.id = c.application_id
        JOIN jobs ON jobs.id = applications.job_id
        JOIN users applicant ON applicant.id = c.applicant_id
        JOIN users employer ON employer.id = c.employer_id
        WHERE c.applicant_id = ? OR c.employer_id = ?
        ORDER BY COALESCE(last_message_at, c.updated_at) DESC
        """,
        (user["id"], user["id"], user["id"], user["id"]),
    ).fetchall()
    conn.close()
    return {"conversations": [dict(row) for row in rows]}


@app.get("/messages/conversations/{conversation_id}")
def get_conversation_messages(conversation_id: int, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    conversation = get_message_conversation(cursor, conversation_id, user["id"])
    if not conversation:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found.")
    cursor.execute(
        "UPDATE direct_messages SET is_read = 1 WHERE conversation_id = ? AND sender_id != ?",
        (conversation_id, user["id"]),
    )
    conn.commit()
    messages = cursor.execute(
        """
        SELECT direct_messages.id, direct_messages.sender_id, direct_messages.body,
               direct_messages.created_at, users.username AS sender_username
        FROM direct_messages JOIN users ON users.id = direct_messages.sender_id
        WHERE direct_messages.conversation_id = ? ORDER BY direct_messages.id
        """,
        (conversation_id,),
    ).fetchall()
    conn.close()
    result = dict(conversation)
    result["messages"] = [dict(row) for row in messages]
    result["current_user_id"] = user["id"]
    return result


@app.post("/messages/conversations/{conversation_id}")
def send_conversation_message(conversation_id: int, data: DirectMessageCreate, request: Request):
    user = get_authenticated_user(request)
    body = data.body.strip()
    if not body or len(body) > 2000:
        raise HTTPException(status_code=400, detail="Messages must contain 1–2,000 characters.")
    sensitive_patterns = [r"\b\d{3}-\d{2}-\d{4}\b", r"\b(?:\d[ -]*?){13,16}\b", r"\b(?:routing|bank account)\s*(?:number)?\b"]
    if any(re.search(pattern, body, re.IGNORECASE) for pattern in sensitive_patterns):
        raise HTTPException(status_code=400, detail="Do not send Social Security, payment-card, routing, or bank-account information through PathForge.")
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    conversation = get_message_conversation(cursor, conversation_id, user["id"])
    if not conversation:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation["applicant_blocked"] or conversation["employer_blocked"]:
        conn.close()
        raise HTTPException(status_code=403, detail="This conversation is blocked.")
    recent_count = cursor.execute(
        "SELECT COUNT(*) FROM direct_messages WHERE conversation_id = ? AND sender_id = ? AND datetime(created_at) > datetime('now', '-1 minute')",
        (conversation_id, user["id"]),
    ).fetchone()[0]
    duplicate = cursor.execute(
        "SELECT 1 FROM direct_messages WHERE conversation_id = ? AND sender_id = ? AND body = ? AND datetime(created_at) > datetime('now', '-2 minutes')",
        (conversation_id, user["id"], body),
    ).fetchone()
    if recent_count >= 5 or duplicate:
        conn.close()
        raise HTTPException(status_code=429, detail="Please slow down and avoid sending duplicate messages.")
    cursor.execute("INSERT INTO direct_messages (conversation_id, sender_id, body) VALUES (?, ?, ?)", (conversation_id, user["id"], body))
    message_id = cursor.lastrowid
    recipient_id = conversation["employer_id"] if user["id"] == conversation["applicant_id"] else conversation["applicant_id"]
    cursor.execute("UPDATE message_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    cursor.execute(
        """
        INSERT OR IGNORE INTO notifications (user_id, notification_type, title, message, href, event_key)
        VALUES (?, 'application_update', 'New PathForge message', ?, ?, ?)
        """,
        (recipient_id, f"New message about {conversation['title']}.", f"messages.html?conversation={conversation_id}", f"message-{message_id}"),
    )
    conn.commit()
    conn.close()
    return {"message": "Message sent.", "message_id": message_id}


@app.put("/messages/conversations/{conversation_id}/block")
def update_conversation_block(conversation_id: int, data: ConversationBlockUpdate, request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    conversation = get_message_conversation(cursor, conversation_id, user["id"])
    if not conversation:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found.")
    column = "applicant_blocked" if user["id"] == conversation["applicant_id"] else "employer_blocked"
    cursor.execute(f"UPDATE message_conversations SET {column} = ? WHERE id = ?", (int(data.blocked), conversation_id))
    conn.commit()
    conn.close()
    return {"message": "Conversation blocked." if data.blocked else "Conversation unblocked."}


@app.post("/messages/{message_id}/report")
def report_direct_message(message_id: int, data: MessageReportCreate, request: Request):
    user = get_authenticated_user(request)
    reason = data.reason.strip()
    if not reason or len(reason) > 500:
        raise HTTPException(status_code=400, detail="Provide a report reason of 1–500 characters.")
    conn = get_connection(DB_NAME)
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT direct_messages.sender_id, message_conversations.applicant_id, message_conversations.employer_id
        FROM direct_messages JOIN message_conversations ON message_conversations.id = direct_messages.conversation_id
        WHERE direct_messages.id = ?
        """,
        (message_id,),
    ).fetchone()
    if not row or user["id"] not in {row[1], row[2]} or user["id"] == row[0]:
        conn.close()
        raise HTTPException(status_code=403, detail="This message cannot be reported by your account.")
    cursor.execute("INSERT OR IGNORE INTO message_reports (message_id, reporter_id, reason) VALUES (?, ?, ?)", (message_id, user["id"], reason))
    conn.commit()
    conn.close()
    return {"message": "Message reported for review."}


@app.get("/analytics")
def get_practical_analytics(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if user["role"] == "employer":
        summary = cursor.execute(
            """
            SELECT COUNT(DISTINCT jobs.id) AS total_jobs,
                   COUNT(DISTINCT CASE WHEN jobs.status = 'active' THEN jobs.id END) AS active_jobs,
                   COUNT(applications.id) AS total_applications,
                   COUNT(CASE WHEN datetime(applications.created_at) >= datetime('now', '-30 days') THEN 1 END) AS applications_last_30_days,
                   COUNT(CASE WHEN applications.interview_date IS NOT NULL THEN 1 END) AS interviews_scheduled
            FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id
            WHERE jobs.employer_id = ?
            """,
            (user["id"],),
        ).fetchone()
        statuses = cursor.execute(
            """SELECT applications.status AS label, COUNT(*) AS count
               FROM applications JOIN jobs ON jobs.id = applications.job_id
               WHERE jobs.employer_id = ? GROUP BY applications.status ORDER BY count DESC""",
            (user["id"],),
        ).fetchall()
        activity = cursor.execute(
            """SELECT strftime('%Y-%W', applications.created_at) AS period, COUNT(*) AS count
               FROM applications JOIN jobs ON jobs.id = applications.job_id
               WHERE jobs.employer_id = ? AND datetime(applications.created_at) >= datetime('now', '-56 days')
               GROUP BY period ORDER BY period""",
            (user["id"],),
        ).fetchall()
        response = cursor.execute(
            """
            SELECT ROUND(AVG(julianday(first_update) - julianday(created_at)), 1)
            FROM (
                SELECT applications.id, applications.created_at, MIN(application_history.created_at) AS first_update
                FROM applications
                JOIN jobs ON jobs.id = applications.job_id
                JOIN application_history ON application_history.application_id = applications.id
                WHERE jobs.employer_id = ? AND application_history.changed_by_type = 'employer'
                GROUP BY applications.id
            ) WHERE first_update IS NOT NULL
            """,
            (user["id"],),
        ).fetchone()[0]
        result = {
            "role": "employer", "summary": dict(summary),
            "status_counts": [dict(row) for row in statuses], "weekly_activity": [dict(row) for row in activity],
            "average_first_update_days": response,
            "explanation": "Counts reflect recorded PathForge applications and employer updates; they are not hiring predictions.",
        }
    else:
        summary = cursor.execute(
            """
            SELECT COUNT(*) AS total_applications,
                   COUNT(CASE WHEN datetime(created_at) >= datetime('now', '-30 days') THEN 1 END) AS applications_last_30_days,
                   COUNT(CASE WHEN interview_date IS NOT NULL THEN 1 END) AS interviews_scheduled,
                   COUNT(CASE WHEN date(follow_up_date) < date('now') AND status NOT IN ('Accepted','Rejected','Withdrawn') THEN 1 END) AS overdue_follow_ups,
                   COUNT(CASE WHEN date(follow_up_date) >= date('now') AND status NOT IN ('Accepted','Rejected','Withdrawn') THEN 1 END) AS upcoming_follow_ups
            FROM applications WHERE user_id = ?
            """,
            (user["id"],),
        ).fetchone()
        saved_count = cursor.execute("SELECT COUNT(*) FROM saved_jobs WHERE user_id = ?", (user["id"],)).fetchone()[0]
        completed_followups = cursor.execute(
            """
            SELECT COUNT(*) FROM application_history h JOIN applications a ON a.id = h.application_id
            WHERE a.user_id = ? AND h.field_name = 'follow_up_date'
              AND h.old_value IS NOT NULL AND trim(h.old_value) != ''
              AND (h.new_value IS NULL OR trim(h.new_value) = '')
            """,
            (user["id"],),
        ).fetchone()[0]
        statuses = cursor.execute(
            "SELECT status AS label, COUNT(*) AS count FROM applications WHERE user_id = ? GROUP BY status ORDER BY count DESC",
            (user["id"],),
        ).fetchall()
        activity = cursor.execute(
            """SELECT strftime('%Y-%W', created_at) AS period, COUNT(*) AS count FROM applications
               WHERE user_id = ? AND datetime(created_at) >= datetime('now', '-56 days') GROUP BY period ORDER BY period""",
            (user["id"],),
        ).fetchall()
        result = {
            "role": "job_seeker", "summary": {**dict(summary), "saved_jobs": saved_count, "completed_follow_ups": completed_followups},
            "status_counts": [dict(row) for row in statuses], "weekly_activity": [dict(row) for row in activity],
            "explanation": "These are factual activity totals from your tracker. PathForge does not predict whether an application will succeed.",
        }
    conn.close()
    return result


@app.get("/me")
def get_current_user(request: Request):
    return get_authenticated_user(request)


@app.get("/session-status")
def get_session_status(request: Request):
    """Report optional session state without treating signed-out visitors as errors."""
    try:
        user = get_authenticated_user(request)
    except HTTPException as error:
        if error.status_code == 401:
            return {"authenticated": False, "user": None}
        raise
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        },
    }


    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in.")

    conn = get_connection(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, email FROM users WHERE id = ?",
        (user_id,)
    )
    user = cursor.fetchone()

    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid session.")

    return {
        "id": user[0],
        "username": user[1],
        "email": user[2]
    }

# Optional profile data personalizes guidance without blocking general access.
@app.get("/profile")
def get_user_profile(request: Request):
    user = get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            display_name,
            career_stage,
            career_interests,
            preferred_industries,
            skills,
            experience_level,
            preferred_location,
            schedule_preference,
            work_preference,
            desired_pay,
            maximum_commute_distance,
            maximum_commute_time,
            pay_period,
            minimum_base_pay,
            career_goals,
            created_at,
            updated_at
        FROM user_profiles
        WHERE user_id = ?
        """,
        (user["id"],)
    )

    profile = cursor.fetchone()
    conn.close()

    if not profile:
        return {
            "user": user,
            "profile": {
                "display_name": "",
                "career_stage": "",
                "career_interests": "",
                "preferred_industries": "",
                "skills": "",
                "experience_level": "",
                "preferred_location": "",
                "schedule_preference": "",
                "work_preference": "",
                "desired_pay": "",
                "maximum_commute_distance": None,
                "maximum_commute_time": None,
                "pay_period": "",
                "minimum_base_pay": None,
                "career_goals": ""
            }
        }

    return {
        "user": user,
        "profile": dict(profile)
    }

@app.put("/profile")
def update_user_profile(
    profile: UserProfileUpdate,
    request: Request
):
    user = get_authenticated_user(request)

    career_stage = (profile.career_stage or "").strip().lower()
    allowed_career_stages = {
        "", "first_time", "student", "recent_graduate",
        "career_changer", "returning_worker", "experienced"
    }
    if career_stage not in allowed_career_stages:
        raise HTTPException(status_code=400, detail="Select a valid career stage.")

    if (
        profile.maximum_commute_distance is not None
        and not 0 <= profile.maximum_commute_distance <= 500
    ):
        raise HTTPException(
            status_code=400,
            detail="Maximum commute distance must be between 0 and 500 miles."
        )

    if (
        profile.maximum_commute_time is not None
        and not 0 <= profile.maximum_commute_time <= 600
    ):
        raise HTTPException(
            status_code=400,
            detail="Maximum commute time must be between 0 and 600 minutes."
        )

    allowed_pay_periods = {"", "hour", "week", "month", "year"}
    pay_period = (profile.pay_period or "").strip().lower()

    if pay_period not in allowed_pay_periods:
        raise HTTPException(
            status_code=400,
            detail="Select a valid pay period."
        )

    if (
        profile.minimum_base_pay is not None
        and not 0 <= profile.minimum_base_pay <= 10000000
    ):
        raise HTTPException(
            status_code=400,
            detail="Minimum base pay must be between 0 and 10,000,000."
        )

    conn = get_connection(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO user_profiles (
            user_id,
            display_name,
            career_stage,
            career_interests,
            preferred_industries,
            skills,
            experience_level,
            preferred_location,
            schedule_preference,
            work_preference,
            desired_pay,
            maximum_commute_distance,
            maximum_commute_time,
            pay_period,
            minimum_base_pay,
            career_goals
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(user_id) DO UPDATE SET
            display_name = excluded.display_name,
            career_stage = excluded.career_stage,
            career_interests = excluded.career_interests,
            preferred_industries = excluded.preferred_industries,
            skills = excluded.skills,
            experience_level = excluded.experience_level,
            preferred_location = excluded.preferred_location,
            schedule_preference = excluded.schedule_preference,
            work_preference = excluded.work_preference,
            desired_pay = excluded.desired_pay,
            maximum_commute_distance = excluded.maximum_commute_distance,
            maximum_commute_time = excluded.maximum_commute_time,
            pay_period = excluded.pay_period,
            minimum_base_pay = excluded.minimum_base_pay,
            career_goals = excluded.career_goals,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user["id"],
            profile.display_name,
            career_stage,
            profile.career_interests,
            profile.preferred_industries,
            profile.skills,
            profile.experience_level,
            profile.preferred_location,
            profile.schedule_preference,
            profile.work_preference,
            profile.desired_pay,
            profile.maximum_commute_distance,
            profile.maximum_commute_time,
            pay_period,
            profile.minimum_base_pay,
            profile.career_goals
        )
    )

    conn.commit()
    conn.close()

    return {
        "message": "Profile saved successfully."
    }

@app.post("/employer-access/redeem")
def redeem_employer_access_code(
    redemption: EmployerCodeRedemption,
    request: Request
):
    user = get_authenticated_user(request)
    submitted_code = redemption.code.strip()

    if not submitted_code:
        raise HTTPException(
            status_code=400,
            detail="Enter an employer access code."
        )

    if user["role"] == "employer":
        return {
            "message": "Your account already has employer access.",
            "role": "employer"
        }

    code_hash = hash_access_code(submitted_code)
    current_time = datetime.now(timezone.utc)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()

        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT
                id,
                is_used,
                expires_at,
                company_name
            FROM employer_access_codes
            WHERE code_hash = ?
            """,
            (code_hash,)
        )

        access_code = cursor.fetchone()

        if not access_code:
            conn.rollback()

            raise HTTPException(
                status_code=400,
                detail="That employer access code is invalid."
            )

        if access_code["is_used"]:
            conn.rollback()

            raise HTTPException(
                status_code=400,
                detail="That employer access code has already been redeemed."
            )

        if access_code["expires_at"]:
            try:
                expiration = datetime.fromisoformat(
                    access_code["expires_at"].replace(
                        "Z",
                        "+00:00"
                    )
                )

                if expiration.tzinfo is None:
                    expiration = expiration.replace(
                        tzinfo=timezone.utc
                    )

            except ValueError:
                conn.rollback()

                raise HTTPException(
                    status_code=500,
                    detail="The access code has an invalid expiration date."
                )

            if expiration <= current_time:
                conn.rollback()

                raise HTTPException(
                    status_code=400,
                    detail="That employer access code has expired."
                )

        cursor.execute(
            """
            UPDATE users
            SET role = 'employer'
            WHERE id = ?
            """,
            (user["id"],)
        )

        cursor.execute(
            """
            UPDATE employer_access_codes
            SET
                is_used = 1,
                redeemed_by_user_id = ?,
                redeemed_at = ?
            WHERE id = ?
              AND is_used = 0
            """,
            (
                user["id"],
                current_time.isoformat(),
                access_code["id"]
            )
        )

        if cursor.rowcount != 1:
            conn.rollback()

            raise HTTPException(
                status_code=409,
                detail="That access code was just redeemed by another account."
            )

        conn.commit()

    except HTTPException:
        raise

    except sqlite3.Error:
        conn.rollback()

        raise HTTPException(
            status_code=500,
            detail="The employer access request could not be completed."
        )

    finally:
        conn.close()

    return {
        "message": "Employer access approved successfully.",
        "role": "employer",
        "company_name": access_code["company_name"]
    }


# Learning content is public in the frontend; these endpoints persist progress
# only for authenticated accounts.
def get_learning_progress(request: Request):
    user = get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            lesson_id,
            is_completed,
            last_opened_at,
            completed_at,
            created_at,
            updated_at
        FROM learning_progress
        WHERE user_id = ?
        ORDER BY updated_at DESC, lesson_id ASC
        """,
        (user["id"],)
    )

    rows = cursor.fetchall()
    conn.close()

    progress = []

    for row in rows:
        item = dict(row)
        item["is_completed"] = bool(
            item["is_completed"]
        )
        progress.append(item)

    return {
        "progress": progress,
        "summary": {
            "available_lessons": len(
                LEARNING_LESSON_IDS
            ),
            "started_lessons": len(progress),
            "completed_lessons": sum(
                1
                for item in progress
                if item["is_completed"]
            )
        }
    }


def update_learning_progress(
    lesson_id: str,
    progress_update: LearningProgressUpdate,
    request: Request
):
    user = get_authenticated_user(request)

    if lesson_id not in LEARNING_LESSON_IDS:
        raise HTTPException(
            status_code=404,
            detail="Learning lesson not found."
        )

    status = progress_update.status.strip().lower()

    if status not in LEARNING_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Learning progress status must be "
                "started, completed, or not_completed."
            )
        )

    timestamp = datetime.now(
        timezone.utc
    ).isoformat()

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if status == "started":
        cursor.execute(
            """
            INSERT INTO learning_progress (
                user_id,
                lesson_id,
                is_completed,
                last_opened_at,
                updated_at
            )
            VALUES (?, ?, 0, ?, ?)

            ON CONFLICT (user_id, lesson_id)
            DO UPDATE SET
                last_opened_at = excluded.last_opened_at,
                updated_at = excluded.updated_at
            """,
            (
                user["id"],
                lesson_id,
                timestamp,
                timestamp
            )
        )

    elif status == "completed":
        cursor.execute(
            """
            INSERT INTO learning_progress (
                user_id,
                lesson_id,
                is_completed,
                last_opened_at,
                completed_at,
                updated_at
            )
            VALUES (?, ?, 1, ?, ?, ?)

            ON CONFLICT (user_id, lesson_id)
            DO UPDATE SET
                is_completed = 1,
                last_opened_at = excluded.last_opened_at,
                completed_at = excluded.completed_at,
                updated_at = excluded.updated_at
            """,
            (
                user["id"],
                lesson_id,
                timestamp,
                timestamp,
                timestamp
            )
        )

    else:
        cursor.execute(
            """
            INSERT INTO learning_progress (
                user_id,
                lesson_id,
                is_completed,
                last_opened_at,
                completed_at,
                updated_at
            )
            VALUES (?, ?, 0, ?, NULL, ?)

            ON CONFLICT (user_id, lesson_id)
            DO UPDATE SET
                is_completed = 0,
                last_opened_at = excluded.last_opened_at,
                completed_at = NULL,
                updated_at = excluded.updated_at
            """,
            (
                user["id"],
                lesson_id,
                timestamp,
                timestamp
            )
        )

    conn.commit()

    cursor.execute(
        """
        SELECT
            lesson_id,
            is_completed,
            last_opened_at,
            completed_at,
            created_at,
            updated_at
        FROM learning_progress
        WHERE user_id = ?
          AND lesson_id = ?
        """,
        (
            user["id"],
            lesson_id
        )
    )

    saved_progress = dict(cursor.fetchone())
    conn.close()

    saved_progress["is_completed"] = bool(
        saved_progress["is_completed"]
    )

    return {
        "message": "Learning progress saved.",
        "progress": saved_progress
    }



@app.get("/dashboard-summary")
def get_dashboard_summary(request: Request):
    user = get_authenticated_user(request)

    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM saved_searches WHERE user_id = ?",
        (user["id"],)
    )
    for saved_search in cursor.fetchall():
        evaluate_saved_search(cursor, saved_search)

    conn.commit()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM saved_jobs
        WHERE user_id = ?
        """,
        (user["id"],)
    )

    saved_jobs_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE user_id = ?
          AND status NOT IN (
              'Accepted',
              'Rejected',
              'Withdrawn'
          )
        """,
        (user["id"],)
    )

    applications_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE user_id = ?
          AND status = 'Interview Scheduled'
          AND interview_date IS NOT NULL
          AND interview_date != ''
        """,
        (user["id"],)
    )

    interviews_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE user_id = ?
          AND follow_up_date IS NOT NULL
          AND follow_up_date != ''
          AND substr(follow_up_date, 1, 10) <= date('now')
          AND status NOT IN (
              'Accepted',
              'Rejected',
              'Withdrawn'
          )
        """,
        (user["id"],)
    )

    follow_ups_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM saved_search_matches
        JOIN saved_searches
            ON saved_searches.id = saved_search_matches.saved_search_id
        WHERE saved_searches.user_id = ?
          AND saved_search_matches.seen_at IS NULL
        """,
        (user["id"],)
    )

    job_alerts_count = cursor.fetchone()[0]

    conn.close()

    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"]
        },
        "summary": {
            "saved_jobs": saved_jobs_count,
            "applications": applications_count,
            "interviews": interviews_count,
            "follow_ups": follow_ups_count,
            "job_alerts": job_alerts_count
        }
    }


def format_action_date(value):
    if not value:
        return ""

    raw_value = str(value)[:10]
    try:
        parsed_date = datetime.strptime(raw_value, "%Y-%m-%d")
        return parsed_date.strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return raw_value


@app.get("/next-best-actions")
def get_next_best_actions(request: Request):
    user = get_authenticated_user(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    actions = []
    covered_application_ids = set()

    evaluate_user_saved_searches(cursor, user["id"])
    conn.commit()

    cursor.execute(
        """
        SELECT
            applications.id AS application_id,
            applications.follow_up_date,
            jobs.title,
            jobs.company
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND applications.follow_up_date IS NOT NULL
          AND applications.follow_up_date != ''
          AND date(applications.follow_up_date) <= date('now')
          AND applications.status NOT IN (
              'Accepted', 'Rejected', 'Withdrawn'
          )
        ORDER BY date(applications.follow_up_date) ASC
        LIMIT 3
        """,
        (user["id"],)
    )
    for row in cursor.fetchall():
        actions.append({
            "id": f"follow-up-{row['application_id']}",
            "type": "follow_up",
            "urgency": "urgent",
            "priority": 10,
            "title": f"Follow up with {row['company']}",
            "reason": (
                f"Your follow-up for {row['title']} was due "
                f"{format_action_date(row['follow_up_date'])}."
            ),
            "action_label": "Open Application",
            "href": "applications.html",
            "due_date": str(row["follow_up_date"])[:10]
        })
        covered_application_ids.add(row["application_id"])

    cursor.execute(
        """
        SELECT
            applications.id AS application_id,
            applications.interview_date,
            applications.interview_time,
            applications.interview_format,
            jobs.title,
            jobs.company
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND applications.status = 'Interview Scheduled'
          AND applications.interview_date IS NOT NULL
          AND applications.interview_date != ''
          AND date(applications.interview_date) >= date('now')
        ORDER BY date(applications.interview_date) ASC,
                 applications.interview_time ASC
        LIMIT 3
        """,
        (user["id"],)
    )
    for row in cursor.fetchall():
        interview_details = [
            format_action_date(row["interview_date"])
        ]
        if row["interview_time"]:
            interview_details.append(str(row["interview_time"]))
        if row["interview_format"]:
            interview_details.append(str(row["interview_format"]))
        actions.append({
            "id": f"interview-{row['application_id']}",
            "type": "interview",
            "urgency": "important",
            "priority": 20,
            "title": f"Prepare for your {row['company']} interview",
            "reason": (
                f"Your interview for {row['title']} is scheduled for "
                f"{' at '.join(interview_details)}."
            ),
            "action_label": "Practice Interviewing",
            "href": "learning-center.html#mockInterviewPanel",
            "due_date": str(row["interview_date"])[:10]
        })
        covered_application_ids.add(row["application_id"])

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM saved_search_matches
        JOIN saved_searches
            ON saved_searches.id = saved_search_matches.saved_search_id
        WHERE saved_searches.user_id = ?
          AND saved_search_matches.seen_at IS NULL
        """,
        (user["id"],)
    )
    unread_alerts = cursor.fetchone()[0]
    if unread_alerts:
        actions.append({
            "id": "new-job-alerts",
            "type": "job_alert",
            "urgency": "important",
            "priority": 25,
            "title": (
                f"Review {unread_alerts} new job "
                f"alert{'s' if unread_alerts != 1 else ''}"
            ),
            "reason": (
                "Newly added jobs match criteria from your saved searches."
            ),
            "action_label": "View Job Alerts",
            "href": "alerts.html",
            "due_date": ""
        })

    cursor.execute(
        """
        SELECT DISTINCT
            jobs.id AS job_id,
            jobs.title,
            jobs.company,
            COALESCE(jobs.application_deadline, jobs.expires_at) AS deadline
        FROM jobs
        LEFT JOIN saved_jobs
            ON saved_jobs.job_id = jobs.id
           AND saved_jobs.user_id = ?
        LEFT JOIN applications
            ON applications.job_id = jobs.id
           AND applications.user_id = ?
        WHERE COALESCE(jobs.application_deadline, jobs.expires_at) IS NOT NULL
          AND date(COALESCE(jobs.application_deadline, jobs.expires_at))
              BETWEEN date('now') AND date('now', '+7 day')
          AND (
              saved_jobs.id IS NOT NULL
              OR applications.status = 'Interested'
          )
        ORDER BY date(deadline) ASC
        LIMIT 3
        """,
        (user["id"], user["id"])
    )
    for row in cursor.fetchall():
        actions.append({
            "id": f"deadline-{row['job_id']}",
            "type": "deadline",
            "urgency": "important",
            "priority": 30,
            "title": f"Review the deadline for {row['title']}",
            "reason": (
                f"{row['company']} lists a deadline of "
                f"{format_action_date(row['deadline'])}. Confirm the "
                "official listing before applying."
            ),
            "action_label": "View Job",
            "href": f"jobs.html?job={row['job_id']}",
            "due_date": str(row["deadline"])[:10]
        })

    cursor.execute(
        """
        SELECT
            applications.id AS application_id,
            jobs.title,
            jobs.company,
            applications.created_at
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND applications.status = 'Interested'
          AND (
              applications.applied_at IS NULL
              OR applications.applied_at = ''
          )
          AND NOT (
              COALESCE(jobs.application_deadline, jobs.expires_at) IS NOT NULL
              AND date(COALESCE(jobs.application_deadline, jobs.expires_at))
                  BETWEEN date('now') AND date('now', '+7 day')
          )
        ORDER BY applications.updated_at ASC
        LIMIT 3
        """,
        (user["id"],)
    )
    for row in cursor.fetchall():
        if row["application_id"] in covered_application_ids:
            continue
        actions.append({
            "id": f"unfinished-{row['application_id']}",
            "type": "application",
            "urgency": "standard",
            "priority": 40,
            "title": f"Continue your {row['company']} application",
            "reason": (
                f"{row['title']} is still marked Interested and does not "
                "have an application date."
            ),
            "action_label": "Open Application Tracker",
            "href": "applications.html",
            "due_date": ""
        })
        covered_application_ids.add(row["application_id"])

    cursor.execute(
        """
        SELECT
            applications.id AS application_id,
            applications.status,
            jobs.title,
            jobs.company,
            application_history.created_at
        FROM application_history
        JOIN applications
            ON applications.id = application_history.application_id
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
          AND application_history.changed_by_type = 'employer'
          AND application_history.created_at >= datetime('now', '-7 day')
          AND application_history.id = (
              SELECT MAX(history.id)
              FROM application_history AS history
              WHERE history.application_id = applications.id
                AND history.changed_by_type = 'employer'
          )
        ORDER BY application_history.created_at DESC
        LIMIT 2
        """,
        (user["id"],)
    )
    for row in cursor.fetchall():
        if row["application_id"] in covered_application_ids:
            continue
        is_decision_update = row["status"] in {
            "Offer Extended", "Accepted", "Rejected"
        }
        actions.append({
            "id": f"employer-update-{row['application_id']}",
            "type": "status_update",
            "urgency": "important" if is_decision_update else "standard",
            "priority": 15 if is_decision_update else 45,
            "title": f"Review the update from {row['company']}",
            "reason": (
                f"Your {row['title']} application is now marked "
                f"{row['status']}."
            ),
            "action_label": "Review Application",
            "href": "applications.html",
            "due_date": ""
        })

    actions.sort(
        key=lambda action: (
            action["priority"],
            action["due_date"] or "9999-12-31",
            action["id"]
        )
    )
    actions = actions[:6]

    if not actions:
        actions.append({
            "id": "explore-jobs",
            "type": "explore",
            "urgency": "standard",
            "priority": 100,
            "title": "Explore current job opportunities",
            "reason": (
                "You have no overdue follow-ups, upcoming interviews, "
                "unfinished applications, or unread job alerts right now."
            ),
            "action_label": "Find Jobs",
            "href": "jobs.html",
            "due_date": ""
        })

    conn.close()
    return {
        "actions": actions,
        "explanation": (
            "Actions are ordered using dates and activity already saved in "
            "PathForge. They are organizational suggestions, not hiring "
            "predictions."
        )
    }


@app.get("/connected-guidance")
def get_connected_guidance(request: Request):
    user = get_authenticated_user(request)
    if user["role"] != "job_seeker":
        raise HTTPException(
            status_code=403,
            detail="Connected guidance is available to job seekers."
        )
    action_data = get_next_best_actions(request)
    conn = get_connection(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    profile = cursor.execute(
        """
        SELECT career_stage, career_interests, preferred_industries, skills,
               experience_level, preferred_location,
               schedule_preference, work_preference,
               minimum_base_pay, maximum_commute_distance
        FROM user_profiles WHERE user_id = ?
        """,
        (user["id"],)
    ).fetchone()
    saved_jobs = cursor.execute(
        """
        SELECT jobs.id, jobs.title, jobs.company
        FROM saved_jobs JOIN jobs ON jobs.id = saved_jobs.job_id
        WHERE saved_jobs.user_id = ?
        ORDER BY saved_jobs.saved_at DESC LIMIT 3
        """,
        (user["id"],)
    ).fetchall()
    application_rows = cursor.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM applications WHERE user_id = ? GROUP BY status
        """,
        (user["id"],)
    ).fetchall()
    conn.close()
    profile_fields = dict(profile) if profile else {}
    completed_fields = [key for key, value in profile_fields.items() if value not in (None, "")]
    applications = {row["status"]: row["total"] for row in application_rows}
    career_stage = profile_fields.get("career_stage") or ""
    stage_guidance = {
        "first_time": "Use genuine examples from school, volunteering, caregiving, projects, clubs, or community activities when paid experience is limited.",
        "student": "Connect coursework, projects, campus activities, and schedule needs to the role without presenting them as employment.",
        "recent_graduate": "Connect recent education, internships, projects, and transferable skills to the employer’s stated needs.",
        "career_changer": "Translate relevant responsibilities from prior work and clearly separate transferable skills from experience you have not gained yet.",
        "returning_worker": "Focus on current capabilities, refreshed skills, and genuine experience while addressing a work gap only when useful.",
        "experienced": "Prioritize recent, relevant accomplishments, scope, leadership, and measurable outcomes without overstating results."
    }.get(career_stage, "Choose an optional career stage in your profile to adapt examples and guidance.")
    evidence = [
        {
            "label": "Profile preferences",
            "summary": f"{len(completed_fields)} relevant preference fields saved",
            "href": "profile.html"
        },
        {
            "label": "Saved jobs",
            "summary": f"{len(saved_jobs)} recent saved jobs available for context",
            "href": "saved-jobs.html"
        },
        {
            "label": "Application tracker",
            "summary": f"{sum(applications.values())} tracked applications",
            "href": "applications.html"
        }
    ]
    return {
        "primary_action": action_data["actions"][0],
        "actions": action_data["actions"],
        "evidence": evidence,
        "recent_saved_jobs": [dict(job) for job in saved_jobs],
        "application_statuses": applications,
        "career_stage": career_stage,
        "career_stage_guidance": stage_guidance,
        "explanation": (
            "These suggestions use only information saved in your PathForge "
            "account. Resume reviews and mock-interview answers are not stored, "
            "so they are not silently used as account history. Suggestions are "
            "organizational guidance, not hiring predictions."
        )
    }


LEARNING_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".rtf",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".xml"
}

LEARNING_DOCUMENT_MAX_BYTES = 5 * 1024 * 1024
LEARNING_DOCUMENT_MAX_TEXT = 20000


# Uploaded career documents are normalized and size-limited before any
# assistant or résumé evaluation logic examines them.
def normalize_learning_document_text(text: str):
    cleaned_text = text.replace("\x00", " ")
    cleaned_text = re.sub(r"\r\n?", "\n", cleaned_text)
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()[:LEARNING_DOCUMENT_MAX_TEXT]


def extract_docx_text(content: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            document_info = document.getinfo(
                "word/document.xml"
            )

            if document_info.file_size > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="The Word document expands beyond the supported size."
                )

            document_xml = document.read(
                "word/document.xml"
            )
    except (KeyError, zipfile.BadZipFile):
        raise HTTPException(
            status_code=400,
            detail="PathForge could not read that Word document."
        )

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        raise HTTPException(
            status_code=400,
            detail="PathForge could not read that Word document."
        )

    paragraphs = []
    namespace = (
        "{http://schemas.openxmlformats.org/"
        "wordprocessingml/2006/main}"
    )

    for paragraph in root.iter(namespace + "p"):
        paragraph_text = "".join(
            node.text or ""
            for node in paragraph.iter(namespace + "t")
        ).strip()

        if paragraph_text:
            paragraphs.append(paragraph_text)

    return "\n".join(paragraphs)


def extract_pdf_text(content: bytes):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail=(
                "PDF reading is not available in this server environment. "
                "Save the document as .docx, .rtf, or .txt and try again."
            )
        )

    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages[:50]
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=(
                "PathForge could not read that PDF. Scanned or "
                "password-protected PDFs may not contain extractable text."
            )
        )

    return text


def extract_learning_document_text(
    filename: str,
    content: bytes
):
    extension = os.path.splitext(filename.lower())[1]

    if extension not in LEARNING_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Supported files are PDF, DOCX, RTF, TXT, Markdown, "
                "CSV, JSON, HTML, and XML."
            )
        )

    if extension == ".pdf":
        text = extract_pdf_text(content)
    elif extension == ".docx":
        text = extract_docx_text(content)
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("cp1252")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="PathForge could not decode that document."
                )

        if extension == ".rtf":
            text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
            text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
            text = text.replace("{", " ").replace("}", " ")
        elif extension in {".html", ".htm", ".xml"}:
            text = re.sub(
                r"<(script|style)\b[^>]*>.*?</\1>",
                " ",
                text,
                flags=re.IGNORECASE | re.DOTALL
            )
            text = unescape(re.sub(r"<[^>]+>", " ", text))

    cleaned_text = normalize_learning_document_text(text)

    if not cleaned_text:
        raise HTTPException(
            status_code=400,
            detail=(
                "No readable text was found in that document. "
                "Scanned documents may need text recognition first."
            )
        )

    return cleaned_text


@app.post("/learning-assistant/extract-document")
def extract_learning_assistant_document(
    data: LearningAssistantDocument,
    request: Request
):
    get_authenticated_user(request)

    filename = os.path.basename(data.filename.strip())

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Choose a document to attach."
        )

    try:
        content = base64.b64decode(
            data.content_base64,
            validate=True
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="The document data is invalid."
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The selected document is empty."
        )

    if len(content) > LEARNING_DOCUMENT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Choose a document no larger than 5 MB."
        )

    extracted_text = extract_learning_document_text(
        filename,
        content
    )

    return {
        "filename": filename,
        "text": extracted_text,
        "characters": len(extracted_text)
    }


AI_CRISIS_PATTERNS = [
    r"\bsuicid(?:e|al)\b", r"\bkill myself\b", r"\bend my life\b",
    r"\bhurt myself\b", r"\bself[ -]?harm\b", r"\bdon't want to live\b",
    r"\bdo not want to live\b", r"\bwish i (?:was|were) dead\b"
]

AI_MENTAL_HEALTH_TERMS = {
    "depressed", "depression", "anxiety", "anxious", "panic attack",
    "mental health", "hopeless", "worthless", "lonely", "therapy",
    "therapist", "need to vent", "venting", "emotionally overwhelmed"
}

AI_CAREER_TERMS = {
    "job", "jobs", "career", "work", "workplace", "employer", "employee",
    "resume", "résumé", "cv", "cover letter", "application", "apply",
    "interview", "interviewer", "recruiter", "hiring", "offer", "salary",
    "pay", "wage", "benefits", "schedule", "shift", "remote", "hybrid",
    "skill", "skills", "strength", "strengths", "accomplishment",
    "accomplishments", "qualification", "experience", "education", "training",
    "certificate", "certification", "portfolio", "networking", "reference",
    "promotion", "manager", "supervisor", "coworker", "colleague", "boss",
    "layoff", "laid off", "fired", "termination", "quit", "resign",
    "onboarding", "background check", "career gap", "employment gap",
    "follow up", "thank you note", "job scam", "ats", "accommodation",
    "internship", "apprenticeship", "volunteer", "professional", "occupation",
    "rejected", "rejection", "resignation", "notice period", "withdraw",
    "disability", "hr", "human resources", "reference check", "raise",
    "harassment", "discrimination", "terminated", "caregiving", "dress code"
}

AI_MEDICAL_REQUEST_PATTERNS = [
    r"\bdiagnos(?:e|is|ing)\b", r"\bwhat medication\b", r"\bprescri(?:be|ption)\b",
    r"\b(?:back|neck|chest) pain\b", r"\bworkplace injury\b", r"\binjured at work\b"
]

AI_EXPLICITLY_UNRELATED_PATTERNS = [
    r"\b(?:write|give me|create)\s+(?:a\s+)?recipe\b",
    r"\b(?:solve|do)\s+(?:this|my)?\s*(?:math|algebra|calculus)\b",
    r"\bcreate\s+(?:a\s+)?workout plan\b",
]


def assistant_contains_term(normalized: str, terms):
    """Match complete words or phrases so 'work' does not match 'homework'."""
    for term in terms:
        phrase_pattern = re.escape(term).replace(r"\ ", r"\s+")
        if re.search(rf"(?<!\w){phrase_pattern}(?!\w)", normalized):
            return True
    return False


def normalize_assistant_question(value: str):
    return re.sub(r"[\s?.!,;:]+$", "", value.strip().lower().replace("-", " "))


def assistant_safety_reply(normalized: str):
    if any(re.search(pattern, normalized) for pattern in AI_CRISIS_PATTERNS):
        return (
            "Immediate safety warning: PathForge is not a crisis service. If you may "
            "hurt yourself or are in immediate danger, call 911 or your local emergency "
            "number, or go to the nearest emergency room. In the United States or Canada, "
            "you can also call or text 988. Please contact someone you trust who can stay "
            "with you while you get help."
        )
    if assistant_contains_term(normalized, AI_MENTAL_HEALTH_TERMS):
        return (
            "I’m sorry this feels difficult. PathForge can help with practical career "
            "and job-search steps, but it is not a mental-health professional and cannot "
            "provide counseling or crisis care. Consider talking with someone you trust "
            "or a qualified mental-health professional. If you feel unsafe or begin "
            "thinking about self-harm, contact emergency services or call or text 988 in "
            "the United States or Canada. If the concern is job-related, tell me the "
            "specific work or job-search problem and I can help you make a practical plan."
        )
    return None


def assistant_safety_level(normalized: str):
    if any(re.search(pattern, normalized) for pattern in AI_CRISIS_PATTERNS):
        return "urgent"
    if assistant_contains_term(normalized, AI_MENTAL_HEALTH_TERMS):
        return "support"
    return None


def is_career_related_prompt(normalized: str):
    canonical = normalize_assistant_question(normalized)
    if canonical in {"hi", "hello", "hey", "help", "what can you do"}:
        return True
    return assistant_contains_term(canonical, AI_CAREER_TERMS)


PROJECT_ROOT = Path(__file__).resolve().parent
RESUME_PROMPT_VERSION = "evaluator_v1.txt"


@lru_cache(maxsize=8)
def load_resume_prompt(filename: str = RESUME_PROMPT_VERSION):
    safe_name = Path(filename).name
    prompt_path = PROJECT_ROOT / "prompts" / safe_name
    if not prompt_path.is_file():
        raise RuntimeError(f"Required resume evaluator prompt is missing: {safe_name}")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError(f"Resume evaluator prompt is empty: {safe_name}")
    return prompt


RESUME_EVALUATOR_SYSTEM_PROMPT = load_resume_prompt()

RESUME_CATEGORY_WEIGHTS = {
    "general": {
        "formatting": 0.15,
        "impact_metrics": 0.25,
        "skills": 0.20,
        "timeline_logic": 0.20,
        "grammar_tone": 0.20,
    },
    "tech_engineering": {
        "formatting": 0.12,
        "impact_metrics": 0.23,
        "skills": 0.30,
        "timeline_logic": 0.18,
        "grammar_tone": 0.17,
    },
    "sales_business": {
        "formatting": 0.12,
        "impact_metrics": 0.35,
        "skills": 0.18,
        "timeline_logic": 0.18,
        "grammar_tone": 0.17,
    },
    "healthcare_finance": {
        "formatting": 0.12,
        "impact_metrics": 0.18,
        "skills": 0.28,
        "timeline_logic": 0.25,
        "grammar_tone": 0.17,
    },
    "service_retail_operations": {
        "formatting": 0.15,
        "impact_metrics": 0.28,
        "skills": 0.20,
        "timeline_logic": 0.22,
        "grammar_tone": 0.15,
    },
}

RESUME_CAREER_STAGE_WEIGHT_MULTIPLIERS = {
    "student": {
        "formatting": 1.10,
        "impact_metrics": 0.68,
        "skills": 1.55,
        "timeline_logic": 0.55,
        "grammar_tone": 1.12,
    },
    "career_changer": {
        "formatting": 1.00,
        "impact_metrics": 0.90,
        "skills": 1.40,
        "timeline_logic": 0.65,
        "grammar_tone": 1.08,
    },
}


def apply_resume_career_stage_weights(base_weights, career_stage):
    multipliers = RESUME_CAREER_STAGE_WEIGHT_MULTIPLIERS.get(career_stage)
    if not multipliers:
        return dict(base_weights)
    adjusted = {
        category: weight * multipliers.get(category, 1.0)
        for category, weight in base_weights.items()
    }
    total = sum(adjusted.values()) or 1.0
    return {category: weight / total for category, weight in adjusted.items()}


def resume_weight_percentages(weights):
    exact = {category: weight * 100 for category, weight in weights.items()}
    whole = {category: int(value) for category, value in exact.items()}
    remaining = 100 - sum(whole.values())
    ranked = sorted(exact, key=lambda category: exact[category] - whole[category], reverse=True)
    for category in ranked[:remaining]:
        whole[category] += 1
    return whole

RESUME_INDUSTRY_EXPECTATIONS = {
    "tech_engineering": {
        "label": "Tech / Engineering",
        "keywords": [
            "python", "javascript", "typescript", "java", "c++", "sql",
            "aws", "azure", "gcp", "docker", "kubernetes", "git", "api",
            "react", "angular", "vue", "node", "testing", "ci/cd",
        ],
        "certifications": [],
        "evidence": ["github", "portfolio", "project", "framework"],
    },
    "sales_business": {
        "label": "Sales / Business",
        "keywords": [
            "sales", "revenue", "quota", "pipeline", "conversion", "crm",
            "salesforce", "forecast", "account", "client", "negotiation",
        ],
        "certifications": [],
        "evidence": ["quota", "revenue", "conversion", "retention"],
    },
    "healthcare_finance": {
        "label": "Healthcare / Finance",
        "keywords": [
            "patient", "clinical", "hipaa", "compliance", "audit", "risk",
            "financial", "accounting", "regulatory", "gaap", "analysis",
        ],
        "certifications": ["RN", "BLS", "CPA", "CFA"],
        "evidence": ["license", "certification", "compliance", "regulatory"],
    },
    "service_retail_operations": {
        "label": "Service / Retail / Operations",
        "keywords": [
            "customer", "cash handling", "pos", "inventory", "safety",
            "service", "shift", "orders", "operations", "reliability",
        ],
        "certifications": [],
        "evidence": ["customers", "transactions", "orders", "accuracy"],
    },
}

RESUME_AI_BUZZWORDS = {
    "spearheaded", "tapestry", "testament", "pivotal", "seamless",
    "burgeoning", "holistic", "driving force", "beacon", "foster",
    "paradigm",
}

RESUME_SKILL_TAXONOMY = {
    "point_of_sale": {"label": "POS operation", "aliases": ["pos", "point of sale", "register system", "cash register"], "category": "technical"},
    "cash_handling": {"label": "Cash handling", "aliases": ["cash handling", "balanced register", "counted drawer", "processed payments", "cash payments"], "category": "operational"},
    "inventory": {"label": "Inventory management", "aliases": ["inventory", "stocking", "restocking", "stock counts", "replenishment"], "category": "operational"},
    "customer_service": {"label": "Customer service", "aliases": ["customer service", "served customers", "guest service", "resolved customer"], "category": "service"},
    "food_safety": {"label": "Food safety", "aliases": ["food safety", "sanitation", "safe food handling", "temperature logs"], "category": "compliance"},
    "spreadsheets": {"label": "Spreadsheet tools", "aliases": ["microsoft excel", "excel", "google sheets", "spreadsheets"], "category": "technical"},
    "programming_python": {"label": "Python", "aliases": ["python", "django", "fastapi", "flask"], "category": "technical"},
    "web_javascript": {"label": "JavaScript / TypeScript", "aliases": ["javascript", "typescript", "react", "node.js", "nodejs"], "category": "technical"},
    "databases": {"label": "Databases / SQL", "aliases": ["sql", "postgresql", "mysql", "sqlite", "database"], "category": "technical"},
    "crm": {"label": "CRM systems", "aliases": ["crm", "salesforce", "hubspot"], "category": "technical"},
}


def parse_contextual_resume_skills(sections: Dict[str, str]):
    results = []
    searchable_sections = ("skills", "work_experience", "projects", "certifications")
    for skill_id, definition in RESUME_SKILL_TAXONOMY.items():
        evidence = []
        source_sections = []
        for section_name in searchable_sections:
            section_text = sections.get(section_name, "")
            matched_lines = [
                line for line in section_text.splitlines()
                if any(re.search(rf"\b{re.escape(alias)}\b", line, re.I) for alias in definition["aliases"])
            ]
            if matched_lines:
                evidence.extend(matched_lines)
                source_sections.append(section_name)
        if not evidence:
            continue
        confidence = 0.50
        if "skills" in source_sections:
            confidence += 0.10
        if "work_experience" in source_sections:
            confidence += 0.25
        if len(set(source_sections)) > 1:
            confidence += 0.10
        results.append({
            "skill_id": skill_id,
            "label": definition["label"],
            "category": definition["category"],
            "confidence": round(min(confidence, 1.0), 2),
            "evidence": list(dict.fromkeys(evidence))[:4],
            "source_sections": list(dict.fromkeys(source_sections)),
        })
    return sorted(results, key=lambda item: item["confidence"], reverse=True)


def _resume_lines(text: str):
    return [line.strip() for line in text.splitlines() if line.strip()]


def _resume_bullets(text: str):
    return [
        re.sub(r"^[•\-*▪◦]\s*", "", line).strip()
        for line in _resume_lines(text)
        if re.match(r"^[•\-*▪◦]\s*", line)
    ]


RESUME_SECTION_ALIASES = {
    "summary": {"summary", "objective", "professional summary", "professional profile"},
    "work_experience": {"experience", "work experience", "employment", "employment history", "work history", "professional experience"},
    "education": {"education", "academic background", "academic history"},
    "skills": {"skills", "technical skills", "core competencies", "competencies"},
    "projects": {"projects", "selected projects", "technical projects"},
    "certifications": {"certifications", "certification", "licenses", "licenses and certifications"},
}


def segment_resume_sections(text: str) -> Dict[str, str]:
    sections = {"header": []}
    current_section = "header"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
        detected = next(
            (name for name, aliases in RESUME_SECTION_ALIASES.items() if normalized in aliases),
            None,
        )
        if detected:
            current_section = detected
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _resume_section_text(text: str, names):
    sections = segment_resume_sections(text)
    requested = set(names)
    if requested.intersection({"experience", "employment", "work history"}):
        return sections.get("work_experience", "")
    if requested.intersection({"skills", "technical skills", "competencies"}):
        return sections.get("skills", "")
    return ""


def _detect_resume_industry(text: str, requested: Optional[str]):
    normalized_requested = re.sub(
        r"[^a-z]+", "_", (requested or "").strip().lower()
    ).strip("_")
    aliases = {
        "tech": "tech_engineering", "engineering": "tech_engineering",
        "technology": "tech_engineering", "sales": "sales_business",
        "business": "sales_business", "healthcare": "healthcare_finance",
        "finance": "healthcare_finance", "retail": "service_retail_operations",
        "service": "service_retail_operations",
        "operations": "service_retail_operations",
    }
    if normalized_requested in RESUME_INDUSTRY_EXPECTATIONS:
        return normalized_requested
    if normalized_requested in aliases:
        return aliases[normalized_requested]

    lowered = text.lower()
    scores = {}
    for industry, expectations in RESUME_INDUSTRY_EXPECTATIONS.items():
        terms = expectations["keywords"] + [
            item.lower() for item in expectations["certifications"]
        ]
        scores[industry] = sum(
            1 for term in terms
            if re.search(rf"\b{re.escape(term)}\b", lowered)
        )
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "general"


def _compressed_resume_score(raw_score: float, extraordinary: bool = False):
    compressed = 50 + ((raw_score - 50) * 0.58)
    upper_bound = 92 if extraordinary else 84
    return max(1, min(upper_bound, round(compressed)))


def _month_number(value: str):
    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
        "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8,
        "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    return months.get(value.lower()[:3], 1)


def _resume_date_ranges(text: str):
    date_token = (
        r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+)?(?:19|20)\d{2}"
    )
    ranges = []
    for line in _resume_lines(text):
        match = re.search(
            rf"(?P<start>{date_token})\s*(?:-|–|—|to)\s*"
            rf"(?P<end>{date_token}|present|current|now)",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        def parse_token(token, end=False):
            if token.lower() in {"present", "current", "now"}:
                return date.today().year * 12 + date.today().month
            year_match = re.search(r"(?:19|20)\d{2}", token)
            year = int(year_match.group())
            month_match = re.match(r"[A-Za-z]+", token)
            month = _month_number(month_match.group()) if month_match else (12 if end else 1)
            return year * 12 + month

        start = parse_token(match.group("start"))
        end = parse_token(match.group("end"), end=True)
        ranges.append({"start": start, "end": end, "line": line})
    return ranges


def _timeline_review(work_text: str, summary_text: str = ""):
    ranges = _resume_date_ranges(work_text)
    flags = []
    invalid = [item for item in ranges if item["end"] < item["start"]]
    for item in invalid:
        flags.append({
            "type": "timeline_contradiction",
            "severity": "high",
            "message": f"The date range appears reversed: {item['line']}",
        })
    valid = sorted(
        [item for item in ranges if item["end"] >= item["start"]],
        key=lambda item: item["start"],
    )
    for previous, current in zip(valid, valid[1:]):
        gap = current["start"] - previous["end"] - 1
        overlap = previous["end"] - current["start"] + 1
        if gap > 6:
            flags.append({
                "type": "employment_gap",
                "severity": "review",
                "message": f"A gap of about {gap} months appears between two dated entries. It may be valid, but consider explaining it if relevant.",
            })
        if overlap > 6 and "part-time" not in (previous["line"] + current["line"]).lower():
            flags.append({
                "type": "overlapping_roles",
                "severity": "review",
                "message": f"Two roles appear to overlap by about {overlap} months. Clarify concurrent or part-time work where applicable.",
            })

    merged = []
    for item in valid:
        if not merged or item["start"] > merged[-1][1] + 1:
            merged.append([item["start"], item["end"]])
        else:
            merged[-1][1] = max(merged[-1][1], item["end"])
    documented_months = sum(end - start + 1 for start, end in merged)
    claim = re.search(
        r"\b(\d{1,2})\+?\s+years?(?:\s+of)?(?:\s+[a-z][a-z-]*){0,4}\s+experience\b",
        summary_text,
        re.I,
    )
    if claim and documented_months and int(claim.group(1)) * 12 > documented_months + 1:
        claimed_years = int(claim.group(1))
        flags.append({
            "type": "experience_claim_mismatch",
            "severity": "high",
            "message": f"The resume claims {claimed_years} year{'s' if claimed_years != 1 else ''} of experience, but the detected dated entries show about {documented_months} months. Confirm that all relevant roles and dates were extracted.",
        })
    return ranges, flags


def _ai_writing_risk(text: str, bullets):
    lowered = text.lower()
    phrases = sorted(
        phrase for phrase in RESUME_AI_BUZZWORDS
        if re.search(rf"\b{re.escape(phrase)}\b", lowered)
    )
    lengths = [len(re.findall(r"\b\w+\b", bullet)) for bullet in bullets]
    uniform = False
    if len(lengths) >= 5 and sum(lengths) / len(lengths):
        average = sum(lengths) / len(lengths)
        variance = sum((length - average) ** 2 for length in lengths) / len(lengths)
        uniform = (variance ** 0.5) / average < 0.12
    vague = [
        bullet for bullet in bullets
        if re.search(r"\b(?:leveraged|optimized|enhanced|transformed|drove|fostered)\b", bullet, re.I)
        and not re.search(r"\d|\b(?:using|with|through|via)\b", bullet, re.I)
    ]
    points = min(4, len(phrases)) + (2 if uniform else 0) + min(3, len(vague))
    level = "High" if points >= 6 else "Medium" if points >= 3 else "Low"
    indicators = []
    if phrases:
        indicators.append("Overused phrases detected: " + ", ".join(phrases))
    if uniform:
        indicators.append("Five or more bullets have unusually uniform lengths")
    if vague:
        indicators.append(f"{len(vague)} polished but nonspecific bullet(s) lack a named method, tool, or measurable context")
    return {
        "flagged": level in {"Medium", "High"},
        "risk_level": level,
        "flagged_phrases": phrases,
        "indicators": indicators,
        "disclaimer": "This is a writing-pattern risk signal, not proof that AI created the resume.",
    }


def _detect_resume_career_stage(text: str, requested: Optional[str]):
    normalized = (requested or "").strip().lower().replace("-", "_")
    if normalized in {"student", "high_school"}:
        return "student"
    if normalized == "career_changer":
        return "career_changer"
    if normalized == "entry_level":
        return "entry_level"
    if normalized in {"mid_level", "mid"}:
        return "mid_level"
    if normalized in {"executive", "senior_executive"}:
        return "executive"
    lowered = text.lower()
    if re.search(r"\b(high school|student|gpa|expected graduation|first job)\b", lowered):
        return "entry_level"
    if re.search(r"\b(chief|c-suite|vice president|vp|executive director)\b", lowered):
        return "executive"
    return "mid_level"


def build_resume_score_breakdown(
    career_stage: str,
    word_count: int,
    documented_employment_months: int,
    employment_ranges: list,
    metric_count: int,
    bullet_count: int,
    weak_bullets: list,
    concrete_skills: list,
    timeline_flags: list,
    action_ratio: float,
    has_email: bool,
    has_phone: bool,
    academic_evidence_count: int = 0,
):
    stage_labels = {
        "student": "Student",
        "entry_level": "Entry-Level / Early Career",
        "career_changer": "Career Changer",
        "mid_level": "Mid-Level",
        "executive": "Executive / Senior Leadership",
    }
    stage_label = stage_labels.get(career_stage, "Mid-Level")
    summary_header = f"{stage_label.upper()} review"
    expected_minimum = {
        "student": 100,
        "entry_level": 100,
        "career_changer": 250,
        "mid_level": 300,
        "executive": 500,
    }.get(career_stage, 300)

    if word_count < expected_minimum:
        length_context = (
            f"At {word_count} words, the resume is shorter than the typical "
            f"starting range for a {stage_label.lower()} resume, so there is "
            "less evidence available to demonstrate skills and impact."
        )
    elif career_stage in {"student", "entry_level"} and word_count <= 250:
        length_context = (
            f"At {word_count} words, the resume is appropriately concise for "
            "an early-career candidate and was not marked down simply for being short."
        )
    else:
        length_context = (
            f"The {word_count}-word length provides a reasonable amount of content "
            f"for the detected {stage_label.lower()} stage."
        )

    if employment_ranges:
        history_context = (
            f" The documented work history covers approximately "
            f"{documented_employment_months} month"
            f"{'s' if documented_employment_months != 1 else ''}. Its length is "
            "considered in context, while the detail inside each responsibility "
            "still determines how much evidence the resume provides."
        )
    else:
        history_context = (
            " No complete employment date range was available, so the evaluator "
            "could not confirm the length of the work history."
        )

    lowering = []
    priority_actions = []
    if employment_ranges and documented_employment_months < 12 and career_stage != "student":
        lowering.append(
            f"Brief documented work history ({documented_employment_months} months) provides fewer examples of workplace impact."
        )
        priority_actions.append(
            "Expand one or two existing responsibilities with the specific work performed, tools used, or workload handled; do not add unverified experience."
        )
    elif not employment_ranges:
        lowering.append("Work-history duration could not be confirmed from complete dates.")
        priority_actions.append(
            "Add consistent Month Year dates to each work entry so employers can understand the timeline."
        )
    if metric_count == 0:
        lowering.append("Responsibilities do not yet include verified workload, frequency, or outcome details.")
        priority_actions.append(
            "Review the experience bullets and add one truthful workload, frequency, accuracy, or outcome detail where you can verify it."
        )
    if weak_bullets:
        lowering.append("Some experience statements are broad and need more specific actions or context.")
        priority_actions.append(
            "Rewrite the weakest experience bullet with a strong action verb and the specific task performed, then add a verified tool or result if available."
        )
    elif bullet_count and action_ratio < 0.5:
        lowering.append("Too few experience bullets begin with clear, specific action language.")
        priority_actions.append(
            "Rewrite the weakest experience bullet so it begins with a strong, accurate action verb and clearly states the work performed."
        )
    elif bullet_count < 2:
        lowering.append("The experience section contains too few developed bullet points.")
        priority_actions.append(
            "Add one truthful bullet describing another important responsibility, skill, or contribution from the role."
        )
    if len(concrete_skills) < 2:
        lowering.append("Few concrete tools, systems, procedures, or role-specific skills were identified.")
        priority_actions.append(
            "Name the concrete tools, systems, safety procedures, languages, or certifications you have actually used."
        )
    if timeline_flags:
        lowering.append("One or more experience claims need to be reconciled with the listed dates.")
        priority_actions.append(
            "Correct the experience-duration claim so it agrees with the listed dates, or add the missing role with accurate dates."
        )
    early_career_density_is_useful = len(concrete_skills) >= 2 or bullet_count >= 2
    length_needs_attention = (
        word_count < expected_minimum
        or (
            career_stage in {"student", "entry_level"}
            and 100 <= word_count <= 200
            and not early_career_density_is_useful
        )
    )
    if length_needs_attention:
        priority_actions.append(
            "Add one or two relevant examples that clarify responsibilities, tools used, or results; do not add filler solely to increase length."
        )
    lowering = lowering[:3]
    while len(lowering) < 2:
        lowering.append("More specific evidence would help distinguish responsibilities from measurable contributions.")

    supporting = []
    if career_stage == "student" and academic_evidence_count:
        supporting.append("Coursework, academic achievement, or other student evidence strengthens the resume.")
    if concrete_skills:
        supporting.append("Concrete, role-relevant skills are clearly identified.")
    if employment_ranges and not timeline_flags:
        supporting.append("The employment timeline is clear with no significant contradictions detected.")
    if action_ratio >= 0.5:
        supporting.append("Several experience bullets begin with clear action language.")
    if has_email and has_phone:
        supporting.append("The contact section includes both an email address and phone number.")
    if career_stage in {"student", "entry_level"} and 100 <= word_count <= 250:
        supporting.append("The resume stays concise and appropriate for an early-career applicant.")
    supporting = supporting[:3]
    while len(supporting) < 2:
        supporting.append("The resume provides a readable foundation that employers can scan quickly.")

    reassurance = (
        "A shorter work history is normal at the beginning of a career. The score can improve by "
        "expanding truthful details about key responsibilities, tools used, workload, and outcomes; not by adding filler."
        if career_stage in {"student", "entry_level"}
        else "This score is a starting point, not a hiring prediction. It can improve by adding concise, truthful evidence about responsibilities, tools, workload, and outcomes."
    )
    return {
        "career_stage": {"code": career_stage, "label": stage_label},
        "summary_header": summary_header,
        "context_explanation": length_context + history_context,
        "factors_lowering_score": lowering,
        "factors_supporting_score": supporting,
        "priority_actions": list(dict.fromkeys(priority_actions))[:3],
        "reassurance_note": reassurance,
    }


def analyze_resume_bullet(bullet: str, sections: Dict[str, str]):
    action_match = re.match(r"^([A-Za-z][A-Za-z-]+)", bullet.strip())
    matched_skills = parse_contextual_resume_skills({
        "work_experience": bullet,
        "skills": sections.get("skills", ""),
    })
    metric_matches = re.findall(
        r"(?:\d+%|\$\s?[\d,.]+|\b\d+\+?\s+(?:customers|orders|transactions|projects|tickets|users|hours)\b)",
        bullet,
        re.I,
    )
    return {
        "original": bullet.strip(),
        "action": action_match.group(1) if action_match else None,
        "skills": [item["label"] for item in matched_skills],
        "metrics": metric_matches,
        "food_service_context": bool(re.search(
            r"\b(?:restaurant|food|cashier|crew member|drive[- ]?thru|orders?|customers?)\b",
            sections.get("work_experience", ""),
            re.I,
        )),
    }


def build_contextual_resume_rewrite(bullet: str, sections: Dict[str, str]):
    analysis = analyze_resume_bullet(bullet, sections)
    original = analysis["original"]
    verification_needed = []
    if analysis["food_service_context"] and re.search(r"customer service|customers|orders|peak", original, re.I):
        after = (
            "Delivered responsive customer service during peak periods while "
            "maintaining an organized and efficient service flow."
        )
        verification_needed = [
            "Add the system used, customer volume, or an accuracy result only if you can verify it."
        ]
    else:
        cleaned = re.sub(
            r"^(?:responsible for|duties included|helped with|worked on|provided|completed)\s*",
            "",
            original,
            flags=re.I,
        ).rstrip(".")
        contextual_labels = {
            item["label"] for item in parse_contextual_resume_skills(sections)
        }
        contextual_actions = []
        if "Customer service" in contextual_labels:
            contextual_actions.append("delivered responsive customer service")
        if "POS operation" in contextual_labels:
            contextual_actions.append("executed customer transactions using the documented POS system")
        if "Cash handling" in contextual_labels:
            contextual_actions.append("managed customer payments")
        if "Inventory management" in contextual_labels:
            contextual_actions.append("maintained inventory readiness for upcoming shifts")
        if "Food safety" in contextual_labels:
            contextual_actions.append("maintained documented food-safety procedures")
        if contextual_actions:
            if len(contextual_actions) == 1:
                action_text = contextual_actions[0]
            elif len(contextual_actions) == 2:
                action_text = " and ".join(contextual_actions)
            else:
                action_text = ", ".join(contextual_actions[:-1]) + ", and " + contextual_actions[-1]
            after = action_text[0].upper() + action_text[1:] + "."
            verification_needed = [
                "Confirm that these responsibilities accurately describe this specific role."
            ]
        elif cleaned and cleaned.lower() not in {"assigned responsibilities", "assigned tasks", "duties"}:
            after = cleaned[0].upper() + cleaned[1:] + "."
            verification_needed = [
                "Add a verified tool, workload, or result if one is available."
            ]
        else:
            after = "Identify the specific responsibility performed before adding this bullet to the resume."
            verification_needed = [
                "The source wording does not contain enough factual detail for a truthful rewrite."
            ]
    return {
        "issue": "This bullet needs clearer action, work context, or verified impact.",
        "before": original,
        "after": after,
        "verification_needed": verification_needed,
    }


def build_resume_job_alignment(resume_text: str, job_description: str):
    if len(job_description.split()) < 20:
        return None
    ignored = {"and", "the", "with", "for", "that", "this", "from", "your", "you", "are", "will", "have", "job", "role", "work", "years", "required", "preferred", "ability"}
    resume_lines = [line for line in _resume_lines(resume_text) if len(line.split()) >= 4]
    requirements = [
        item.strip(" •-*\t")
        for item in re.split(r"\n+|(?<=[.!?;])\s+", job_description)
        if len(item.split()) >= 5
    ][:30]
    supported = []
    missing = []
    for requirement in requirements:
        terms = {
            word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", requirement)
            if word.lower() not in ignored and len(word) > 3
        }
        if len(terms) < 2:
            continue
        best_line = ""
        best_matches = []
        for line in resume_lines:
            matches = [term for term in terms if term in line.lower()]
            if len(matches) > len(best_matches):
                best_line, best_matches = line, matches
        item = {
            "requirement": requirement[:300],
            "matched_terms": best_matches[:8],
            "evidence": best_line[:300] if best_matches else "",
            "status": "supported" if len(best_matches) >= min(3, max(2, round(len(terms) * 0.35))) else "unsupported_or_uncertain",
        }
        (supported if item["status"] == "supported" else missing).append(item)
    return {
        "requirements_analyzed": len(supported) + len(missing),
        "supported": supported[:8],
        "unsupported_or_uncertain": missing[:8],
        "warning": "Related wording is not proof of qualification. Verify every claim before applying.",
    }


def evaluate_resume_document(
    text: str,
    requested_mode="auto",
    target_industry=None,
    target_job_description=None,
    career_stage=None,
):
    lowered = text.lower()
    segmented_sections = segment_resume_sections(text)
    lines = _resume_lines(text)
    experience_text = segmented_sections.get("work_experience", "")
    skills_text = segmented_sections.get("skills", "")
    summary_text = segmented_sections.get("summary", "")
    bullets = _resume_bullets(experience_text)
    word_count = len(re.findall(r"\b[\w+#.-]+\b", text))
    detected_career_stage = _detect_resume_career_stage(text, career_stage)
    career_stage_source = (
        "selected"
        if (career_stage or "").strip().lower().replace("-", "_")
        in {"student", "entry_level", "career_changer", "mid_level", "executive"}
        else "auto"
    )
    sections = {
        "experience": bool(re.search(r"\b(experience|employment|work history)\b", lowered)),
        "skills": bool(re.search(r"\b(skills|competencies|technical skills)\b", lowered)),
        "education": bool(re.search(r"\b(education|degree|certifications?)\b", lowered)),
        "summary": bool(re.search(r"\b(summary|professional profile|objective)\b", lowered)),
    }
    has_email = bool(re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text, re.I))
    has_phone = bool(re.search(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}", text))
    metrics = re.findall(r"(?:\d+%|\$\s?[\d,.]+|\b\d+\+?\s+(?:customers|clients|projects|employees|sales|tickets|users|orders|transactions|hours)\b)", text, re.I)
    weak_bullets = [bullet for bullet in bullets if re.search(r"\b(?:responsible for|duties included|helped with|worked on|provided friendly customer service|completed assigned (?:responsibilities|tasks))\b", bullet, re.I)]
    contextual_skills = parse_contextual_resume_skills(segmented_sections)
    soft_skill_terms = [
        "dependable", "reliable", "hard-working", "team player",
        "communication", "organized", "friendly", "motivated", "punctual",
    ]
    detected_hard_skills = [item["label"] for item in contextual_skills]
    detected_soft_skills = [term for term in soft_skill_terms if term in skills_text.lower()]
    long_lines = [line for line in lines if len(re.findall(r"\b\w+\b", line)) > 35]
    action_pattern = re.compile(r"^(?:achieved|analyzed|built|coordinated|created|delivered|designed|developed|implemented|improved|increased|launched|led|managed|organized|reduced|resolved|streamlined|supported|trained)\b", re.I)
    action_ratio = sum(bool(action_pattern.search(item)) for item in bullets) / len(bullets) if bullets else 0
    ranges, timeline_flags = _timeline_review(experience_text, summary_text)
    valid_ranges = sorted(
        [item for item in ranges if item["end"] >= item["start"]],
        key=lambda item: item["start"],
    )
    merged_ranges = []
    for item in valid_ranges:
        if not merged_ranges or item["start"] > merged_ranges[-1][1] + 1:
            merged_ranges.append([item["start"], item["end"]])
        else:
            merged_ranges[-1][1] = max(merged_ranges[-1][1], item["end"])
    documented_employment_months = sum(end - start + 1 for start, end in merged_ranges)

    job_description = (target_job_description or "").strip()
    mode = "JOB_REVIEW" if len(job_description.split()) >= 20 else "GENERAL"
    industry_source = text + ("\n" + job_description if mode == "JOB_REVIEW" else "")
    industry = _detect_resume_industry(industry_source, target_industry)
    base_weights = RESUME_CATEGORY_WEIGHTS[industry if industry != "general" else "general"]
    weights = apply_resume_career_stage_weights(base_weights, detected_career_stage)
    expectations = RESUME_INDUSTRY_EXPECTATIONS.get(industry, {"label": "General", "keywords": [], "certifications": [], "evidence": []})
    matched_keywords = [term for term in expectations["keywords"] if re.search(rf"\b{re.escape(term)}\b", lowered)]
    matched_certifications = [term for term in expectations["certifications"] if re.search(rf"\b{re.escape(term)}\b", text, re.I)]
    missing_keywords = [term for term in expectations["keywords"] if term not in matched_keywords][:8]
    missing_certifications = [term for term in expectations["certifications"] if term not in matched_certifications]

    minimum_useful_words = {
        "student": 100,
        "entry_level": 100,
        "career_changer": 250,
        "mid_level": 300,
        "executive": 500,
    }[detected_career_stage]
    brevity_ratio = word_count / minimum_useful_words
    brevity_penalty = 25 if word_count < 25 else 8 if brevity_ratio < 0.55 else 0
    formatting_raw = 28 + sum(12 for present in sections.values() if present) + (12 if has_email and has_phone else 4 if has_email or has_phone else 0) + (8 if 200 <= word_count <= 1000 else 0) - brevity_penalty - min(20, len(long_lines) * 4)
    student_academic_evidence = len(re.findall(
        r"\b(?:gpa|honou?r(?:s)?|advanced placement|ap class|dual enrollment|concurrent enrollment|college credits?|coursework|class(?:es)?|student of the (?:month|day)|graduate|graduation)\b",
        text,
        re.I,
    ))
    transferable_evidence = len(re.findall(
        r"\b(?:transferable|transition|career change|cross-functional|trained|managed|coordinated|customer service|communication|leadership|project)\b",
        text,
        re.I,
    ))
    impact_raw = 28 + min(30, len(metrics) * 8) + round(action_ratio * 28) - min(18, len(weak_bullets) * 6)
    skills_raw = 28 + min(32, len(detected_hard_skills) * 8) + min(40, len(matched_keywords) * 4) + min(12, len(matched_certifications) * 6) + (5 if sections["skills"] else 0)
    if detected_career_stage == "student":
        skills_raw += min(20, student_academic_evidence * 3)
        impact_raw += min(10, student_academic_evidence * 2)
    elif detected_career_stage == "career_changer":
        skills_raw += min(16, transferable_evidence * 2)
    timeline_raw = 25 + (60 if ranges else 0) - sum(18 if flag["severity"] == "high" else 8 for flag in timeline_flags)
    first_person = len(re.findall(r"\b(?:I|me|my|mine|we|our|ours)\b", text, re.I))
    grammar_brevity_penalty = 35 if word_count < 25 else 8 if brevity_ratio < 0.55 else 0
    grammar_raw = 65 + (12 if bullets else 0) - grammar_brevity_penalty - min(16, len(long_lines) * 3) - min(12, first_person * 2) - min(12, len(weak_bullets) * 3)
    raw_categories = {
        "formatting": formatting_raw,
        "impact_metrics": impact_raw,
        "skills": skills_raw,
        "timeline_logic": timeline_raw,
        "grammar_tone": grammar_raw,
    }
    category_scores = {name: _compressed_resume_score(score) for name, score in raw_categories.items()}
    weighted_raw = sum(raw_categories[name] * weight for name, weight in weights.items())
    extraordinary = weighted_raw >= 94 and len(metrics) >= 5 and not timeline_flags and len(matched_keywords) >= 5
    overall_score = _compressed_resume_score(weighted_raw, extraordinary)
    ai_risk = _ai_writing_risk(text, bullets)

    red_flags = list(timeline_flags)
    if not has_email or not has_phone:
        red_flags.append({"type": "contact_information", "severity": "medium", "message": "A complete email-and-phone contact block was not detected."})
    if not bullets and sections["experience"]:
        red_flags.append({"type": "ats_parseability", "severity": "review", "message": "Experience content was detected without clear bullets; verify that document extraction preserved the layout."})
    if len(long_lines) > 2:
        red_flags.append({"type": "ats_parseability", "severity": "review", "message": f"{len(long_lines)} unusually long lines may be difficult to scan or may reflect imperfect text extraction."})

    strengths = []
    if detected_career_stage == "student" and experience_text:
        strengths.append("The resume combines student achievements with genuine workplace experience.")
    elif detected_career_stage == "entry_level" and experience_text:
        strengths.append("The resume presents a focused early-career profile supported by real workplace experience.")
    elif experience_text:
        strengths.append("The resume establishes a clear professional foundation through relevant work history.")
    if metrics or action_ratio >= 0.6:
        strengths.append("The experience section begins to communicate contributions rather than only listing responsibilities.")
    if matched_keywords or detected_hard_skills:
        strengths.append("The resume demonstrates a foundation of role-relevant capabilities that can be developed further.")
    if not strengths:
        strengths.append("Provides a readable starting point that can be strengthened with more specific evidence.")

    improvements = []
    if weak_bullets:
        improvements.extend(
            build_contextual_resume_rewrite(bullet, segmented_sections)
            for bullet in weak_bullets[:3]
        )
    if not metrics and not weak_bullets:
        original = bullets[0] if bullets else "Completed assigned responsibilities."
        improvements.append(build_contextual_resume_rewrite(original, segmented_sections))
    if len(detected_hard_skills) < 2:
        improvements.append({
            "issue": "The skills content lacks enough concrete, verifiable abilities.",
            "before": skills_text or "Skills are scattered or not labeled.",
            "after": "List only the tools, systems, safety procedures, languages, or certifications you have actually used.",
            "verification_needed": ["Confirm every skill before adding it."],
        })
    if timeline_flags:
        claim_mismatch = next(
            (flag for flag in timeline_flags if flag["type"] == "experience_claim_mismatch"),
            None,
        )
        improvements.append({
            "issue": "The timeline contains dates that need clarification.",
            "before": timeline_flags[0]["message"],
            "after": (
                f"If the listed work history is complete, replace the unsupported duration claim with approximately {documented_employment_months} months of experience. Otherwise, add the missing role and accurate dates."
                if claim_mismatch
                else "Use Month Year – Month Year consistently and label concurrent, contract, part-time, or caregiving periods truthfully."
            ),
            "verification_needed": ["complete work history", "accurate dates"],
        })
    improvements = improvements[:4]

    score_breakdown = build_resume_score_breakdown(
        career_stage=detected_career_stage,
        word_count=word_count,
        documented_employment_months=documented_employment_months,
        employment_ranges=ranges,
        metric_count=len(metrics),
        bullet_count=len(bullets),
        weak_bullets=weak_bullets,
        concrete_skills=detected_hard_skills,
        timeline_flags=timeline_flags,
        action_ratio=action_ratio,
        has_email=has_email,
        has_phone=has_phone,
        academic_evidence_count=student_academic_evidence,
    )
    score_breakdown["career_stage"]["source"] = career_stage_source
    applied_weight_percentages = resume_weight_percentages(weights)
    score_breakdown["category_weights"] = applied_weight_percentages
    score_breakdown["rubric_note"] = (
        "Student rubric: coursework, student achievements, and concrete skills receive more emphasis; employment timeline and workplace metrics receive less."
        if detected_career_stage == "student"
        else "Career Changer rubric: transferable skills receive more emphasis, while a linear industry timeline receives less."
        if detected_career_stage == "career_changer"
        else "The standard career-stage rubric is applied to this review."
    )

    return {
        "schema_version": "2.3",
        "prompt_version": RESUME_PROMPT_VERSION,
        "evaluation_mode": mode,
        "overall_score": overall_score,
        "score_interpretation": "Scores are compressed toward the center and are guidance, not hiring predictions.",
        "score_breakdown": score_breakdown,
        "category_scores": {
            "formatting": {"score": category_scores["formatting"], "general_weight": 15},
            "impact_metrics": {"score": category_scores["impact_metrics"], "general_weight": 25},
            "skills": {"score": category_scores["skills"], "general_weight": 20},
            "timeline_logic": {"score": category_scores["timeline_logic"], "general_weight": 20},
            "grammar_tone": {"score": category_scores["grammar_tone"], "general_weight": 20},
        },
        "applied_weights": applied_weight_percentages,
        "ai_generated_risk": ai_risk,
        "red_flags": red_flags,
        "key_strengths": strengths[:5],
        "critical_improvements": improvements,
        "section_audits": {
            "experience": {
                "bullet_count": len(bullets),
                "action_led_bullet_ratio": round(action_ratio, 2),
                "metric_count": len(metrics),
                "weak_bullets": weak_bullets[:3],
                "assessment": (
                    "Experience includes specific action and measurable evidence."
                    if bullets and action_ratio >= 0.5 and metrics
                    else "Experience needs more specific actions, work context, or truthful results."
                ),
            },
            "skills": {
                "concrete_skills": contextual_skills,
                "generic_soft_skills": detected_soft_skills,
                "assessment": (
                    "Skills include concrete tools or role-specific abilities."
                    if len(detected_hard_skills) >= 2
                    else "Generic strengths need evidence, and more concrete verified skills should be named."
                ),
            },
        },
        "timeline_audit": {
            "documented_employment_months": documented_employment_months,
            "employment_ranges": ranges,
            "flags": timeline_flags,
            "education_dates_excluded": True,
        },
        "skill_audit": {
            "contextual_skills": contextual_skills,
            "generic_soft_skills": detected_soft_skills,
        },
        "job_alignment": build_resume_job_alignment(text, job_description) if mode == "JOB_REVIEW" else None,
        "industry_alignment": ({
            "industry": expectations["label"],
            "matched_keywords": matched_keywords,
            "missing_keywords_to_verify": missing_keywords,
            "matched_certifications": matched_certifications,
            "missing_certifications_to_verify": missing_certifications,
            "warning": "Missing items are prompts to verify, not instructions to add qualifications the applicant does not have.",
        } if mode == "JOB_REVIEW" else None),
        "analysis_evidence": {
            "career_stage": detected_career_stage,
            "career_stage_source": career_stage_source,
            "word_count": word_count,
            "bullet_count": len(bullets),
            "metric_count": len(metrics),
            "dated_range_count": len(ranges),
        },
    }


def format_resume_evaluation_reply(evaluation):
    category_labels = {
        "formatting": "Formatting",
        "impact_metrics": "Impact and metrics",
        "skills": "Skills",
        "timeline_logic": "Timeline logic",
        "grammar_tone": "Grammar and tone",
    }
    lines = [
        "RÉSUMÉ EVALUATION",
        "",
        f"Overall score: {evaluation['overall_score']}/100",
        evaluation["score_interpretation"],
        "",
        "SCORE CONTEXT",
        f"Career stage: {evaluation['score_breakdown']['career_stage']['label']}",
        evaluation["score_breakdown"]["context_explanation"],
        "What affected the score:",
        *[f"- {item}" for item in evaluation["score_breakdown"]["factors_lowering_score"]],
        "What supported the score:",
        *[f"- {item}" for item in evaluation["score_breakdown"]["factors_supporting_score"]],
        evaluation["score_breakdown"]["reassurance_note"],
        "",
        "CATEGORY SCORES",
    ]
    for key, value in evaluation["category_scores"].items():
        applied = evaluation["applied_weights"][key]
        lines.append(f"- {category_labels[key]}: {value['score']}/100 ({applied}% applied weight)")
    lines.extend(["", "KEY STRENGTHS"])
    lines.extend("- " + item for item in evaluation["key_strengths"])
    lines.extend(["", "CRITICAL IMPROVEMENTS"])
    for item in evaluation["critical_improvements"]:
        lines.extend([
            "- " + item["issue"],
            "  Before: " + item["before"],
            "  After: " + item["after"],
        ])
    risk = evaluation["ai_generated_risk"]
    lines.extend([
        "", "AI-WRITING RISK SIGNAL",
        f"- {risk['risk_level']} risk. {risk['disclaimer']}",
    ])
    lines.extend("- " + item for item in risk["indicators"])
    if evaluation["red_flags"]:
        lines.extend(["", "ITEMS TO REVIEW"])
        lines.extend("- " + item["message"] for item in evaluation["red_flags"])
    alignment = evaluation["industry_alignment"]
    if alignment:
        lines.extend([
            "", "INDUSTRY ALIGNMENT",
            f"- Review type: Job suitability review — {alignment['industry']}",
            "- Matched: " + (", ".join(alignment["matched_keywords"] + alignment["matched_certifications"]) or "No strong industry-specific matches detected."),
            "- Verify if relevant: " + (", ".join(alignment["missing_keywords_to_verify"] + alignment["missing_certifications_to_verify"]) or "No major missing items detected."),
            "- " + alignment["warning"],
        ])
    else:
        lines.extend([
            "", "REVIEW MODE",
            "- GENERAL — no job description was supplied, so job-matching analysis was intentionally omitted.",
        ])
    return "\n".join(lines)


# Structured résumé evaluation returns evidence-based feedback and never
# invents credentials, experience, or accomplishments.
@app.post("/resume-evaluator/evaluate")
def evaluate_resume_endpoint(
    data: ResumeEvaluationRequest,
    request: Request,
):
    get_authenticated_user(request)
    resume_text = normalize_learning_document_text(data.resume_text)
    if len(re.findall(r"\b\w+\b", resume_text)) < 40:
        raise HTTPException(
            status_code=400,
            detail="Provide at least 40 readable resume words for a useful review.",
        )
    job_description = normalize_learning_document_text(data.job_description or "")
    return evaluate_resume_document(
        text=resume_text,
        target_job_description=job_description,
        target_industry=data.target_industry,
        career_stage=None if data.career_stage == "auto" else data.career_stage,
    )


# The learning assistant handles general guidance separately from the
# stateful mock-interview flow below.
@app.post("/learning-assistant")
def learning_assistant(
    data: LearningAssistantMessage,
    request: Request
):
    get_authenticated_user(request)

    message = data.message.strip()
    attachment_name = (
        os.path.basename(data.attachment_name.strip())
        if data.attachment_name
        else None
    )
    if (
        data.attachment_text and
        len(data.attachment_text) > LEARNING_DOCUMENT_MAX_TEXT
    ):
        raise HTTPException(
            status_code=400,
            detail="The attached document contains too much text."
        )

    attachment_text = (
        normalize_learning_document_text(
            data.attachment_text
        )
        if data.attachment_text
        else None
    )

    if message == "":
        raise HTTPException(
            status_code=400,
            detail="Please enter a question or request."
        )

    if len(message) > 800:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please keep your request "
                "under 800 characters."
            )
        )

    normalized = (
    message
    .lower()
    .replace("-", " ")
    )

    safety_reply = assistant_safety_reply(normalized)
    if safety_reply:
        return {
            "reply": safety_reply,
            "safety_notice": True,
            "safety_level": assistant_safety_level(normalized),
            "follow_up_questions": [],
            "authenticity_reminder": "Seek qualified human support for health or safety concerns.",
            "request_document_upload": False
        }

    if any(re.search(pattern, normalized) for pattern in AI_MEDICAL_REQUEST_PATTERNS):
        return {
            "reply": (
                "PathForge cannot diagnose an injury, recommend medication, or replace a qualified "
                "health professional. For urgent or severe symptoms, seek prompt medical help. For "
                "the job-related part, I can help you prepare a factual note for your employer, find "
                "the correct workplace reporting channel, or plan an accommodation request."
            ),
            "follow_up_questions": [
                "How do I document a workplace concern factually?",
                "How do I request a workplace accommodation?"
            ],
            "authenticity_reminder": "Keep health details private unless they are necessary for the request.",
            "request_document_upload": False
        }

    if any(re.search(pattern, normalized) for pattern in AI_EXPLICITLY_UNRELATED_PATTERNS):
        return {
            "reply": (
                "PathForge AI is limited to careers, jobs, applications, resumes, interviews, "
                "workplace readiness, and related professional development. I can’t complete that "
                "unrelated request, even when it is combined with career-related wording."
            ),
            "follow_up_questions": [
                "How can I organize my job search?",
                "How should I prepare for an interview?"
            ],
            "authenticity_reminder": "Keep application and interview information truthful.",
            "request_document_upload": False
        }

    if not attachment_text and not is_career_related_prompt(normalized):
        return {
            "reply": (
                "PathForge AI is limited to careers, jobs, applications, resumes, "
                "interviews, workplace readiness, and related professional development. "
                "I can’t help with that unrelated request. Ask me a career or job question instead."
            ),
            "follow_up_questions": [
                "How can I organize my job search?",
                "How should I prepare for an interview?",
                "How can I improve my resume truthfully?"
            ],
            "authenticity_reminder": "Keep application and interview information truthful.",
            "request_document_upload": False
        }

    reply = (
        "I can help with career exploration, job-search "
        "organization, interview preparation, workplace "
        "readiness, and resume education. Tell me what "
        "you are working on and where you feel uncertain."
    )

    follow_ups = [
        "Where should I begin in Learn + Assistant?",
        "How can I prepare for my first job?",
        "Which interview lesson should I review?"
    ]
    request_document_upload = False

    specific_answers = {
    "how do i identify my strongest skills?": (
        "List three tasks you perform confidently and three "
        "situations where other people rely on you. For each "
        "one, identify the skill involved and the evidence that "
        "shows you used it successfully. Look for skills that "
        "appear more than once."
    ),

    "what skills are useful for retail jobs?": (
        "Retail roles commonly use customer service, clear communication, "
        "reliable attendance, product learning, stocking and organization, "
        "and accurate transaction handling. Choose only skills you can support "
        "with a real example from work, school, volunteering, activities, or "
        "responsibilities at home."
    ),

    "help me create a three step career goal.": (
        "Choose one career area to investigate, identify one "
        "qualification or skill commonly required, and select "
        "one realistic action with a completion date. Keep the "
        "first action small enough to begin this week."
    ),

    "how can i compare two career options?": (
        "Compare the daily duties, required training, expected "
        "schedule, work environment, advancement opportunities, "
        "and how well each option fits your interests and current "
        "responsibilities. Research both options using reliable "
        "sources before deciding."
    ),

    "how do i choose a star example?": (
        "Choose a genuine situation that relates to the skill "
        "the employer is asking about. The best example has a "
        "clear responsibility, specific actions you personally "
        "took, and an accurate result or lesson learned."
    ),

    "how long should a behavioral answer be?": (
        "Most behavioral answers should be focused enough to "
        "deliver in roughly one to two minutes. Keep the "
        "situation brief, spend most of the time explaining your "
        "actions, and finish with the result or lesson learned."
    ),

    "what if i have not faced that exact situation?": (
        "Say honestly that you have not faced the exact "
        "situation. Then offer a related genuine example or "
        "explain the steps you would take based on your actual "
        "experience and judgment."
    ),

    "what belongs in a resume summary?": (
        "A resume summary can include your relevant experience, "
        "two or three important strengths, and the value you can "
        "offer in the type of role you are pursuing. Keep it "
        "brief, specific, and supported by the rest of the resume."
    ),

    "how do i write an accomplishment statement?": (
        "Begin with an action verb, describe the task or problem, "
        "and explain the accurate result or who benefited. Add "
        "numbers only when they are truthful and meaningful."
    ),

    "what does truthful tailoring mean?": (
        "Truthful tailoring means emphasizing the genuine "
        "experience and skills most relevant to a particular "
        "job. It does not mean changing dates, inventing skills, "
        "or adding responsibilities you never had."
    ),

    "which activities count as experience?": (
        "Relevant experience can come from employment, school "
        "projects, volunteering, clubs, athletics, caregiving, "
        "personal projects, and community activities. Focus on "
        "the responsibilities and skills you can demonstrate."
    ),

    "how can i describe a school project?": (
        "Explain the project's purpose, your specific role, the "
        "steps or tools you used, and the result. If it was a "
        "group project, clearly distinguish your contribution "
        "while acknowledging the team's work."
    ),

    "what entry level jobs should i explore?": (
        "Begin with jobs that match your current skills, schedule, "
        "transportation, interests, and training needs. Compare "
        "the actual duties and requirements instead of relying "
        "only on job titles."
    )
}

    specific_answers.update({
        "where should i begin in learn + assistant?": (
            "If you are unsure where to begin, start with "
            "Explore Interests and Strengths. If an interview "
            "is approaching, begin with Interview Foundations. "
            "If you are actively applying, review Job-Search "
            "Readiness and Resume Fundamentals."
        ),

        "how can i prepare for my first job?": (
            "Review the role's duties, plan transportation and "
            "your schedule, prepare genuine examples from school "
            "or community activities, and learn how the employer "
            "expects staff to communicate. Ask questions when "
            "instructions are unclear."
        ),

        "which interview lesson should i review?": (
            "Start with Interview Foundations for common "
            "questions. Choose Behavioral Interviews for STAR "
            "answers, Interview Formats for phone or virtual "
            "preparation, and Interview Day and Follow-Up when "
            "the appointment is close."
        ),

        "how can i identify transferable skills?": (
            "List responsibilities from previous work, school, "
            "projects, volunteering, or caregiving. For each "
            "responsibility, identify the skill used and where "
            "that same skill appears in the new role."
        ),

        "how do i explain limited experience honestly?": (
            "Acknowledge that you are early in your experience, "
            "then describe genuine responsibilities, relevant "
            "skills, and evidence that you learn reliably. Do "
            "not apologize for being new or invent experience."
        ),

        "which genuine examples could fit an interview?": (
            "Consider a problem you solved, a deadline you met, "
            "a time you helped someone, a mistake you corrected, "
            "or a situation where you learned quickly. Choose "
            "the example most relevant to the question."
        ),

        "how do i identify transferable skills?": (
            "Compare the new role's duties with tasks you have "
            "already performed. Look for shared abilities such "
            "as communication, organization, customer service, "
            "safety, analysis, teamwork, or leadership."
        ),

        "what is a realistic career change goal?": (
            "Choose one target role, investigate its essential "
            "requirements, identify your strongest transferable "
            "skill, and select one achievable action to address "
            "a skill gap within a specific time period."
        ),

        "how do i discuss a career change in an interview?": (
            "Briefly explain what attracts you to the new field, "
            "connect your genuine transferable skills to the "
            "role, and describe the steps you are taking to "
            "learn. Keep the explanation positive and forward-looking."
        ),

        "how should i answer tell me about yourself?": (
            "Give a brief professional introduction: describe "
            "your current situation, mention one or two relevant "
            "strengths, and explain your genuine interest in the "
            "role. Avoid sharing unrelated personal details."
        ),

        "what questions should i ask an interviewer?": (
            "Ask about early priorities, training, team structure, "
            "how success is measured, and the next hiring step. "
            "Choose questions that were not already answered in "
            "the posting or conversation."
        ),

        "how do i prepare for a virtual interview?": (
            "Test the meeting link, camera, microphone, internet, "
            "lighting, and display name. Close distractions, keep "
            "the employer's contact information nearby, and join "
            "a few minutes early."
        ),

        "how often should i follow up?": (
            "Follow the employer's stated timeline. If no timeline "
            "was provided, one polite message after several "
            "business days is usually reasonable. Avoid sending "
            "repeated daily requests."
        ),

        "how can i organize my weekly job search?": (
            "Set separate times for finding jobs, preparing "
            "applications, practicing interviews, and following "
            "up. Record each application and its next action in "
            "your PathForge Application Tracker."
        ),

        "how do i decide whether a job fits me?": (
            "Compare the duties, required qualifications, schedule, "
            "location, transportation, pay information, work "
            "environment, and growth opportunities with your "
            "current needs and genuine skills."
        ),

        "how can i spot a job scam?": (
            "Verify the opening on the employer's official careers site. "
            "Be cautious about personal-email recruiters, unexpected "
            "offers, pressure to act immediately, requests for sensitive "
            "information before a verified hiring stage, or any request "
            "to pay, deposit a check, buy equipment, or return money."
        ),

        "how do i verify an employer?": (
            "Find the employer's official website independently and confirm "
            "the opening in its careers section. Compare the recruiter's "
            "email domain and contact details with official information. "
            "If uncertain, contact the employer through a phone number or "
            "website you found yourself—not one supplied by the recruiter."
        ),

        "what information should i avoid sharing early?": (
            "Before you have verified the employer and reached a legitimate "
            "hiring stage, do not share banking credentials, account "
            "passwords, Social Security numbers, identification documents, "
            "or payment information. Never pay to receive a job offer."
        ),

        "how do work values affect career fit?": (
            "Work values describe what matters to you in a workplace, "
            "such as independence, stability, service, advancement, "
            "recognition, or teamwork. Compare those values with the "
            "daily duties and environment of an occupation instead of "
            "choosing from its title alone."
        ),

        "how do i request an informational interview?": (
            "Ask for a short conversation to learn about the person's "
            "work, career path, and advice. Explain why you contacted "
            "them, request a limited amount of time, prepare thoughtful "
            "questions, and thank them afterward. Do not present the "
            "conversation as a demand for a job."
        ),

        "what questions should i ask about a career?": (
            "Ask about typical duties, useful skills, training paths, work "
            "environment, challenges, changes in the field, and advice for "
            "someone entering it. Avoid requesting confidential employer or "
            "client information."
        ),

        "how do i evaluate a job offer?": (
            "Review the written duties, base pay, pay period, schedule, "
            "location, benefits, employment status, start date, and any "
            "conditions. Compare the complete offer with your needs, "
            "verify unclear terms, and ask for reasonable time to review "
            "it before accepting when possible."
        ),

        "which offer details should be in writing?": (
            "Look for the job title, primary duties, base pay and pay period, "
            "schedule, work location, employment status, start date, benefits "
            "eligibility, and important conditions. Ask the employer to "
            "clarify anything that differs from the posting or interviews."
        ),

        "how do i compare pay periods?": (
            "Keep hourly, weekly, monthly, and annual amounts labeled rather "
            "than comparing the raw numbers. Estimate expected hours, unpaid "
            "time, overtime rules, commissions, tips, and benefits separately. "
            "Treat estimates as estimates until the employer confirms them."
        ),

        "how can i make my resume ats friendly?": (
            "Use recognizable section headings, consistent dates, and a "
            "standard work-history format. Follow the employer's file-type "
            "instructions and avoid placing essential qualifications only "
            "inside headers, footers, tables, text boxes, pictures, or "
            "graphics. ATS systems differ, so no format can guarantee a result."
        ),

        "how should i use ai for career preparation?": (
            "Use AI to brainstorm questions, review structure, practice "
            "answers, and suggest revisions. Verify factual claims with "
            "trusted sources, preserve your own voice, and reject invented "
            "experience, skills, dates, credentials, or accomplishments."
        ),

        "what does career readiness include?": (
            "Career readiness includes ongoing career development, clear "
            "communication, critical thinking, teamwork, professionalism, "
            "responsible technology use, and learning from feedback. Show "
            "these skills through specific behavior and evidence rather "
            "than unsupported labels."
        ),

        "how should i negotiate salary?": (
            "Research a reasonable range for the role and location, then ask whether "
            "there is flexibility in the base pay or total package. Explain your request "
            "using relevant experience and the role’s responsibilities, not personal expenses."
        ),

        "how do i respond to a job rejection?": (
            "Acknowledge the decision professionally, thank the employer for their time, "
            "and ask for feedback only when appropriate. Record what you learned, then "
            "continue with other applications rather than treating one outcome as a prediction."
        ),

        "how do i explain an employment gap?": (
            "Use a brief, truthful explanation without unnecessary personal detail. "
            "Then redirect to current readiness, relevant activity during the gap when "
            "applicable, and evidence that you can perform the role now."
        ),

        "who should i use as a professional reference?": (
            "Choose people who directly observed your reliable work, skills, or character, "
            "such as supervisors, instructors, volunteer leaders, or project leads. Ask "
            "permission first and confirm their preferred contact information."
        ),

        "how should i handle a workplace conflict?": (
            "Focus on observable behavior, the work impact, and a specific constructive "
            "request. Speak privately and calmly when safe. Document serious patterns and "
            "use the appropriate supervisor or HR process when direct discussion is unsafe or ineffective."
        )
    })

    dishonest_terms = [
        "make up",
        "fabricate",
        "lie",
        "fake experience",
        "fake resume",
        "falsify",
        "invent experience",
        "invent qualifications"
    ]

    canonical_question = normalize_assistant_question(normalized)
    canonical_specific_answers = {
        normalize_assistant_question(question): answer
        for question, answer in specific_answers.items()
    }

    if canonical_question in canonical_specific_answers:
        reply, follow_ups = canonical_specific_answers[canonical_question], []

    elif "resume summary" in normalized:
        reply = specific_answers["what belongs in a resume summary?"]
        follow_ups = ["How do I write an accomplishment statement?", "What does truthful tailoring mean?"]

    elif any(
        term in normalized
        for term in ["salary negotiation", "negotiate salary", "higher salary", "counter offer", "higher pay"]
    ):
        reply = specific_answers["how should i negotiate salary?"]
        follow_ups = ["How do I evaluate a job offer?", "How do I compare pay periods?"]

    elif any(
        term in normalized
        for term in ["job rejection", "rejected", "didn't get the job", "did not get the job"]
    ):
        reply = specific_answers["how do i respond to a job rejection?"]
        follow_ups = ["How can I organize my weekly job search?", "How often should I follow up?"]

    elif any(
        term in normalized
        for term in ["employment gap", "resume gap", "career gap", "gap in work"]
    ):
        reply = specific_answers["how do i explain an employment gap?"]
        follow_ups = ["What belongs in a resume summary?", "How should I answer tell me about yourself?"]

    elif any(
        term in normalized
        for term in ["professional reference", "job reference", "references"]
    ):
        reply = specific_answers["who should i use as a professional reference?"]
        follow_ups = []

    elif any(
        term in normalized
        for term in ["workplace conflict", "conflict with", "difficult coworker", "problem with my boss"]
    ):
        reply = specific_answers["how should i handle a workplace conflict?"]
        follow_ups = []

    elif any(term in normalized for term in ["ask for a raise", "request a raise", "pay raise", "salary increase"]):
        reply = (
            "Prepare a short request based on your responsibilities, documented contributions, and "
            "current market information for comparable work. Ask for a scheduled conversation, name "
            "the adjustment you want, and be ready to discuss timing or other compensation if the "
            "employer cannot approve it immediately."
        )
        follow_ups = ["How should I negotiate salary?", "How do I document my contributions?"]

    elif any(term in normalized for term in ["compare benefits", "benefits should i compare", "insurance benefits", "health insurance", "benefits package"]):
        reply = (
            "Compare employee premiums, deductibles, copays, coverage limits, provider networks, "
            "waiting periods, paid time off, retirement contributions, and eligibility dates. Keep "
            "salary and benefits separate, and verify details in the employer’s written plan materials."
        )
        follow_ups = ["How do I evaluate a job offer?", "Which offer details should be in writing?"]

    elif any(term in normalized for term in ["find remote work", "find remote jobs", "remote job search"]):
        reply = (
            "Search for roles that explicitly state remote eligibility and confirm any location, time-zone, "
            "travel, or equipment requirements in the official posting. Verify the opening on the employer’s "
            "careers site, because remote-job scams are common, and track each legitimate application."
        )
        follow_ups = ["How can I spot a job scam?", "How do I organize my weekly job search?"]

    elif "background check" in normalized:
        reply = (
            "Review the employer’s instructions, use accurate names and dates, and gather only the records "
            "the verified employer requests through its official process. Do not send sensitive identity "
            "documents through an unverified email or recruiter. If a report appears inaccurate, ask for "
            "the employer’s correction or dispute process."
        )
        follow_ups = ["How do I verify an employer?", "What information should I avoid sharing early?"]

    elif any(term in normalized for term in ["harassment at work", "workplace harassment", "discriminating against", "workplace discrimination"]):
        reply = (
            "Write down factual details such as dates, words or actions, witnesses, and work impact, and "
            "preserve relevant messages. Use the employer’s reporting policy or an appropriate manager or "
            "HR contact when safe. For immediate danger, contact emergency help; for advice about legal "
            "rights or deadlines, use a qualified local professional or government workplace agency."
        )
        follow_ups = ["How do I document a workplace concern factually?", "How should I handle a workplace conflict?"]

    elif any(term in normalized for term in ["caregiving as experience", "caregiver experience", "caregiving experience"]):
        reply = (
            "Caregiving can demonstrate genuine skills when you describe the work accurately. Focus on "
            "relevant responsibilities such as scheduling, communication, recordkeeping, transportation, "
            "problem-solving, or coordinating services, while protecting the other person’s private details."
        )
        follow_ups = ["Which activities count as experience?", "How do I identify transferable skills?"]

    elif any(term in normalized for term in ["be a reference", "ask for a reference", "teacher as a reference"]):
        reply = specific_answers["who should i use as a professional reference?"]
        follow_ups = []

    elif any(term in normalized for term in ["what should i wear", "interview outfit", "dress for an interview"]):
        reply = (
            "Choose clean, well-fitting clothing that is slightly more polished than the role’s usual dress, "
            "unless the employer gives specific instructions. Prioritize safety requirements and comfort, "
            "and ask the recruiter when the workplace dress expectation is unclear."
        )
        follow_ups = ["How early should I arrive for an interview?", "What questions should I ask an interviewer?"]

    elif any(term in normalized for term in ["how early should i arrive", "when should i arrive"]):
        reply = (
            "Plan to be ready about 10–15 minutes early without arriving excessively early at the workplace. "
            "For video interviews, join a few minutes early after testing the link. Allow extra travel time "
            "and contact the employer promptly if an unavoidable delay occurs."
        )
        follow_ups = ["How do I prepare for a virtual interview?"]

    elif any(term in normalized for term in ["negotiate my schedule", "ask about my schedule", "schedule flexibility"]):
        reply = (
            "State the hours you can reliably work, identify any firm limits, and ask which parts of the "
            "schedule are flexible. Discuss availability before accepting when it could affect the role, and "
            "get any agreed schedule condition in writing."
        )
        follow_ups = ["How do I evaluate a job offer?"]

    elif any(
        term in normalized
        for term in ["request an accommodation", "workplace accommodation", "interview accommodation", "disability accommodation"]
    ):
        reply = (
            "Contact the employer or its accommodation contact and briefly state that you need an "
            "accommodation for the application, interview, or work process. Describe the change you "
            "need rather than sharing unnecessary medical details. Ask what process or documentation "
            "the employer requires, because requirements vary by location and situation."
        )
        follow_ups = ["How do I write a concise accommodation request?", "What interview details should I confirm?"]

    elif any(
        term in normalized
        for term in ["withdraw my application", "withdraw an application", "withdraw from consideration"]
    ):
        reply = (
            "Send a short, prompt message thanking the employer and clearly stating that you are "
            "withdrawing from consideration. You do not need to provide private details. If an "
            "interview is scheduled, cancel it directly rather than simply not attending."
        )
        follow_ups = []

    elif any(
        term in normalized
        for term in ["follow up email", "follow-up email", "thank you email", "thank-you email", "thank you note", "thank-you note"]
    ):
        reply = (
            "Subject: Thank you for the interview\n\nThank the interviewer for their time, name the "
            "role, mention one specific point from the conversation, briefly restate your interest, "
            "and close professionally. Replace every detail with information from your actual interview."
        )
        follow_ups = ["How often should I follow up?", "What questions should I ask an interviewer?"]

    elif any(
        term in normalized
        for term in ["i was fired", "i got fired", "explain being fired", "termination in an interview", "why were you terminated", "why i was terminated"]
    ):
        reply = (
            "Give a brief, truthful explanation without blaming or oversharing. Acknowledge what "
            "happened, state what you learned or changed, and redirect to evidence that you are ready "
            "for the new role. Do not describe a termination as a resignation or layoff if it was not."
        )
        follow_ups = ["How should I answer tell me about yourself?", "Which genuine examples could fit an interview?"]

    elif any(
        term in normalized
        for term in ["quit my job", "leave my job", "resign from my job", "resign professionally", "resignation letter", "resignation message", "give notice"]
    ):
        reply = (
            "Before resigning, consider immediate safety, your finances, benefits, any written "
            "employment terms, and whether another offer is final. If you decide to leave, use a "
            "short written notice with your intended last day, follow local requirements, and keep "
            "the message professional. PathForge cannot decide the personal risk for you."
        )
        follow_ups = ["How do I write a resignation message?", "How do I organize a job search before leaving?"]

    elif any(term in normalized for term in ["cancel my interview", "cancel an interview", "cancel tomorrow's interview", "cancel tomorrow’s interview"]):
        reply = (
            "Contact the employer as soon as possible, identify the scheduled interview, and clearly say "
            "whether you are withdrawing or requesting another time. Keep the explanation brief, apologize "
            "for the inconvenience, and do not simply miss the appointment."
        )
        follow_ups = []

    elif any(
        term in normalized
        for term in [
            "job scam",
            "fake job",
            "scam recruiter",
            "suspicious offer",
            "pay for equipment"
        ]
    ):
        reply = specific_answers["how can i spot a job scam?"]
        follow_ups = [
            "How do I verify an employer?",
            "What information should I avoid sharing early?",
            "How do I evaluate a job offer?"
        ]

    elif any(
        term in normalized
        for term in [
            "networking",
            "informational interview",
            "career contact",
            "reach out to someone"
        ]
    ):
        reply = specific_answers[
            "how do i request an informational interview?"
        ]
        follow_ups = [
            "What questions should I ask about a career?",
            "How do work values affect career fit?",
            "How can I compare two career options?"
        ]

    elif any(
        term in normalized
        for term in [
            "job offer",
            "offer details",
            "accept an offer",
            "evaluate an offer"
        ]
    ):
        reply = specific_answers["how do i evaluate a job offer?"]
        follow_ups = [
            "Which offer details should be in writing?",
            "How do I compare pay periods?",
            "How can I spot a job scam?"
        ]

    elif any(
        term in normalized
        for term in dishonest_terms
    ):
        reply = (
            "Do not invent experience, skills, credentials, "
            "or accomplishments. Look for a genuine example "
            "from employment, school, volunteering, projects, "
            "caregiving, athletics, or community activities. "
            "A truthful example can still demonstrate useful "
            "skills even when it comes from another setting."
        )

        follow_ups = [
            "How can I identify transferable skills?",
            "How do I explain limited experience honestly?",
            "Which genuine examples could fit an interview?"
        ]

    elif any(
        term in normalized
        for term in [
            "career change",
            "changing careers",
            "change careers",
            "switch careers",
            "new career",
            "different career",
            "move into",
            "transferable"
        ]
    ):
        reply = (
            "Compare your previous responsibilities with the "
            "duties in the new field. Look for genuine "
            "transferable skills such as communication, "
            "planning, customer service, safety, analysis, "
            "leadership, or project coordination. Then choose "
            "one realistic step that could close an important "
            "skill gap."
        )

        follow_ups = [
            "How do I identify transferable skills?",
            "What is a realistic career-change goal?",
            "How do I discuss a career change in an interview?"
        ]

    elif any(
        term in normalized
        for term in [
            "workplace",
            "work readiness",
            "professional behavior",
            "reliable",
            "reliability",
            "communicate with a supervisor",
            "first week at work"
        ]
    ):
        reply = (
            "Workplace readiness includes arriving on time, "
            "communicating early about problems, listening "
            "carefully, asking useful questions, accepting "
            "feedback, and completing agreed responsibilities. "
            "Prepare by confirming your schedule, transportation, "
            "dress expectations, and supervisor contact method."
        )

        follow_ups = []
    

    elif any(
        term in normalized
        for term in [
            "first job",
            "no experience",
            "limited experience",
            "school project",
            "entry level",
            "activities count as experience"
        ]
    ):
        reply = (
            "First-time job seekers can use genuine evidence "
            "from school projects, volunteering, clubs, "
            "athletics, caregiving, and community activities. "
            "Focus on your responsibilities, the skills you "
            "practiced, and how your work helped someone or "
            "produced a useful result."
        )

        follow_ups = [
            "Which activities count as experience?",
            "How can I describe a school project?",
            "What entry-level jobs should I explore?"
        ]

    elif any(
        term in normalized
        for term in [
            "interest",
            "strength",
            "strongest skills",
            "career goal",
            "career path",
            "career option",
            "where should i begin"
        ]
    ):
        reply = (
            "Begin with evidence from your life: tasks that "
            "hold your attention, problems you enjoy solving, "
            "skills others rely on, and work environments you "
            "prefer. Choose one career area to investigate and "
            "set a small goal with a specific action and date."
        )

        follow_ups = [
            "How do I identify my strongest skills?",
            "Help me create a three-step career goal.",
            "How can I compare two career options?"
        ]

    elif any(
        term in normalized
        for term in [
            "behavioral",
            "star",
            "tell me about a time",
            "genuine example",
            "exact situation"
        ]
    ):
        reply = (
            "Use the STAR structure. Explain the Situation, "
            "describe your Task or responsibility, state the "
            "specific Actions you took, and explain the accurate "
            "Result or lesson learned. Always choose a genuine "
            "example and focus on your real contribution."
        )

        follow_ups = [
            "How do I choose a STAR example?",
            "How long should a behavioral answer be?",
            "What if I have not faced that exact situation?"
        ]

    elif "cover letter" in normalized:
        reply = (
            "Use a short opening naming the role, one paragraph connecting two or three genuine "
            "qualifications to the employer’s needs, and a concise closing. Add a specific example "
            "instead of repeating the resume, and verify the employer and contact name before sending it."
        )
        follow_ups = ["What does truthful tailoring mean?", "How do I write an accomplishment statement?"]

    elif "portfolio" in normalized:
        reply = (
            "Choose a small set of relevant, genuine work samples. For each sample, explain the goal, "
            "your individual contribution, tools used, result, and any private information you removed. "
            "Use clear navigation and test every link before sharing it with an employer."
        )
        follow_ups = ["How can I identify transferable skills?", "What does truthful tailoring mean?"]

    elif any(term in normalized for term in ["track an external application", "track external application", "external application"]):
        reply = (
            "After applying on the employer’s website, add the job to PathForge’s Application Tracker and "
            "record the submission date, source, current status, saved job description, and next follow-up. "
            "PathForge cannot read the employer’s private system automatically, so update changes from emails "
            "or the employer portal as they occur."
        )
        follow_ups = ["How often should I follow up?", "How can I organize my weekly job search?"]

    elif any(term in normalized for term in ["write my entire application", "complete my application for me", "answer my application for me"]):
        reply = (
            "I can help you understand a question, organize truthful evidence, and review your draft, but "
            "you should provide and approve the final answers. Do not submit invented experience, availability, "
            "credentials, demographic information, or legal attestations."
        )
        follow_ups = ["How can I identify transferable skills?", "How do I explain limited experience honestly?"]

    elif any(
        term in normalized
        for term in [
            "interview",
            "interviewer",
            "practice question",
            "virtual interview",
            "phone interview",
            "tell me about yourself",
            "questions should i ask"
        ]
    ):
        reply = (
            "Review the job description, research the employer, "
            "and choose genuine examples that demonstrate "
            "relevant skills. Practice your key points aloud "
            "instead of memorizing every word. During the "
            "interview, listen fully and ask for clarification "
            "when necessary."
        )

        follow_ups = [
            "How should I answer tell me about yourself?",
            "What questions should I ask an interviewer?",
            "How do I prepare for a virtual interview?"
        ]

    elif any(
        term in normalized
        for term in [
            "resume",
            "résumé",
            "skill section",
            "tailor",
            "cover letter",
            "career document",
            "upload a file",
            "upload my",
            "review my file"
        ]
    ):
        reply = (
            "To give guidance based on your own resume or career "
            "document, select the file from your device when the "
            "upload box appears below. Then add a specific question, "
            "such as which section to strengthen. You can also ask a "
            "general resume question without attaching a file."
        )
        request_document_upload = True

        follow_ups = [
            "What belongs in a resume summary?",
            "How do I write an accomplishment statement?",
            "What does truthful tailoring mean?"
        ]

    elif any(
        term in normalized
        for term in [
            "job search",
            "application",
            "follow up",
            "how often should i follow",
            "weekly job search",
            "job fits"
        ]
    ):
        reply = (
            "Use a repeatable routine: schedule time to search, "
            "save promising jobs, record submitted applications, "
            "keep the job descriptions, and add appropriate "
            "follow-up reminders. Prioritize thoughtful "
            "applications for roles that fit your genuine "
            "qualifications."
        )

        follow_ups = [
            "How often should I follow up?",
            "How can I organize my weekly job search?",
            "How do I decide whether a job fits me?"
        ]    

    if attachment_text:
        resume_evaluation = evaluate_resume_document(
            attachment_text,
            requested_mode=(data.evaluation_mode or "auto").strip().lower(),
            target_industry=data.target_industry,
            target_job_description=data.target_job_description,
            career_stage=data.career_stage,
        )
        improvement_questions = [
            "How should I fix the highest-priority issue without inventing details?",
            "How can I tailor this resume for a specific job posting?",
            "Which bullet should I rewrite first?",
        ]
        return {
            "reply": format_resume_evaluation_reply(resume_evaluation),
            "resume_evaluation": resume_evaluation,
            "evaluator_system_prompt_version": "2.2",
            "follow_up_questions": improvement_questions,
            "authenticity_reminder": (
                "Review and personalize this guidance. Keep every "
                "application and interview answer truthful."
            ),
            "request_document_upload": False,
        }

        # Legacy evaluator retained temporarily below for rollback reference.
        # It is unreachable because structured evaluator version 2 returns above.
        attachment_lower = attachment_text.lower()
        attachment_word_count = len(
            re.findall(r"\b[\w+#.-]+\b", attachment_text)
        )
        section_patterns = {
            "Experience": (
                r"\b(experience|employment|work history)\b"
            ),
            "Skills": (
                r"\b(skills|competencies|technical skills)\b"
            ),
            "Education": (
                r"\b(education|degree|certification)\b"
            ),
            "Summary": (
                r"\b(summary|professional profile|objective)\b"
            )
        }
        present_sections = [
            label
            for label, pattern in section_patterns.items()
            if re.search(pattern, attachment_lower)
        ]
        missing_sections = [
            label
            for label in section_patterns
            if label not in present_sections
        ]
        has_email = bool(re.search(
            r"[\w.+-]+@[\w.-]+\.[a-z]{2,}",
            attachment_text,
            flags=re.IGNORECASE
        ))
        has_phone = bool(re.search(
            r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}",
            attachment_text
        ))
        has_contact_details = has_email and has_phone
        has_dates = bool(re.search(
            r"\b(?:19|20)\d{2}\b",
            attachment_text
        ))
        has_first_person_pronouns = bool(re.search(
            r"\b(?:i|me|my|mine|we|our|ours)\b",
            attachment_text,
            flags=re.IGNORECASE
        ))
        has_weak_phrases = bool(re.search(
            r"\b(?:responsible for|duties included|helped with|worked on)\b",
            attachment_text,
            flags=re.IGNORECASE
        ))
        has_metrics = bool(
            re.search(
                (
                    r"(?:\d+%|\$\s?\d+"
                    r"|\b\d+\+?\s+(?:customers|clients|projects"
                    r"|employees|people|sales|tickets|users|hours)\b)"
                ),
                attachment_text,
                flags=re.IGNORECASE
            )
        )
        action_verbs = {
            "achieved", "analyzed", "built", "coordinated",
            "created", "delivered", "designed", "developed",
            "implemented", "improved", "increased", "launched",
            "led", "managed", "organized", "reduced", "resolved",
            "streamlined", "supported", "trained"
        }
        detected_action_verbs = sorted(
            verb
            for verb in action_verbs
            if re.search(
                rf"\b{re.escape(verb)}\b",
                attachment_lower
            )
        )
        attachment_lines = [
            line.strip()
            for line in attachment_text.splitlines()
            if line.strip()
        ]
        long_lines = [
            line for line in attachment_lines
            if len(re.findall(r"\b[\w+#.-]+\b", line)) > 35
        ]
        bullet_lines = [
            re.sub(r"^[•\-*▪◦]\s*", "", line)
            for line in attachment_lines
            if re.match(r"^[•\-*▪◦]", line)
        ]
        action_verb_pattern = re.compile(
            r"^(?:" + "|".join(
                re.escape(verb) for verb in sorted(action_verbs)
            ) + r")\b",
            flags=re.IGNORECASE
        )
        action_led_bullets = sum(
            1 for line in bullet_lines
            if action_verb_pattern.search(line)
        )
        action_bullet_ratio = (
            action_led_bullets / len(bullet_lines)
            if bullet_lines
            else 0
        )

        structure_score = min(
            100,
            25 +
            (len(present_sections) * 12) +
            (15 if has_contact_details else 0) +
            (12 if has_dates else 0)
        )
        clarity_score = max(
            35,
            100
            - (0 if 200 <= attachment_word_count <= 1000 else 22)
            - (15 if len(long_lines) > 2 else 0)
            - (12 if has_first_person_pronouns else 0)
            - (12 if has_weak_phrases else 0)
        )
        impact_score = min(
            100,
            30 +
            (30 if has_metrics else 0) +
            (
                round(action_bullet_ratio * 40)
                if bullet_lines
                else min(40, len(detected_action_verbs) * 6)
            )
        )
        relevance_score = min(
            100,
            35 +
            (25 if "Skills" in present_sections else 0) +
            (20 if "Experience" in present_sections else 0) +
            (10 if "Education" in present_sections else 0) +
            (10 if "Summary" in present_sections else 0)
        )
        ats_score = min(
            100,
            30 +
            (len(present_sections) * 12) +
            (12 if has_contact_details else 0) +
            (10 if has_dates else 0)
        )
        overall_score = round(
            (
                structure_score +
                clarity_score +
                impact_score +
                relevance_score +
                ats_score
            ) / 5
        )

        strengths = []
        if present_sections:
            strengths.append(
                "The document uses recognizable sections: " +
                ", ".join(present_sections) + "."
            )
        if has_contact_details:
            strengths.append(
                "Contact information appears to be present and "
                "easy to identify."
            )
        if detected_action_verbs:
            strengths.append(
                "Experience statements use action-focused language, "
                "including " +
                ", ".join(detected_action_verbs[:5]) + "."
            )
        if has_metrics:
            strengths.append(
                "At least one statement includes a measurable result "
                "or scale indicator."
            )
        if has_dates:
            strengths.append(
                "Dates help establish the chronology of experience "
                "and education."
            )
        if 300 <= attachment_word_count <= 850:
            strengths.append(
                f"At approximately {attachment_word_count} words, the "
                "resume provides a focused amount of content for review."
            )
        if len(present_sections) >= 3:
            strengths.append(
                "The resume has a broad content foundation across "
                f"{len(present_sections)} recognizable sections."
            )
        if len(bullet_lines) >= 3:
            strengths.append(
                f"The resume uses {len(bullet_lines)} detected bullets, "
                "which supports quick scanning."
            )
        if bullet_lines and action_bullet_ratio >= 0.5:
            strengths.append(
                "At least half of the detected bullets begin with "
                "action-focused language."
            )
        if not strengths:
            strengths.append(
                "The document contains readable résumé content that "
                "can be strengthened with clearer organization."
            )

        feedback = []
        if missing_sections:
            feedback.append(
                "Add or clearly label the following relevant sections: " +
                ", ".join(missing_sections) + ". Only include a Summary "
                "when it adds useful, role-focused information."
            )
        if not has_contact_details:
            feedback.append(
                "Place professional contact information near the top. "
                "Include both an appropriate email address and phone number; "
                "add LinkedIn only when the profile is complete."
            )
        if not has_dates:
            feedback.append(
                "Add clear dates to applicable experience and education "
                "entries, then use one date format consistently."
            )
        if not has_metrics:
            feedback.append(
                "Strengthen appropriate experience bullets with honest "
                "results or scale, such as customers helped, projects "
                "completed, time saved, or accuracy improved. Do not "
                "invent numbers."
            )
        if len(detected_action_verbs) < 3:
            feedback.append(
                "Begin more experience bullets with precise action verbs "
                "that describe what you actually did. Replace vague "
                "phrases such as 'responsible for' where possible."
            )
        elif bullet_lines and action_bullet_ratio < 0.5:
            feedback.append(
                f"Only {action_led_bullets} of {len(bullet_lines)} detected "
                "bullets begin with a recognized action verb. Strengthen "
                "the openings of the remaining bullets where accurate."
            )
        if has_first_person_pronouns:
            feedback.append(
                "Remove first-person pronouns such as I, me, my, we, and "
                "our to keep resume statements concise."
            )
        if has_weak_phrases:
            feedback.append(
                "Replace duty-only phrases such as 'responsible for' or "
                "'worked on' with the action taken, how it was done, and "
                "the truthful result or purpose."
            )
        if len(long_lines) > 2:
            feedback.append(
                "Break long statements into concise bullets so employers "
                "can scan the most relevant evidence quickly."
            )
        if attachment_word_count < 300:
            feedback.append(
                "The résumé is relatively brief. Add specific evidence "
                "of relevant responsibilities, projects, education, or "
                "volunteer work without adding filler."
            )
        elif attachment_word_count > 850:
            feedback.append(
                "The résumé is lengthy. Remove repeated or low-relevance "
                "details and keep the strongest evidence for the target "
                "role."
            )
        if not feedback:
            feedback.append(
                "Tailor the ordering and wording of the strongest truthful "
                "examples to the requirements of each target role."
            )

        score_lines = [
            (
                f"Structure and organization: {structure_score}/100 — "
                "Based on section coverage and document organization."
            ),
            (
                f"Clarity and readability: {clarity_score}/100 — "
                "Based on length and overall readability signals."
            ),
            (
                f"Impact and accomplishments: {impact_score}/100 — "
                "Based on action language and measurable evidence."
            ),
            (
                f"Skills and relevance: {relevance_score}/100 — "
                "Based on visible skills, experience, and education signals."
            ),
            (
                f"ATS readiness: {ats_score}/100 — "
                "Based on recognizable sections and basic parseability."
            )
        ]

        holistic_findings = [
            (
                "Content foundation: "
                f"{len(present_sections)} of {len(section_patterns)} "
                "recognizable core sections were detected"
                + (
                    " (" + ", ".join(present_sections) + ")."
                    if present_sections
                    else "."
                )
            ),
            (
                "Experience evidence: "
                f"{len(bullet_lines)} bullets were detected; "
                f"{action_led_bullets} begin with recognized action language. "
                + (
                    "The resume also includes measurable evidence."
                    if has_metrics
                    else "No clear measurable result was detected."
                )
            ),
            (
                "Readability: "
                f"The extracted resume contains about {attachment_word_count} "
                f"words and {len(long_lines)} unusually long statements."
            ),
            (
                "Career story: "
                + (
                    "Dates are present to support chronology."
                    if has_dates
                    else "Dates were not clearly detected, which makes chronology harder to assess."
                )
            ),
            (
                "Target fit: A general resume review cannot fully judge "
                "role-specific relevance without a target job description. "
                "Use the Resume Workspace with a target posting for a "
                "keyword-alignment comparison."
            )
        ]

        if overall_score >= 85:
            overall_summary = (
                "This résumé has a strong overall foundation. Its main "
                "opportunity is refining the strongest details for the "
                "roles you want."
            )
        elif overall_score >= 70:
            overall_summary = (
                "This résumé has a solid foundation with several clear "
                "strengths. Focused improvements could make its value "
                "easier for employers to recognize."
            )
        elif overall_score >= 55:
            overall_summary = (
                "This résumé communicates useful experience, but some "
                "important areas need clearer organization, stronger "
                "evidence, or more specific wording."
            )
        else:
            overall_summary = (
                "This résumé is a workable starting point, but it needs "
                "more complete structure and clearer evidence of your "
                "skills and experience."
            )

        reply = (
            "RÉSUMÉ EVALUATION\n\n"
            f"{overall_summary}\n\n"
            "IMPORTANT LIMITATIONS\n"
            "- This résumé evaluation does not predict hiring, "
            "interview, or offer chances.\n"
            "- The scores are guidance, not a final grade or an "
            "employer's decision.\n"
            "- PathForge cannot verify whether every résumé claim is "
            "complete or accurate.\n"
            "- ATS systems differ, so this review cannot guarantee how "
            "a particular employer's system will process the résumé.\n"
            "- Text extraction may not fully represent visual layout, "
            "spacing, graphics, or formatting.\n\n"
            f"Overall score: {overall_score}/100\n"
            "Reason: A high-level measure of structure, clarity, impact, "
            "relevance, and ATS readability. It is guidance—not a hiring "
            "prediction.\n\n"
            "HOLISTIC ASSESSMENT\n- " +
            "\n- ".join(holistic_findings) +
            "\n\n"
            "CATEGORY SCORES\n" +
            "\n".join(score_lines) +
            "\n\nSTRENGTHS\n- " +
            "\n- ".join(strengths) +
            "\n\nCONSTRUCTIVE FEEDBACK\n- " +
            "\n- ".join(feedback)
        )
        follow_ups = []

        if missing_sections:
            follow_ups.append(
                "How should I strengthen my missing " +
                missing_sections[0].lower() +
                " section?"
            )

        if not has_metrics:
            follow_ups.append(
                "How can I add truthful measurable results "
                "to my experience bullets?"
            )

        if len(detected_action_verbs) < 3:
            follow_ups.append(
                "How can I replace vague wording with stronger "
                "action-focused bullets?"
            )

        if not has_contact_details:
            follow_ups.append(
                "How should I format the contact section "
                "at the top of my resume?"
            )

        if not has_dates:
            follow_ups.append(
                "How should I format dates consistently on my resume?"
            )

        if has_weak_phrases or has_first_person_pronouns:
            follow_ups.append(
                "Which resume phrases should I rewrite to be more direct?"
            )

        if attachment_word_count < 300:
            follow_ups.append(
                "Which relevant details could make my resume "
                "more complete?"
            )
        elif attachment_word_count > 850:
            follow_ups.append(
                "Which kinds of details should I shorten or remove?"
            )

        if len(follow_ups) < 3:
            follow_ups.extend([
                "Which part of my resume should I improve first?",
                "How can I make my strongest accomplishment "
                "more specific?",
                "How should I tailor this resume truthfully "
                "for a target role?"
            ])

        follow_ups = follow_ups[:3]
        request_document_upload = False

    authenticity_reminder = (
        "Review and personalize this guidance. Keep every "
        "application and interview answer truthful."
    )

    return {
        "reply": reply,
        "follow_up_questions": follow_ups,
        "authenticity_reminder": authenticity_reminder,
        "request_document_upload": request_document_upload
    }


MOCK_INTERVIEW_QUESTIONS = {
    "general": [
        (
            "Tell me about yourself and briefly explain why "
            "you are interested in the {role} role."
        ),
        (
            "What is one strength you would bring to the "
            "{role} role? Give a genuine example."
        ),
        (
            "Describe a challenge you faced and the steps you "
            "took to handle it."
        ),
        (
            "Why are you interested in this organization, and "
            "what would you want to learn in the role?"
        ),
        (
            "What thoughtful question would you ask the "
            "interviewer before the conversation ends?"
        )
    ],
    "behavioral": [
        (
            "Tell me about a time you worked with other people "
            "to complete an important task."
        ),
        (
            "Describe a time you solved a problem with limited "
            "information or resources."
        ),
        (
            "Tell me about a time you had to meet a difficult "
            "deadline."
        ),
        (
            "Describe a time you received feedback and explain "
            "what you did with it."
        ),
        (
            "Tell me about a mistake you made, how you responded, "
            "and what you learned."
        )
    ],
    "first_job": [
        (
            "Tell me about yourself and why the {role} role "
            "interests you."
        ),
        (
            "Which skills from school, volunteering, activities, "
            "caregiving, or personal projects could help you in "
            "this role?"
        ),
        (
            "Give an example that shows you can be dependable "
            "when someone is counting on you."
        ),
        (
            "How would you approach a task you have never done "
            "before?"
        ),
        (
            "What would you ask a supervisor so you could begin "
            "the job successfully?"
        )
    ]
}

MOCK_INTERVIEW_AUTHENTIC_EXAMPLES = {
    "general": [
        (
            "I am currently [your real situation]. Through "
            "[real experience], I developed [relevant skill]. "
            "I am interested in this role because [truthful "
            "reason connected to the work]."
        ),
        (
            "One strength I would bring is [real strength]. "
            "For example, during [real situation], I personally "
            "[specific action], which resulted in [real outcome]."
        ),
        (
            "During [real challenge], my responsibility was "
            "[your responsibility]. I [specific actions], and "
            "the result or lesson was [truthful result]."
        ),
        (
            "I am interested in this organization because "
            "[specific researched reason]. In this role, I hope "
            "to learn [realistic skill or responsibility]."
        ),
        (
            "What would you want the person in this role to "
            "accomplish during the first 60 to 90 days?"
        )
    ],
    "behavioral": [
        (
            "During [real project or event], I worked with "
            "[people involved]. My responsibility was [task]. "
            "I personally [actions], and together we achieved "
            "[truthful result]."
        ),
        (
            "When [real problem] happened, I had [available "
            "information or resources]. I [specific actions], "
            "which led to [real result or lesson]."
        ),
        (
            "I needed to complete [real task] by [deadline]. "
            "I organized the work by [specific steps]. The "
            "result was [truthful outcome]."
        ),
        (
            "I received feedback that [real feedback]. I asked "
            "[clarifying question], changed [specific action], "
            "and afterward [real result or lesson]."
        ),
        (
            "I made a mistake when [real situation]. I took "
            "responsibility by [corrective actions]. The result "
            "was [outcome], and I now [prevention step]."
        )
    ],
    "first_job": [
        (
            "I am currently [your real situation], and I am "
            "interested in this role because [truthful reason]. "
            "A skill I could contribute is [real skill] from "
            "[school, volunteering, or another real activity]."
        ),
        (
            "During [real activity], I practiced [relevant "
            "skill] by [specific action]. That experience would "
            "help me with [actual duty in the role]."
        ),
        (
            "When [person or group] depended on me to [real "
            "responsibility], I [specific actions]. I completed "
            "it by [deadline or standard], resulting in [outcome]."
        ),
        (
            "I would first review the instructions and identify "
            "what I understand. Then I would ask [appropriate "
            "person] a specific question, take notes, and confirm "
            "the task before beginning."
        ),
        (
            "What training will I receive during my first few "
            "weeks, and who should I ask when I need clarification?"
        )
    ]
}

MOCK_INTERVIEW_TRANSITIONS = [
    "Thank you for explaining that.",
    "I appreciate that response.",
    "Thank you. Let us continue.",
    "That is helpful context."
]


def analyze_mock_interview_answer(answer: str):
    normalized_answer = answer.lower()
    words = answer.split()
    strengths = []
    improvements = []

    if len(words) >= 45:
        strengths.append(
            "Your answer includes enough detail to develop a "
            "clear example."
        )
    elif len(words) >= 20:
        strengths.append(
            "Your answer is focused and gives the interviewer "
            "a useful starting point."
        )
    else:
        improvements.append(
            "Add one or two specific details so the interviewer "
            "can understand the situation and your contribution."
        )

    personal_action_terms = [
        "i organized",
        "i created",
        "i helped",
        "i learned",
        "i decided",
        "i communicated",
        "i completed",
        "i solved",
        "i asked",
        "i improved"
    ]

    if any(
        term in normalized_answer
        for term in personal_action_terms
    ):
        strengths.append(
            "You describe an action you personally took."
        )
    else:
        improvements.append(
            "Clarify what you personally did by using a specific "
            "statement such as “I organized,” “I communicated,” "
            "or “I learned.”"
        )

    result_terms = [
        "result",
        "outcome",
        "because",
        "learned",
        "improved",
        "completed",
        "finished",
        "successful",
        "feedback"
    ]

    if any(
        term in normalized_answer
        for term in result_terms
    ):
        strengths.append(
            "You include an outcome or lesson learned."
        )
    else:
        improvements.append(
            "Finish with the truthful result, what changed, or "
            "what you learned."
        )

    if len(words) > 220:
        improvements.append(
            "Shorten a few background details so the main point "
            "can be delivered comfortably in about two minutes."
        )

    if not strengths:
        strengths.append(
            "You attempted the question and now have material "
            "you can refine through practice."
        )

    template_phrases = [
        "as an ai language model",
        "in today's fast paced",
        "in today’s fast paced",
        "it is important to note",
        "delve into",
        "leverage my skills",
        "dynamic landscape",
        "seamlessly",
        "multifaceted",
        "uniquely qualified"
    ]

    matched_phrases = [
        phrase
        for phrase in template_phrases
        if phrase in normalized_answer
    ]

    corporate_template_terms = [
        "strategic",
        "methodologies",
        "proactively",
        "optimize",
        "exceed expectations",
        "deadline driven",
        "stakeholders",
        "innovative solutions",
        "exceptional value",
        "organizational outcomes",
        "commitment to excellence",
        "professional landscape",
        "professional capabilities"
    ]

    matched_corporate_terms = [
        term
        for term in corporate_template_terms
        if term in normalized_answer
    ]

    first_person_count = (
        normalized_answer.count(" i ") +
        int(normalized_answer.startswith("i "))
    )

    authenticity_reasons = []

    if matched_phrases:
        authenticity_reasons.append(
            "It contains wording commonly found in generic "
            "templates."
        )

    if len(matched_corporate_terms) >= 2:
        authenticity_reasons.append(
            "It combines several corporate buzzwords without "
            "supporting them with a specific personal example."
        )

    if len(words) >= 80 and first_person_count == 0:
        authenticity_reasons.append(
            "It is lengthy but gives little first-person detail."
        )

    if len(words) >= 120 and not any(
        term in normalized_answer
        for term in personal_action_terms
    ):
        authenticity_reasons.append(
            "It is highly polished without clearly identifying "
            "your personal actions."
        )

    needs_authenticity_review = bool(
        authenticity_reasons
    )

    authenticity_message = (
        (
            "AI-like language warning: This answer sounds "
            "generic, heavily polished, or template-like. " +
            " ".join(authenticity_reasons) +
            " Rewrite it in your normal speaking voice and add "
            "specific, truthful details from your experience. "
            "This warning identifies writing patterns and does "
            "not prove that AI wrote the answer."
        )
        if needs_authenticity_review
        else (
            "Authenticity review: No strong template-like "
            "patterns were found. Continue checking that every "
            "detail is truthful and sounds like your own voice. "
            "This review cannot determine authorship."
        )
    )

    feedback = (
        "What worked: " +
        " ".join(strengths[:2]) +
        " Next improvement: " +
        " ".join(improvements[:2])
        if improvements
        else (
            "What worked: " +
            " ".join(strengths[:2]) +
            " Next improvement: Practice delivering the answer "
            "aloud while keeping every detail accurate."
        )
    )

    return {
        "feedback": feedback,
        "word_count": len(words),
        "has_personal_action": any(
            term in normalized_answer
            for term in personal_action_terms
        ),
        "has_result": any(
            term in normalized_answer
            for term in result_terms
        ),
        "needs_authenticity_review":
            needs_authenticity_review,
        "authenticity_reasons": authenticity_reasons,
        "authenticity_message": authenticity_message
    }


def build_mock_interview_report(
    answers: List[str],
    role: str,
    interview_type: str,
    flagged_attempts: List[dict]
):
    analyses = [
        analyze_mock_interview_answer(answer)
        for answer in answers
    ]

    total_answers = len(analyses)
    average_words = round(
        sum(
            item["word_count"]
            for item in analyses
        ) / total_answers
    )

    action_count = sum(
        int(item["has_personal_action"])
        for item in analyses
    )

    result_count = sum(
        int(item["has_result"])
        for item in analyses
    )

    review_count = len(flagged_attempts)

    action_score = (
        action_count / total_answers
    ) * 4

    result_score = (
        result_count / total_answers
    ) * 3

    if 20 <= average_words <= 180:
        detail_score = 2
    elif (
        12 <= average_words < 20 or
        181 <= average_words <= 220
    ):
        detail_score = 1
    else:
        detail_score = 0.5

    authenticity_score = max(
        0,
        1 - (review_count * 0.5)
    )

    overall_rating = round(
        action_score +
        result_score +
        detail_score +
        authenticity_score,
        1
    )

    if overall_rating >= 9:
        rating_label = "Interview-ready foundation"
    elif overall_rating >= 7:
        rating_label = "Strong foundation"
    elif overall_rating >= 5:
        rating_label = "Developing foundation"
    else:
        rating_label = "More practice recommended"

    priorities = []

    if action_count < total_answers:
        priorities.append(
            "state your personal action more clearly"
        )

    if result_count < total_answers:
        priorities.append(
            "finish examples with a result or lesson"
        )

    if average_words < 20:
        priorities.append(
            "add specific supporting details"
        )
    elif average_words > 180:
        priorities.append(
            "make answers more concise"
        )

    if review_count:
        priorities.append(
            "rewrite flagged answers in your natural voice"
        )

    if not priorities:
        priorities.append(
            "practice delivering the answers aloud"
        )

    flagged_details = []
    authentic_examples = (
        MOCK_INTERVIEW_AUTHENTIC_EXAMPLES[
            interview_type
        ]
    )

    for attempt_number, attempt in enumerate(
        flagged_attempts,
        start=1
    ):
        question_index = attempt["question_index"]
        analysis = analyze_mock_interview_answer(
            attempt["answer"]
        )

        reasons = " ".join(
            analysis["authenticity_reasons"]
        )

        flagged_details.append(
            "Question " +
            str(question_index + 1) +
            ", flagged attempt " +
            str(attempt_number) +
            ": AI-like or template-style response flagged\n"
            "Why it was flagged: " +
            reasons +
            "\nAuthentic response framework: " +
            authentic_examples[question_index] +
            "\nReplace every bracketed section with truthful "
            "details from your own experience."
        )

    authenticity_section = (
        "\n\n".join(flagged_details)
        if flagged_details
        else (
            "No answers showed strong AI-like or "
            "template-style patterns. Continue making sure the "
            "details are accurate and sound natural when spoken."
        )
    )

    priority_lines = "\n".join(
        (
            str(index + 1) +
            ". " +
            priority.capitalize() +
            "."
        )
        for index, priority in enumerate(
            priorities[:2]
        )
    )

    return (
        "Thank you. That concludes the mock interview.\n\n"
        "MOCK INTERVIEW REPORT\n"
        "Role: " +
        role +
        "\n\nOVERALL RATING\n" +
        str(overall_rating) +
        " / 10 - " +
        rating_label +
        "\nThe rating considers clear personal actions "
        "(4 points), results or lessons (3 points), useful "
        "answer detail (2 points), and authentic language "
        "(1 point). Flagged attempts affect the authenticity "
        "portion even when the answer is later revised."
        "\n\nSESSION OVERVIEW\n"
        "- Questions completed: " +
        str(total_answers) +
        " of 5\n"
        "- Average answer length: " +
        str(average_words) +
        " words\n"
        "- Answers with a clear personal action: " +
        str(action_count) +
        " of 5\n"
        "- Answers with a result or lesson: " +
        str(result_count) +
        " of 5\n"
        "- Answers flagged for authenticity review: " +
        str(review_count) +
        "\n\nPRACTICE PRIORITIES\n" +
        priority_lines +
        "\n\nAUTHENTICITY REVIEW\n" +
        authenticity_section +
        "\n\nIMPORTANT LIMITATIONS\n"
        "- This mock-interview rating does not predict real "
        "interview, hiring, or offer outcomes.\n"
        "- The rating is practice guidance, not a final grade or "
        "an employer's decision.\n"
        "- PathForge cannot verify whether every answer is complete "
        "or factually accurate.\n"
        "- Written practice cannot fully evaluate spoken delivery, "
        "tone, pacing, body language, or interviewer expectations.\n"
        "- The authenticity review identifies writing patterns only "
        "and cannot prove whether AI was used."
    )


@app.post("/learning-assistant/mock-interview")
def mock_interview(
    data: MockInterviewMessage,
    request: Request
):
    user = get_authenticated_user(request)

    role = data.role.strip()
    interview_type = data.interview_type.strip()
    answer = (data.answer or "").strip()

    if role == "" or len(role) > 80:
        raise HTTPException(
            status_code=400,
            detail="Enter a role using 1 to 80 characters."
        )

    if interview_type not in MOCK_INTERVIEW_QUESTIONS:
        raise HTTPException(
            status_code=400,
            detail="Choose a valid mock interview type."
        )

    questions = MOCK_INTERVIEW_QUESTIONS[interview_type]

    if (
        data.question_index < 0 or
        data.question_index >= len(questions)
    ):
        raise HTTPException(
            status_code=400,
            detail="The mock interview question is invalid."
        )

    current_question = questions[
        data.question_index
    ].format(role=role)
    if data.question_index == 0:
        conn = get_connection(DB_NAME)
        row = conn.execute(
            "SELECT career_stage FROM user_profiles WHERE user_id = ?",
            (user["id"],)
        ).fetchone()
        conn.close()
        stage = row[0] if row else ""
        stage_prompt = {
            "first_time": " You may use a genuine example from school, volunteering, caregiving, projects, clubs, or community activities.",
            "student": " You may use genuine examples from coursework, projects, campus activities, volunteering, or part-time work.",
            "recent_graduate": " You may connect recent education, internships, projects, or early work experience.",
            "career_changer": " Focus on genuine transferable skills from your previous work without claiming experience you have not gained.",
            "returning_worker": " You may draw from earlier work, recent learning, volunteering, caregiving, or refreshed skills.",
            "experienced": " Focus on a recent, relevant example that shows your scope, decisions, and truthful results."
        }.get(stage, "")
        current_question += stage_prompt

    if answer == "":
        if data.question_index != 0:
            raise HTTPException(
                status_code=400,
                detail="Enter an answer before continuing."
            )

        return {
            "question": current_question,
            "question_number": 1,
            "total_questions": len(questions),
            "feedback": "",
            "complete": False
        }

    if len(answer) > 2000:
        raise HTTPException(
            status_code=400,
            detail=(
                "Keep each mock interview answer under "
                "2,000 characters."
            )
        )

    safety_normalized = answer.lower().replace("-", " ")
    safety_reply = assistant_safety_reply(safety_normalized)
    if safety_reply:
        return {
            "question": current_question,
            "question_number": data.question_index + 1,
            "total_questions": len(questions),
            "feedback": safety_reply,
            "complete": False,
            "safety_notice": True,
            "safety_level": assistant_safety_level(safety_normalized)
        }

    previous_answers = data.answers or []
    flagged_attempts = [
        {
            "question_index": attempt.question_index,
            "answer": attempt.answer.strip()
        }
        for attempt in (
            data.flagged_attempts or []
        )
    ]

    if len(previous_answers) != data.question_index:
        raise HTTPException(
            status_code=400,
            detail="The mock interview answer history is invalid."
        )

    if any(
        not isinstance(saved_answer, str) or
        len(saved_answer.strip()) == 0 or
        len(saved_answer) > 2000
        for saved_answer in previous_answers
    ):
        raise HTTPException(
            status_code=400,
            detail="A saved mock interview answer is invalid."
        )

    if len(flagged_attempts) > 15:
        raise HTTPException(
            status_code=400,
            detail="Too many mock interview retry attempts."
        )

    if any(
        attempt["question_index"] < 0 or
        attempt["question_index"] >= len(questions) or
        attempt["answer"] == "" or
        len(attempt["answer"]) > 2000
        for attempt in flagged_attempts
    ):
        raise HTTPException(
            status_code=400,
            detail="A flagged interview attempt is invalid."
        )

    analysis = analyze_mock_interview_answer(answer)

    if analysis["needs_authenticity_review"]:
        return {
            "question": current_question,
            "question_number":
                data.question_index + 1,
            "total_questions": len(questions),
            "feedback": "",
            "authenticity_review": {
                "needs_review": True,
                "message":
                    analysis["authenticity_message"]
            },
            "retry_required": True,
            "complete": False,
            "interviewer_reply": (
                "Please try the same question again using "
                "specific, truthful details and your natural "
                "speaking voice."
            ),
            "summary": ""
        }

    complete_answers = previous_answers + [answer]
    next_index = data.question_index + 1
    is_complete = next_index >= len(questions)

    return {
        "question": (
            None
            if is_complete
            else questions[next_index].format(role=role)
        ),
        "question_number": (
            len(questions)
            if is_complete
            else next_index + 1
        ),
        "total_questions": len(questions),
        "feedback": analysis["feedback"],
        "authenticity_review": {
            "needs_review": False,
            "message":
                analysis["authenticity_message"]
        },
        "retry_required": False,
        "complete": is_complete,
        "interviewer_reply": (
            ""
            if is_complete
            else (
                MOCK_INTERVIEW_TRANSITIONS[
                    data.question_index %
                    len(MOCK_INTERVIEW_TRANSITIONS)
                ] +
                " Here is the next question."
            )
        ),
        "summary": (
            build_mock_interview_report(
                complete_answers,
                role,
                interview_type,
                flagged_attempts
            )
            if is_complete
            else ""
        )
    }


@app.post("/chat")
def chat(data: ChatMessage, request: Request):
    user = get_authenticated_user(request)

    message = data.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Enter a job-search question."
        )

    if len(message) > 500:
        raise HTTPException(
            status_code=400,
            detail="Keep job-search questions under 500 characters."
        )

    normalized = message.lower().replace("-", " ")
    safety_reply = assistant_safety_reply(normalized)
    if safety_reply:
        return {
            "reply": safety_reply,
            "job_results": [],
            "guidance_sources": [],
            "safety_notice": True,
            "safety_level": assistant_safety_level(normalized)
        }
    if not is_career_related_prompt(normalized):
        return {
            "reply": (
                "The Job Search AI Assistant is limited to finding jobs, comparing "
                "listings, applications, interviews, resumes, and other employment topics. "
                "I can’t help with that unrelated request. Ask me what kind of job or "
                "job-search task you want help with."
            ),
            "job_results": [],
            "guidance_sources": []
        }
    guidance = (
        get_connected_guidance(request)
        if user["role"] == "job_seeker"
        else None
    )

    if guidance and any(
        topic in normalized
        for topic in [
            "what should i do", "what next", "next step",
            "recommend", "priority", "where should i start"
        ]
    ):
        primary = guidance["primary_action"]
        reply = (
            f"A useful next step is: {primary['title']}. "
            f"{primary['reason']} Choose {primary['action_label']} to act on it. "
            + (
                f"For your selected career stage: {guidance['career_stage_guidance']} "
                if guidance.get("career_stage") else ""
            ) +
            "This is based on dates and activity saved in your PathForge "
            "account, not a prediction about hiring outcomes."
        )
    elif any(
        topic in normalized
        for topic in [
            "resume",
            "cover letter",
            "interview",
            "career plan",
            "career advice"
        ]
    ):
        if "interview" in normalized and guidance:
            interview_action = next(
                (action for action in guidance["actions"]
                 if action["type"] == "interview"),
                None
            )
            reply = (
                (interview_action["reason"] + " " if interview_action else "") +
                "Open Resources + AI Assistant for mock-interview practice. "
                + (
                    guidance["career_stage_guidance"] + " "
                    if guidance.get("career_stage") else ""
                ) +
                "PathForge does not store mock-interview answers as connected "
                "account history."
            )
        else:
            saved_context = (
                f" You currently have {len(guidance['recent_saved_jobs'])} "
                "recent saved jobs available to compare against."
                if guidance else ""
            )
            reply = (
                "Open Resources + AI Assistant for resume feedback, then use "
                "a selected job's requirements to make truthful, supported "
                "improvements." + saved_context + (
                    " " + guidance["career_stage_guidance"]
                    if guidance and guidance.get("career_stage") else ""
                ) + " Resume document contents "
                "are not silently stored or reused by connected guidance."
            )
    elif any(
        topic in normalized
        for topic in [
            "save",
            "saved job",
            "bookmark"
        ]
    ):
        reply = (
            "Open a listing on the Jobs page and choose Save Job. "
            "You can review or remove saved opportunities from "
            "Saved Jobs in the main menu."
        )
    elif any(
        topic in normalized
        for topic in [
            "application",
            "apply",
            "employer website"
        ]
    ):
        reply = (
            "PathForge listings show their application method. "
            "Some applications are completed through PathForge; "
            "others send you to the employer's website. Use the "
            "Application Tracker to organize applications you start."
        )
    elif any(
        topic in normalized
        for topic in [
            "filter",
            "location",
            "remote",
            "schedule",
            "experience"
        ]
    ):
        reply = (
            "Use the filters on the Jobs page to narrow current "
            "PathForge listings by keyword, location, category, "
            "employment type, remote option, experience, employer, "
            "or application method."
        )
    else:
        part_time_only = (
            "part time" in normalized or
            "part-time" in message.lower()
        )

        conn = get_connection(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT id, title, company, location, schedule
            FROM jobs
            WHERE """ + PUBLIC_JOB_ELIGIBILITY_SQL
        parameters = []

        if part_time_only:
            query += " AND lower(schedule) LIKE ?"
            parameters.append("%part%time%")

        query += " ORDER BY id DESC LIMIT 4"
        cursor.execute(query, parameters)
        jobs = [dict(job) for job in cursor.fetchall()]
        conn.close()

        if not jobs:
            reply = (
                "I could not find an active " +
                ("part-time " if part_time_only else "") +
                "listing in PathForge right now. Try the Jobs page "
                "again later or broaden its filters."
            )
        else:
            reply = (
                "Here are current " +
                ("part-time " if part_time_only else "") +
                "PathForge listings. Open any job below to go directly "
                "to its full job card, details, deadline, and application method."
            )

    return {
        "reply": reply,
        "job_results": [
            {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "href": f"jobs.html#job-{job['id']}"
            }
            for job in jobs
        ] if 'jobs' in locals() and jobs else [],
        "guidance_sources": (
            [item["label"] for item in guidance["evidence"]]
            if guidance else []
        )
    }


# Serve the browser application from the API process without exposing the
# project directory, database, environment file, backups, or source configs.
PUBLIC_FRONTEND_FILES = {
    "account-security.html", "admin-moderation.html", "alerts.html",
    "analytics.html", "applications.html", "company.html", "dashboard.html",
    "employer-access.html", "employer.html", "index.html", "jobs.html",
    "learning-center.html", "login.html", "messages.html", "offline.html",
    "profile.html", "register.html", "resume.html", "saved-jobs.html",
    "search-history.html", "manifest.webmanifest", "offline.js",
    "pathforge-core.js", "script.js", "service-worker.js", "style.css",
    "us-places.json",
}
PUBLIC_ASSET_SUFFIXES = {".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif"}
FRONTEND_ROOT = Path(__file__).resolve().parent


@app.get("/app", include_in_schema=False)
def open_browser_app():
    return RedirectResponse(url="/index.html", status_code=307)


@app.get("/{frontend_path:path}", include_in_schema=False)
def get_frontend_file(frontend_path: str):
    normalized = Path(frontend_path).as_posix().lstrip("/")
    is_public_asset = (
        normalized.startswith("assets/")
        and Path(normalized).suffix.lower() in PUBLIC_ASSET_SUFFIXES
    )
    if normalized not in PUBLIC_FRONTEND_FILES and not is_public_asset:
        raise HTTPException(status_code=404, detail="Not found.")
    candidate = (FRONTEND_ROOT / normalized).resolve()
    if FRONTEND_ROOT not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(candidate)
