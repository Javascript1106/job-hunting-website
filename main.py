from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import date, datetime, timezone
from typing import Optional, List
import hashlib
import hmac
import os
import sqlite3


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "jobs.db"

def hash_password(password: str):
    salt = os.urandom(16).hex()
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return f"{salt}:{password_hash}"


def verify_password(plain_password: str, stored_password: str):
    try:
        salt, saved_hash = stored_password.split(":", 1)
    except ValueError:
        return False

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return hmac.compare_digest(password_hash, saved_hash)

def hash_access_code(code: str):
    normalized_code = code.strip().upper()

    return hashlib.sha256(
        normalized_code.encode("utf-8")
    ).hexdigest()

def get_authenticated_user(request: Request):
    user_id = request.cookies.get("user_id")

    if not user_id or not user_id.isdigit():
        raise HTTPException(
            status_code=401,
            detail="Not logged in."
        )

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, email, role
        FROM users
        WHERE id = ?
        """,
        (int(user_id),)
    )

    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid session."
        )

    return dict(user)


def require_employer(request: Request):
    user = get_authenticated_user(request)

    if user["role"] != "employer":
        raise HTTPException(
            status_code=403,
            detail="Employer access is required."
        )

    return user

class ChatMessage(BaseModel):
    message: str

class LearningAssistantMessage(BaseModel):
    message: str

class MockInterviewFlaggedAttempt(BaseModel):
    question_index: int
    answer: str

class MockInterviewMessage(BaseModel):
    role: str
    interview_type: str
    question_index: int
    answer: Optional[str] = None
    answers: Optional[List[str]] = None
    flagged_attempts: Optional[
        List[MockInterviewFlaggedAttempt]
    ] = None

class Job(BaseModel):
    title: str
    company: str
    location: str
    pay: str
    description: str
    schedule: str
    experience: str
    category: str
    application_method: str = "pathforge"
    application_url: Optional[str] = None
    status: str = "active"
    application_deadline: Optional[str] = None


class JobStatusUpdate(BaseModel):
    status: str


class RegisterUser(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginUser(BaseModel):
    identifier: str
    password: str

class EmployerCodeRedemption(BaseModel):
    code: str

class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    career_interests: Optional[str] = None
    preferred_industries: Optional[str] = None
    skills: Optional[str] = None
    experience_level: Optional[str] = None
    preferred_location: Optional[str] = None
    schedule_preference: Optional[str] = None
    work_preference: Optional[str] = None
    desired_pay: Optional[str] = None
    career_goals: Optional[str] = None

class ApplicationCreate(BaseModel):
    job_id: int
    application_method: str
    status: str = "Interested"
    applied_at: Optional[str] = None
    interview_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[str] = None
    applied_at: Optional[str] = None
    interview_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None

class ApplicationQuestionInput(BaseModel):
    question_text: str
    field_type: str = "short_text"
    is_required: bool = True


class ApplicationFormUpdate(BaseModel):
    questions: List[ApplicationQuestionInput]


class ApplicationAnswerInput(BaseModel):
    question_id: int
    answer_text: Optional[str] = None


class InternalApplicationSubmit(BaseModel):
    answers: List[ApplicationAnswerInput]

class EmployerApplicationUpdate(BaseModel):
    status: Optional[str] = None
    interview_date: Optional[str] = None
    interview_time: Optional[str] = None
    interview_format: Optional[str] = None
    interview_location: Optional[str] = None
    interview_details: Optional[str] = None
    employer_notes: Optional[str] = None

class LearningProgressUpdate(BaseModel):
    status: str

class CompanyProfileUpdate(BaseModel):
    company_name: str
    company_description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    hiring_preferences: Optional[str] = None

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

@app.get("/")
def home():
    return {"message": "Job hunting website backend is running"}


@app.get("/jobs")
def get_jobs():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM jobs
        WHERE status = 'active'
          AND (
              application_method = 'pathforge'
              OR verification_status = 'verified'
          )
          AND (
              expires_at IS NULL
              OR date(expires_at) >= date('now')
          )
          AND (
              application_deadline IS NULL
              OR date(application_deadline) >= date('now')
          )
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()
    jobs = [dict(row) for row in rows]

    conn.close()

    return jobs


@app.get("/employer/company-profile")
def get_employer_company_profile(request: Request):
    employer = require_employer(request)

    conn = sqlite3.connect(DB_NAME)
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


@app.get("/employer/statistics")
def get_employer_statistics(request: Request):
    employer = require_employer(request)

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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
    cleaned_schedule = job.schedule.strip()
    cleaned_experience = job.experience.strip()
    cleaned_category = job.category.strip()
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

    conn = sqlite3.connect(DB_NAME)
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
            ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        (
            cleaned_title,
            cleaned_company,
            cleaned_location,
            cleaned_pay,
            cleaned_description,
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
    cleaned_schedule = job.schedule.strip()
    cleaned_experience = job.experience.strip()
    cleaned_category = job.category.strip()
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

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE jobs
        SET
            title = ?,
            company = ?,
            location = ?,
            pay = ?,
            description = ?,
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

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

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

    conn = sqlite3.connect(DB_NAME)
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

@app.get("/saved-jobs")
def get_saved_jobs(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            jobs.id,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.pay,
            jobs.description,
            jobs.schedule,
            jobs.experience,
            jobs.category,
            jobs.application_deadline,
            saved_jobs.saved_at
        FROM saved_jobs
        JOIN jobs
            ON jobs.id = saved_jobs.job_id
        WHERE saved_jobs.user_id = ?
        ORDER BY saved_jobs.saved_at DESC
        """,
        (user["id"],)
    )

    saved_jobs = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "saved_jobs": saved_jobs
    }


@app.post("/saved-jobs/{job_id}")
def save_job(job_id: int, request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
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

    try:
        cursor.execute(
            """
            INSERT INTO saved_jobs (
                user_id,
                job_id
            )
            VALUES (?, ?)
            """,
            (
                user["id"],
                job_id
            )
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return {
            "message": "This job is already saved.",
            "already_saved": True
        }

    conn.close()

    return {
        "message": "Job saved successfully.",
        "already_saved": False
    }

@app.get("/applications")
def get_applications(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
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
            updated_follow_up_date,
            updated_notes,
            application_id,
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    return {
        "message": "Application updated successfully."
    }


@app.delete("/applications/{application_id}")
def delete_application(
    application_id: int,
    request: Request
):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.id,
            applications.application_method,
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

@app.delete("/saved-jobs/{job_id}")
def remove_saved_job(job_id: int, request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM saved_jobs
        WHERE user_id = ?
          AND job_id = ?
        """,
        (
            user["id"],
            job_id
        )
    )

    removed = cursor.rowcount
    conn.commit()
    conn.close()

    if removed == 0:
        raise HTTPException(
            status_code=404,
            detail="Saved job not found."
        )

    return {
        "message": "Job removed from saved jobs."
    }




@app.post("/register")
def register_user(user: RegisterUser):
    password_bytes = len(user.password.encode("utf-8"))

    if len(user.password) < 8 or password_bytes > 72:
        raise HTTPException(
            status_code=400,
            detail="Password must be between 8 and 72 bytes long."
        )

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email = ? OR username = ?",
        (user.email, user.username)
    )
    existing_user = cursor.fetchone()

    if existing_user:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Username or email already exists."
        )

    hashed_password = hash_password(user.password)

    cursor.execute(
    """
    INSERT INTO users (
        username,
        email,
        password,
        role
    )
    VALUES (?, ?, ?, 'job_seeker')
    """,
    (
        user.username,
        user.email,
        hashed_password
    )
    )

    conn.commit()
    conn.close()

    return {"message": "Account created successfully."}


@app.post("/login")
def login_user(user: LoginUser, response: Response):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
    """
    SELECT id, username, email, password, role
    FROM users
    WHERE email = ? OR username = ?
    """,
    (user.identifier, user.identifier)
    )

    db_user = cursor.fetchone()

    conn.close()

    if not db_user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )

    user_id, username, email, hashed_password, role = db_user

    if not verify_password(user.password, hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )

    response.set_cookie(
        key="user_id",
        value=str(user_id),
        httponly=True,
        samesite="lax"
    )

    return {
        "message": "Login successful.",
        "user": {
            "id": user_id,
            "username": username,
            "email": email,
            "role": role
        }
    }


@app.post("/logout")
def logout_user(response: Response):
    response.delete_cookie("user_id")
    return {"message": "Logged out successfully."}


@app.get("/me")
def get_current_user(request: Request):
    return get_authenticated_user(request)


    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in.")

    conn = sqlite3.connect(DB_NAME)
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

@app.get("/profile")
def get_user_profile(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            display_name,
            career_interests,
            preferred_industries,
            skills,
            experience_level,
            preferred_location,
            schedule_preference,
            work_preference,
            desired_pay,
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
                "career_interests": "",
                "preferred_industries": "",
                "skills": "",
                "experience_level": "",
                "preferred_location": "",
                "schedule_preference": "",
                "work_preference": "",
                "desired_pay": "",
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

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO user_profiles (
            user_id,
            display_name,
            career_interests,
            preferred_industries,
            skills,
            experience_level,
            preferred_location,
            schedule_preference,
            work_preference,
            desired_pay,
            career_goals
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(user_id) DO UPDATE SET
            display_name = excluded.display_name,
            career_interests = excluded.career_interests,
            preferred_industries = excluded.preferred_industries,
            skills = excluded.skills,
            experience_level = excluded.experience_level,
            preferred_location = excluded.preferred_location,
            schedule_preference = excluded.schedule_preference,
            work_preference = excluded.work_preference,
            desired_pay = excluded.desired_pay,
            career_goals = excluded.career_goals,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user["id"],
            profile.display_name,
            profile.career_interests,
            profile.preferred_industries,
            profile.skills,
            profile.experience_level,
            profile.preferred_location,
            profile.schedule_preference,
            profile.work_preference,
            profile.desired_pay,
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

    conn = sqlite3.connect(DB_NAME)
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


@app.get("/learning-progress")
def get_learning_progress(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
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


@app.put("/learning-progress/{lesson_id}")
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

    conn = sqlite3.connect(DB_NAME)
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

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

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
            "follow_ups": follow_ups_count
        }
    }


@app.post("/learning-assistant")
def learning_assistant(
    data: LearningAssistantMessage,
    request: Request
):
    get_authenticated_user(request)

    message = data.message.strip()

    if message == "":
        raise HTTPException(
            status_code=400,
            detail="Please enter a learning question."
        )

    if len(message) > 800:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please keep your learning question "
                "under 800 characters."
            )
        )

    normalized = (
    message
    .lower()
    .replace("-", " ")
    )

    reply = (
        "I can help with career exploration, job-search "
        "organization, interview preparation, workplace "
        "readiness, and resume education. Tell me what "
        "you are working on and where you feel uncertain."
    )

    follow_ups = [
        "Where should I begin in the Learning Center?",
        "How can I prepare for my first job?",
        "Which interview lesson should I review?"
    ]

    specific_answers = {
    "how do i identify my strongest skills?": (
        "List three tasks you perform confidently and three "
        "situations where other people rely on you. For each "
        "one, identify the skill involved and the evidence that "
        "shows you used it successfully. Look for skills that "
        "appear more than once."
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
        "where should i begin in the learning center?": (
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
        )
    })

    dishonest_terms = [
        "make up",
        "fabricate",
        "lie",
        "fake experience",
        "invent experience"
    ]

    if normalized in specific_answers: reply, follow_ups = specific_answers[normalized], []

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
            "tailor"
        ]
    ):
        reply = (
            "I can teach resume principles, but the Learning "
            "Center does not generate, upload, parse, rewrite, "
            "or automatically tailor resumes. Identify the "
            "opportunity's main requirements and compare them "
            "with truthful evidence from your skills, experience, "
            "education, projects, and volunteer work."
        )

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

    authenticity_reminder = (
        "Review and personalize this guidance. Keep every "
        "application and interview answer truthful."
    )

    return {
        "reply": reply,
        "follow_up_questions": follow_ups,
        "authenticity_reminder": authenticity_reminder
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
        "\n\nIMPORTANT NOTE\n"
        "The authenticity review identifies writing "
        "patterns only and cannot prove whether AI was used."
    )


@app.post("/learning-assistant/mock-interview")
def mock_interview(
    data: MockInterviewMessage,
    request: Request
):
    get_authenticated_user(request)

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
def chat(data: ChatMessage):
    message = data.message.lower()

    if "resume" in message:
        reply = "I can help improve your resume by matching your skills to the job."
    elif "interview" in message:
        reply = "I can help you practice interview answers and prepare strong responses."
    elif "job" in message:
        reply = "I can help you find jobs based on location, schedule, experience, and age requirements."
    else:
        reply = "I can help with job searching, resumes, applications, interviews, and career planning."

    return {"reply": reply}
