"""Public job-discovery routes and shared public-listing eligibility rules."""

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Callable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import auth as auth_service
from database import get_connection
from job_discovery import compact_job, discover_jobs


# Keep discovery and new-bookmark eligibility aligned so hidden, expired, or
# private tracker records cannot be accessed merely by guessing an identifier.
PUBLIC_JOB_ELIGIBILITY_SQL = """
    status = 'active'
    AND owner_user_id IS NULL
    AND (
        application_method = 'pathforge'
        OR verification_status = 'verified'
    )
    AND (expires_at IS NULL OR date(expires_at) >= date('now'))
    AND (
        application_deadline IS NULL
        OR date(application_deadline) >= date('now')
    )
"""

JOB_REPORT_REASONS = {
    "suspected_scam", "misleading_information", "expired_or_broken_link",
    "discriminatory_content", "duplicate_listing", "other",
}


class JobReportInput(BaseModel):
    reason: str
    details: str | None = None


class AdminJobReportUpdate(BaseModel):
    status: str
    moderation_note: str | None = None


def create_job_router(database_path: Callable[[], str], enrich_job: Callable):
    """Build public job routes around late-bound app dependencies."""
    router = APIRouter(tags=["jobs"])
    discovery_cache = {"signature": None, "jobs": None, "categories": None}
    discovery_cache_lock = RLock()

    def catalog_signature(path):
        """Invalidate cached discovery data after either SQLite file changes."""
        database_file = Path(path)
        signature = []
        for candidate in (database_file, Path(str(database_file) + "-wal")):
            try:
                stat = candidate.stat()
                signature.append((stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                signature.append(None)
        return tuple(signature)

    def discovery_catalog(connection, path):
        signature = catalog_signature(path)
        with discovery_cache_lock:
            if discovery_cache["signature"] == signature:
                return discovery_cache["jobs"], discovery_cache["categories"]
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE {PUBLIC_JOB_ELIGIBILITY_SQL}"
            ).fetchall()
            jobs = [enrich_job(dict(row)) for row in rows]
            categories = sorted({job.get("category") for job in jobs if job.get("category")})
            discovery_cache.update(
                signature=signature,
                jobs=jobs,
                categories=categories,
            )
            return jobs, categories

    @router.get("/jobs")
    def get_jobs():
        connection = get_connection(database_path())
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                f"""
                SELECT * FROM jobs
                WHERE {PUBLIC_JOB_ELIGIBILITY_SQL}
                ORDER BY id DESC
                """
            ).fetchall()
            return [enrich_job(dict(row)) for row in rows]
        finally:
            connection.close()

    @router.get("/jobs/catalog")
    def get_job_catalog(limit: int = 250, offset: int = 0):
        """Return lightweight cards while keeping complete text in job details."""
        if limit < 1 or limit > 500 or offset < 0:
            raise HTTPException(
                status_code=400,
                detail="Catalog limit must be 1–500 and offset cannot be negative.",
            )
        connection = get_connection(database_path())
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                f"""
                SELECT * FROM jobs
                WHERE {PUBLIC_JOB_ELIGIBILITY_SQL}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            catalog = []
            for row in rows:
                job = enrich_job(dict(row))
                for field in ("description", "requirements", "preferred_qualifications"):
                    value = str(job.get(field) or "")
                    if len(value) > 240:
                        job[field] = value[:240].rsplit(" ", 1)[0].rstrip() + "…"
                        job["details_truncated"] = True
                catalog.append(job)
            return catalog
        finally:
            connection.close()

    @router.get("/jobs/search")
    def search_jobs(
        query: str = Query("", max_length=200),
        location: str = Query("", max_length=200),
        location_scope: str = Query("us", pattern="^(us|all)$"),
        location_mode: str = Query("nearby", pattern="^(nearby|exact)$"),
        category: str = Query("all", max_length=100),
        employment_type: str = Query("all", pattern="^(all|full-time|part-time)$"),
        remote: str = Query("all", pattern="^(all|remote|hybrid|onsite)$"),
        remote_eligibility: str = Query("all", pattern="^(all|us|anywhere)$"),
        experience: str = Query("all", pattern="^(all|entry-level|experienced)$"),
        age_fit: str = Query("all", pattern="^(all|age-14|age-15|age-16-17|age-18-plus)$"),
        date_posted: str = Query("all", pattern="^(all|1|3|7|14|30|60|90)$"),
        listing_quality: str = Query("all", pattern="^(all|pay|deadline|complete)$"),
        minimum_pay: float = Query(0, ge=0, le=10_000_000),
        exclusions: str = Query("", max_length=100),
        exclude_terms: str = Query("", max_length=200),
        sort: str = Query("recommended", pattern="^(recommended|newest|pay-high|verified)$"),
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        """Return a filtered result page without sending the full catalog."""
        path = database_path()
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            jobs, categories = discovery_catalog(connection, path)
            results = discover_jobs(
                jobs,
                query=query,
                location=location,
                location_scope=location_scope,
                location_mode=location_mode,
                category=category,
                employment_type=employment_type,
                remote=remote,
                remote_eligibility=remote_eligibility,
                experience=experience,
                age_fit=age_fit,
                date_posted=date_posted,
                listing_quality=listing_quality,
                minimum_pay=minimum_pay,
                exclusions=exclusions,
                exclude_terms=exclude_terms,
                sort=sort,
            )
            page = [compact_job(job) for job in results[offset:offset + limit]]
            return {
                "jobs": page,
                "total": len(results),
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(page) < len(results),
                "categories": categories,
            }
        finally:
            connection.close()

    @router.get("/jobs/{job_id}")
    def get_public_job(job_id: int):
        connection = get_connection(database_path())
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                f"""SELECT * FROM jobs
                    WHERE id = ? AND {PUBLIC_JOB_ELIGIBILITY_SQL}""",
                (job_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job listing not found.")
            return enrich_job(dict(row))
        finally:
            connection.close()

    @router.get("/jobs/{job_id}/history")
    def get_public_job_history(job_id: int):
        """Expose a concise, user-safe record of material listing changes."""
        connection = get_connection(database_path())
        connection.row_factory = sqlite3.Row
        try:
            if not connection.execute(
                f"SELECT id FROM jobs WHERE id = ? AND {PUBLIC_JOB_ELIGIBILITY_SQL}",
                (job_id,),
            ).fetchone():
                raise HTTPException(status_code=404, detail="Job listing not found.")
            safe_fields = (
                "title", "company", "location", "pay", "schedule", "experience",
                "application_method", "application_url", "application_deadline",
                "status", "source_url", "expires_at", "employment_type",
                "is_remote", "salary_min", "salary_max", "salary_period",
                "verification_status", "link_status",
            )
            placeholders = ", ".join("?" for _ in safe_fields)
            rows = connection.execute(
                f"""SELECT field_name, old_value, new_value, change_source, changed_at
                    FROM job_change_history
                    WHERE job_id = ? AND field_name IN ({placeholders})
                    ORDER BY changed_at DESC, id DESC LIMIT 100""",
                (job_id, *safe_fields),
            ).fetchall()
            return {"job_id": job_id, "changes": [dict(row) for row in rows]}
        finally:
            connection.close()

    @router.get("/companies/{company_name}")
    def get_company_research(company_name: str):
        normalized_name = company_name.strip()
        if not normalized_name or len(normalized_name) > 120:
            raise HTTPException(status_code=400, detail="Invalid company name.")
        connection = get_connection(database_path())
        connection.row_factory = sqlite3.Row
        try:
            jobs = connection.execute(
                f"""SELECT * FROM jobs
                   WHERE company = ? COLLATE NOCASE
                     AND {PUBLIC_JOB_ELIGIBILITY_SQL}
                   ORDER BY COALESCE(posted_at, created_at) DESC, id DESC""",
                (normalized_name,),
            ).fetchall()
            profile = connection.execute(
                """SELECT company_name, company_description, website, logo_url,
                          brand_color, hiring_preferences, updated_at
                   FROM company_profiles
                   WHERE company_name = ? COLLATE NOCASE
                   ORDER BY updated_at DESC LIMIT 1""",
                (normalized_name,),
            ).fetchone()
            if not jobs and not profile:
                raise HTTPException(status_code=404, detail="Company not found.")
            company = profile["company_name"] if profile else jobs[0]["company"]
            active_jobs = [enrich_job(dict(job)) for job in jobs]
            sources = []
            seen_sources = set()
            for job in active_jobs:
                source_key = (job.get("source") or "PathForge").lower()
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
                sources.append({
                    "name": job.get("source") or "PathForge",
                    "url": job.get("source_url") or job.get("application_url"),
                    "last_verified_at": job.get("last_verified_at"),
                    "verification_status": job.get("verification_status"),
                })
            return {
                "company": {
                    "name": company,
                    "description": profile["company_description"] if profile else None,
                    "website": profile["website"] if profile else None,
                    "logo_url": profile["logo_url"] if profile else None,
                    "brand_color": profile["brand_color"] if profile else None,
                    "hiring_information": profile["hiring_preferences"] if profile else None,
                    "profile_updated_at": profile["updated_at"] if profile else None,
                    "profile_source": "employer_provided" if profile else "not_provided",
                },
                "summary": {
                    "active_job_count": len(active_jobs),
                    "remote_job_count": sum(job.get("is_remote") == 1 for job in active_jobs),
                    "published_salary_count": sum(
                        job.get("salary_min") is not None or job.get("salary_max") is not None
                        for job in active_jobs
                    ),
                    "locations": sorted({job.get("location") for job in active_jobs if job.get("location")}),
                    "job_types": sorted({job.get("employment_type") for job in active_jobs if job.get("employment_type")}),
                },
                "sources": sources,
                "active_jobs": active_jobs,
            }
        finally:
            connection.close()

    @router.get("/job-reports/mine")
    def get_my_job_reports(request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        if user["role"] != "job_seeker":
            raise HTTPException(status_code=403, detail="Job-seeker access is required.")
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """SELECT job_id, reason, status, created_at FROM job_reports
                   WHERE user_id = ? ORDER BY created_at DESC""",
                (user["id"],),
            ).fetchall()
            return {"reports": [dict(row) for row in rows]}
        finally:
            connection.close()

    @router.post("/jobs/{job_id}/report", status_code=201)
    def report_job_listing(job_id: int, report: JobReportInput, request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        if user["role"] != "job_seeker":
            raise HTTPException(status_code=403, detail="Job-seeker access is required.")
        reason = report.reason.strip().lower()
        details = (report.details or "").strip()
        if reason not in JOB_REPORT_REASONS:
            raise HTTPException(status_code=400, detail="Choose a valid report reason.")
        if len(details) > 1000:
            raise HTTPException(status_code=400, detail="Report details must be 1,000 characters or fewer.")
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            if not connection.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Job listing not found.")
            try:
                cursor = connection.execute(
                    "INSERT INTO job_reports (user_id, job_id, reason, details) VALUES (?, ?, ?, ?)",
                    (user["id"], job_id, reason, details or None),
                )
                report_id = cursor.lastrowid
                connection.commit()
            except sqlite3.IntegrityError as error:
                raise HTTPException(status_code=409, detail="You already reported this listing.") from error
            saved = connection.execute(
                """SELECT id, job_id, reason, status, created_at
                   FROM job_reports WHERE id = ?""",
                (report_id,),
            ).fetchone()
            return {"message": "Report submitted for review.", "report": dict(saved)}
        finally:
            connection.close()

    @router.get("/admin/job-reports")
    def get_admin_job_reports(request: Request, status: str = "all"):
        path = database_path()
        auth_service.require_role(request, path, "admin")
        normalized = status.strip().lower()
        if normalized not in {"all", "submitted", "reviewed", "resolved"}:
            raise HTTPException(status_code=400, detail="Invalid report status.")
        clause = "" if normalized == "all" else "WHERE reports.status = ?"
        parameters = [] if normalized == "all" else [normalized]
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                f"""SELECT reports.id, reports.job_id, reports.reason, reports.details,
                            reports.status, reports.moderation_note, reports.created_at,
                            reports.updated_at, reports.reviewed_at, reports.resolved_at,
                            reporter.username AS reporter_username,
                            reporter.email AS reporter_email,
                            moderator.username AS moderator_username,
                            jobs.title AS job_title, jobs.company AS job_company,
                            jobs.location AS job_location, jobs.status AS job_status,
                            jobs.application_method, jobs.application_url,
                            jobs.source_url, jobs.verification_status, jobs.link_status
                     FROM job_reports AS reports
                     JOIN users AS reporter ON reporter.id = reports.user_id
                     JOIN jobs ON jobs.id = reports.job_id
                     LEFT JOIN users AS moderator ON moderator.id = reports.moderator_user_id
                     {clause}
                     ORDER BY CASE reports.status WHEN 'submitted' THEN 0
                              WHEN 'reviewed' THEN 1 ELSE 2 END,
                              reports.created_at DESC""",
                parameters,
            ).fetchall()
            count_rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM job_reports GROUP BY status"
            ).fetchall()
            counts = {"submitted": 0, "reviewed": 0, "resolved": 0}
            for row in count_rows:
                counts[row["status"]] = row["total"]
            counts["all"] = sum(counts.values())
            return {"reports": [dict(row) for row in rows], "counts": counts}
        finally:
            connection.close()

    @router.get("/admin/operations")
    def get_admin_operations(request: Request):
        """Summarize catalog freshness, source health, and actionable issues."""
        path = database_path()
        auth_service.require_role(request, path, "admin")
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            summary = dict(connection.execute(
                """SELECT
                    SUM(CASE WHEN status = 'active' AND owner_user_id IS NULL THEN 1 ELSE 0 END) AS active_jobs,
                    SUM(CASE WHEN link_status = 'unavailable' AND owner_user_id IS NULL THEN 1 ELSE 0 END) AS broken_links,
                    SUM(CASE WHEN owner_user_id IS NULL AND (last_verified_at IS NULL OR datetime(last_verified_at) < datetime('now', '-7 days')) THEN 1 ELSE 0 END) AS stale_jobs,
                    SUM(CASE WHEN status = 'active' AND owner_user_id IS NULL AND COALESCE(application_deadline, expires_at) IS NOT NULL AND date(COALESCE(application_deadline, expires_at)) BETWEEN date('now') AND date('now', '+7 days') THEN 1 ELSE 0 END) AS expiring_soon
                    FROM jobs"""
            ).fetchone())
            summary["pending_reports"] = connection.execute(
                "SELECT COUNT(*) FROM job_reports WHERE status = 'submitted'"
            ).fetchone()[0]
            summary["changes_24h"] = connection.execute(
                "SELECT COUNT(*) FROM job_change_history WHERE datetime(changed_at) >= datetime('now', '-1 day')"
            ).fetchone()[0]
            sources = connection.execute(
                """SELECT COALESCE(NULLIF(source, ''), 'PathForge employers') AS source,
                    COUNT(*) AS total_jobs,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_jobs,
                    SUM(CASE WHEN link_status = 'unavailable' THEN 1 ELSE 0 END) AS broken_links,
                    SUM(CASE WHEN last_verified_at IS NULL OR datetime(last_verified_at) < datetime('now', '-7 days') THEN 1 ELSE 0 END) AS stale_jobs,
                    MAX(last_verified_at) AS last_verified_at
                    FROM jobs WHERE owner_user_id IS NULL
                    GROUP BY COALESCE(NULLIF(source, ''), 'PathForge employers')
                    ORDER BY broken_links DESC, stale_jobs DESC, total_jobs DESC"""
            ).fetchall()
            issues = connection.execute(
                """SELECT id, title, company, source, status, link_status,
                    last_verified_at, application_deadline, expires_at
                    FROM jobs
                    WHERE owner_user_id IS NULL AND (
                        link_status = 'unavailable'
                        OR last_verified_at IS NULL
                        OR datetime(last_verified_at) < datetime('now', '-7 days')
                        OR (status = 'active' AND date(COALESCE(application_deadline, expires_at)) BETWEEN date('now') AND date('now', '+7 days'))
                    )
                    ORDER BY CASE WHEN link_status = 'unavailable' THEN 0 ELSE 1 END,
                             COALESCE(last_verified_at, '') ASC LIMIT 50"""
            ).fetchall()
            return {
                "summary": {key: value or 0 for key, value in summary.items()},
                "sources": [dict(row) for row in sources],
                "issues": [dict(row) for row in issues],
            }
        finally:
            connection.close()

    @router.patch("/admin/job-reports/{report_id}")
    def update_admin_job_report(report_id: int, update: AdminJobReportUpdate, request: Request):
        path = database_path()
        admin = auth_service.require_role(request, path, "admin")
        status = update.status.strip().lower()
        note = (update.moderation_note or "").strip()
        if status not in {"submitted", "reviewed", "resolved"}:
            raise HTTPException(status_code=400, detail="Invalid report status.")
        if len(note) > 1000:
            raise HTTPException(status_code=400, detail="Moderation notes must be 1,000 characters or fewer.")
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            if not connection.execute("SELECT id FROM job_reports WHERE id = ?", (report_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Report not found.")
            connection.execute(
                """UPDATE job_reports SET status = ?, moderation_note = ?, moderator_user_id = ?,
                       reviewed_at = CASE WHEN ? IN ('reviewed', 'resolved')
                           THEN COALESCE(reviewed_at, CURRENT_TIMESTAMP) ELSE NULL END,
                       resolved_at = CASE WHEN ? = 'resolved'
                           THEN COALESCE(resolved_at, CURRENT_TIMESTAMP) ELSE NULL END,
                       updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (status, note or None, admin["id"], status, status, report_id),
            )
            connection.commit()
            row = connection.execute(
                """SELECT id, job_id, status, moderation_note,
                          reviewed_at, resolved_at, updated_at
                   FROM job_reports WHERE id = ?""",
                (report_id,),
            ).fetchone()
            return {"message": "Report moderation status updated.", "report": dict(row)}
        finally:
            connection.close()

    return router
