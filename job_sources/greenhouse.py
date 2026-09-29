"""Adapter for retrieving and normalizing jobs from authorized Greenhouse boards."""

from urllib.parse import quote

from .common import (
    classify_category,
    concise_summary,
    extract_qualification_text,
    fetch_json,
    plain_text,
    utc_now
)


def pay_fields(job):
    ranges = job.get("pay_input_ranges") or []

    for pay_range in ranges:
        if str(pay_range.get("currency_type") or "").upper() != "USD":
            continue

        title = str(pay_range.get("title") or "").lower()
        if "base" not in title and len(ranges) > 1:
            continue

        minimum_cents = pay_range.get("min_cents")
        maximum_cents = pay_range.get("max_cents")

        if not isinstance(minimum_cents, (int, float)):
            continue
        if not isinstance(maximum_cents, (int, float)):
            continue

        minimum = minimum_cents / 100
        maximum = maximum_cents / 100
        period = "hour" if maximum <= 1000 else "year"
        return minimum, maximum, period

    return None, None, None


# Convert provider-specific fields into the shared record schema in common.py.
def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    board_token = configuration["board_token"].strip()
    source = f"Greenhouse:{board_token}"
    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        f"{quote(board_token, safe='')}/jobs"
        "?content=true&pay_transparency=true"
    )
    payload = fetch_json(url)
    records = []

    for job in payload.get("jobs", []):
        title = plain_text(job.get("title"))
        location = plain_text(
            (job.get("location") or {}).get("name")
        ) or "Location not listed"
        departments = [
            plain_text(department.get("name"))
            for department in job.get("departments", [])
            if department.get("name")
        ]
        location_lower = location.lower()
        is_remote = (
            True
            if "remote" in location_lower
            else None
            if location_lower in {"", "location not listed", "multiple locations"}
            else False
        )
        if configuration.get("remote_only") and is_remote is not True:
            continue
        fallback = (
            f"Official {employer} posting for {title}. "
            "See the employer listing for complete requirements."
        )
        minimum, maximum, period = pay_fields(job)

        records.append({
            "title": title,
            "company": employer,
            "location": location,
            "description": concise_summary(
                job.get("content"),
                fallback
            ),
            "requirements": extract_qualification_text(
                job.get("content")
            ),
            "preferred_qualifications": None,
            "experience": "See published qualifications",
            "category": classify_category(title, departments),
            "employment_type": None,
            "is_remote": is_remote,
            "salary_min": minimum,
            "salary_max": maximum,
            "salary_period": period,
            "source": source,
            "external_job_id": str(job["id"]),
            "source_url": job["absolute_url"],
            "posted_at": job.get("first_published"),
            "expires_at": job.get("application_deadline"),
            "application_deadline": (
                str(job.get("application_deadline"))[:10]
                if job.get("application_deadline")
                else None
            ),
            "last_verified_at": utc_now()
        })

    maximum = int(configuration.get("max_jobs", 250))
    return source, records[:maximum]
