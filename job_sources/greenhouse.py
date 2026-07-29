from urllib.parse import quote

from .common import (
    classify_category,
    concise_summary,
    fetch_json,
    plain_text,
    utc_now
)


def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    board_token = configuration["board_token"].strip()
    source = f"Greenhouse:{board_token}"
    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        f"{quote(board_token, safe='')}/jobs?content=true"
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
            True if "remote" in location_lower
            else None
        )
        if configuration.get("remote_only") and is_remote is not True:
            continue
        fallback = (
            f"Official {employer} posting for {title}. "
            "See the employer listing for complete requirements."
        )

        records.append({
            "title": title,
            "company": employer,
            "location": location,
            "description": concise_summary(
                job.get("content"),
                fallback
            ),
            "experience": "Not listed",
            "category": classify_category(title, departments),
            "employment_type": None,
            "is_remote": is_remote,
            "salary_min": None,
            "salary_max": None,
            "salary_period": None,
            "source": source,
            "external_job_id": str(job["id"]),
            "source_url": job["absolute_url"],
            "posted_at": None,
            "expires_at": None,
            "last_verified_at": utc_now()
        })

    maximum = int(configuration.get("max_jobs", 250))
    return source, records[:maximum]
