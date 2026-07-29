import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SYNC_COLUMNS = [
    "title", "company", "location", "pay", "description",
    "schedule", "experience", "category", "application_method",
    "application_url", "employer_id", "status", "source",
    "external_job_id", "source_url", "posted_at", "expires_at",
    "application_deadline",
    "last_verified_at", "employment_type", "is_remote",
    "salary_min", "salary_max", "salary_period",
    "verification_status"
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_json(url, headers=None, timeout=30):
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "PathForge/1.0"
    }
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"unexpected HTTP status {response.status}"
                )
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(
            f"HTTP {error.code} returned by {urlparse(url).netloc}"
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"could not reach {urlparse(url).netloc}: {error.reason}"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"invalid JSON returned by {urlparse(url).netloc}"
        ) from error


def plain_text(value):
    if not value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", str(value))
    return " ".join(html.unescape(without_tags).split())


def concise_summary(value, fallback, limit=320):
    text = plain_text(value)
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0]
    return f"{shortened}…"


def classify_category(title, departments=None):
    searchable = " ".join(
        [title] + list(departments or [])
    ).lower()
    category_rules = [
        ("Pharmacy", ("pharmacy", "pharmacist")),
        ("Technology", (
            "software", "engineer", "developer", "technology",
            "data scientist", "cyber"
        )),
        ("Customer Service", (
            "customer service", "customer support", "support specialist"
        )),
        ("Healthcare", (
            "health", "nurse", "medical", "clinical", "therapist"
        )),
        ("Warehouse", (
            "warehouse", "fulfillment", "distribution", "inventory"
        )),
        ("Food Service", (
            "restaurant", "barista", "food", "kitchen", "cook"
        )),
        ("Sales", ("sales", "account executive")),
        ("Marketing", ("marketing", "communications")),
        ("Finance", ("finance", "accounting", "accountant")),
        ("Human Resources", (
            "human resources", "recruiter", "talent acquisition"
        )),
        ("Retail", (
            "retail", "store", "cashier", "merchandising"
        ))
    ]
    for category, keywords in category_rules:
        if any(keyword in searchable for keyword in keywords):
            return category
    return "Other"


def valid_https_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme == "https" and bool(parsed.netloc)


def pay_text(job):
    minimum = job.get("salary_min")
    maximum = job.get("salary_max")
    period = job.get("salary_period")
    if minimum is None or maximum is None or not period:
        return "Not listed"
    return f"${minimum:g}-${maximum:g}/{period}"


def validate_record(job):
    required = (
        "title", "company", "location", "description",
        "experience", "category", "source", "external_job_id",
        "source_url", "last_verified_at"
    )
    missing = [field for field in required if not job.get(field)]
    if missing:
        raise ValueError(
            "missing required fields: " + ", ".join(missing)
        )
    if not valid_https_url(job["source_url"]):
        raise ValueError("source_url must be an HTTPS URL")
    if job.get("is_remote") not in (True, False, None):
        raise ValueError("is_remote must be true, false, or null")
    minimum = job.get("salary_min")
    maximum = job.get("salary_max")
    if (minimum is None) != (maximum is None):
        raise ValueError(
            "salary_min and salary_max must both be provided"
        )
    if minimum is not None and minimum > maximum:
        raise ValueError("salary_min cannot exceed salary_max")


def prepare_record(raw_job):
    validate_record(raw_job)
    job = dict(raw_job)
    if not job.get("application_deadline") and job.get("expires_at"):
        job["application_deadline"] = str(
            job["expires_at"]
        )[:10]
    job.update({
        "pay": pay_text(job),
        "schedule": job.get("employment_type") or "Not listed",
        "application_method": "employer_website",
        "application_url": job["source_url"],
        "employer_id": None,
        "status": "active",
        "verification_status": "verified",
        "is_remote": (
            None if job.get("is_remote") is None
            else int(job["is_remote"])
        )
    })
    return job


def synchronize_records(
    database_path,
    records,
    completed_sources,
    mark_stale=False
):
    summary = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "expired": 0,
        "failed": 0
    }
    seen_keys = set()
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    for index, raw_job in enumerate(records, start=1):
        try:
            job = prepare_record(raw_job)
            key = (job["source"], str(job["external_job_id"]))
            job["external_job_id"] = key[1]
            if key in seen_keys:
                raise ValueError("duplicate source and external_job_id")
            seen_keys.add(key)

            existing = cursor.execute(
                """
                SELECT *
                FROM jobs
                WHERE source = ?
                  AND external_job_id = ?
                """,
                key
            ).fetchone()
            values = [job.get(column) for column in SYNC_COLUMNS]

            if existing is None:
                placeholders = ", ".join("?" for _ in SYNC_COLUMNS)
                cursor.execute(
                    f"""
                    INSERT INTO jobs ({", ".join(SYNC_COLUMNS)})
                    VALUES ({placeholders})
                    """,
                    values
                )
                summary["inserted"] += 1
                continue

            changed = any(
                existing[column] != job.get(column)
                for column in SYNC_COLUMNS
            )
            if not changed:
                summary["skipped"] += 1
                continue

            assignments = ", ".join(
                f"{column} = ?" for column in SYNC_COLUMNS
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

    if mark_stale:
        for source in completed_sources:
            source_keys = {
                external_id
                for seen_source, external_id in seen_keys
                if seen_source == source
            }
            existing_rows = cursor.execute(
                """
                SELECT id, external_job_id
                FROM jobs
                WHERE source = ?
                  AND employer_id IS NULL
                  AND verification_status = 'verified'
                """,
                (source,)
            ).fetchall()
            for row in existing_rows:
                if row["external_job_id"] in source_keys:
                    continue
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = 'closed',
                        verification_status = 'expired',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (row["id"],)
                )
                summary["expired"] += 1

    conn.commit()
    conn.close()
    return summary
