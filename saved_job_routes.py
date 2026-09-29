"""Authenticated bookmark routes for PathForge job seekers."""

import sqlite3
from typing import Callable

from fastapi import APIRouter, HTTPException, Request

import auth as auth_service
from database import get_connection
from job_routes import PUBLIC_JOB_ELIGIBILITY_SQL


def create_saved_job_router(database_path: Callable[[], str]):
    """Build bookmark routes with a late-bound database path for test isolation."""
    router = APIRouter(prefix="/saved-jobs", tags=["saved jobs"])

    @router.get("")
    def get_saved_jobs(request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        connection = get_connection(path)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT jobs.id, jobs.title, jobs.company, jobs.location,
                       jobs.pay, jobs.description, jobs.schedule,
                       jobs.experience, jobs.category,
                       jobs.application_deadline, saved_jobs.saved_at
                FROM saved_jobs
                JOIN jobs ON jobs.id = saved_jobs.job_id
                WHERE saved_jobs.user_id = ?
                ORDER BY saved_jobs.saved_at DESC
                """,
                (user["id"],),
            ).fetchall()
            return {"saved_jobs": [dict(row) for row in rows]}
        finally:
            connection.close()

    @router.post("/{job_id}")
    def save_job(job_id: int, request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        connection = get_connection(path)
        try:
            job = connection.execute(
                f"SELECT id FROM jobs WHERE id = ? AND {PUBLIC_JOB_ELIGIBILITY_SQL}",
                (job_id,),
            ).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Job not found.")
            try:
                connection.execute(
                    "INSERT INTO saved_jobs (user_id, job_id) VALUES (?, ?)",
                    (user["id"], job_id),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                return {
                    "message": "This job is already saved.",
                    "already_saved": True,
                }
        finally:
            connection.close()
        return {"message": "Job saved successfully.", "already_saved": False}

    @router.delete("/{job_id}")
    def remove_saved_job(job_id: int, request: Request):
        path = database_path()
        user = auth_service.get_authenticated_user(request, path)
        connection = get_connection(path)
        try:
            cursor = connection.execute(
                "DELETE FROM saved_jobs WHERE user_id = ? AND job_id = ?",
                (user["id"], job_id),
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Saved job not found.")
        finally:
            connection.close()
        return {"message": "Job removed from saved jobs."}

    return router
