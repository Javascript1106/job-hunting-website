import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from database import DB_NAME, create_jobs_table


BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "verified_jobs.json"
REQUIRED_FIELDS = {
    "title",
    "company",
    "location",
    "description",
    "experience",
    "category",
    "source",
    "external_job_id",
    "source_url",
    "last_verified_at",
    "verification_status"
}
VERIFICATION_STATUSES = {
    "verified",
    "unverified",
    "expired",
    "removed"
}


def valid_https_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme == "https" and bool(parsed.netloc)


def pay_text(job):
    minimum = job.get("salary_min")
    maximum = job.get("salary_max")
    period = job.get("salary_period")

    if minimum is None or maximum is None or not period:
        return "Not listed"

    def amount(value):
        return f"{value:g}"

    return f"${amount(minimum)}-${amount(maximum)}/{period}"


def validate_job(job):
    missing = [
        field for field in REQUIRED_FIELDS
        if not job.get(field)
    ]
    if missing:
        raise ValueError(
            "missing required fields: " + ", ".join(sorted(missing))
        )
    if not valid_https_url(job["source_url"]):
        raise ValueError("source_url must be an HTTPS URL")
    if job["verification_status"] not in VERIFICATION_STATUSES:
        raise ValueError("invalid verification_status")
    if job.get("is_remote") not in (True, False, None):
        raise ValueError("is_remote must be true, false, or null")
    if job.get("salary_min") is not None:
        if job.get("salary_max") is None:
            raise ValueError("salary_max is required with salary_min")
        if job["salary_min"] > job["salary_max"]:
            raise ValueError("salary_min cannot exceed salary_max")


def import_catalog(mark_stale=False):
    os.chdir(BASE_DIR)
    create_jobs_table()

    with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        jobs = json.load(catalog_file)

    summary = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "expired": 0,
        "failed": 0
    }
    seen_keys = set()
    seen_sources = set()

    conn = sqlite3.connect(BASE_DIR / DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    columns = [
        "title", "company", "location", "pay", "description",
        "schedule", "experience", "category", "application_method",
        "application_url", "employer_id", "status", "source",
        "external_job_id", "source_url", "posted_at", "expires_at",
        "last_verified_at", "employment_type", "is_remote",
        "salary_min", "salary_max", "salary_period",
        "verification_status"
    ]

    for index, raw_job in enumerate(jobs, start=1):
        try:
            validate_job(raw_job)
            job = dict(raw_job)
            key = (job["source"], job["external_job_id"])
            if key in seen_keys:
                raise ValueError("duplicate source and external_job_id")
            seen_keys.add(key)
            seen_sources.add(job["source"])

            job.update({
                "pay": pay_text(job),
                "schedule": job.get("employment_type") or "Not listed",
                "application_method": "employer_website",
                "application_url": job["source_url"],
                "employer_id": None,
                "status": (
                    "active"
                    if job["verification_status"] == "verified"
                    else "closed"
                ),
                "is_remote": (
                    None if job.get("is_remote") is None
                    else int(job["is_remote"])
                )
            })

            existing = cursor.execute(
                """
                SELECT *
                FROM jobs
                WHERE source = ?
                  AND external_job_id = ?
                """,
                key
            ).fetchone()

            values = [job.get(column) for column in columns]
            if existing is None:
                placeholders = ", ".join("?" for _ in columns)
                cursor.execute(
                    f"""
                    INSERT INTO jobs ({", ".join(columns)})
                    VALUES ({placeholders})
                    """,
                    values
                )
                summary["inserted"] += 1
                continue

            changed = any(
                existing[column] != job.get(column)
                for column in columns
            )
            if not changed:
                summary["skipped"] += 1
                continue

            assignments = ", ".join(
                f"{column} = ?" for column in columns
            )
            cursor.execute(
                f"""
                UPDATE jobs
                SET {assignments},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND employer_id IS NULL
                """,
                values + [existing["id"]]
            )
            summary["updated"] += cursor.rowcount
        except (KeyError, TypeError, ValueError) as error:
            summary["failed"] += 1
            print(f"Record {index} failed: {error}")

    if mark_stale and seen_sources:
        placeholders = ", ".join("?" for _ in seen_sources)
        stale_rows = cursor.execute(
            f"""
            SELECT id, source, external_job_id
            FROM jobs
            WHERE employer_id IS NULL
              AND source IN ({placeholders})
              AND verification_status = 'verified'
            """,
            tuple(seen_sources)
        ).fetchall()

        for stale in stale_rows:
            key = (stale["source"], stale["external_job_id"])
            if key in seen_keys:
                continue
            cursor.execute(
                """
                UPDATE jobs
                SET status = 'closed',
                    verification_status = 'expired',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (stale["id"],)
            )
            summary["expired"] += 1

    conn.commit()
    conn.close()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import PathForge's curated verified job catalog."
    )
    parser.add_argument(
        "--mark-stale",
        action="store_true",
        help=(
            "Mark previously imported verified jobs as expired when "
            "they are absent from this catalog."
        )
    )
    arguments = parser.parse_args()
    result = import_catalog(mark_stale=arguments.mark_stale)
    print(json.dumps(result, indent=2))
