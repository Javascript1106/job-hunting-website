"""Secure adapter for CareerOneStop Jobs V2 listings."""

import os
from urllib.parse import quote, urlencode

from .common import classify_category, fetch_json, plain_text, utc_now


API_ROOT = "https://api.careeronestop.org/v2/jobsearch"


def _date_only(value):
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def _path_value(value):
    return quote(str(value), safe="")


def fetch_jobs(configuration):
    """Fetch bounded U.S. results without exposing credentials in URLs or logs."""
    user_id = os.getenv("CAREERONESTOP_USER_ID")
    api_token = os.getenv("CAREERONESTOP_API_TOKEN")
    if not user_id or not api_token:
        raise RuntimeError(
            "CAREERONESTOP_USER_ID and CAREERONESTOP_API_TOKEN must be set"
        )

    locations = [
        str(value).strip().upper()
        for value in configuration.get("locations", [])
        if str(value).strip()
    ]
    if not locations:
        raise ValueError("CareerOneStop requires at least one configured location")

    keyword = str(configuration.get("keyword") or "0").strip()
    radius = max(0, min(int(configuration.get("radius", 0)), 500))
    page_size = max(1, min(int(configuration.get("page_size", 100)), 100))
    pages_per_location = max(
        1, min(int(configuration.get("pages_per_location", 1)), 5)
    )
    days = max(0, min(int(configuration.get("days", 60)), 365))
    maximum = max(1, min(int(configuration.get("max_jobs", 4000)), 5000))
    headers = {"Authorization": f"Bearer {api_token}"}
    query = urlencode({
        "showFilters": "false",
        "enableJobDescriptionSnippet": "true",
        "enableMetaData": "true",
    })

    source = "CareerOneStop"
    records = []
    seen_ids = set()
    for location in locations:
        for page in range(pages_per_location):
            start_record = page * page_size
            path = "/".join((
                API_ROOT,
                _path_value(user_id),
                _path_value(keyword),
                _path_value(location),
                str(radius),
                "acquisitiondate",
                "DESC",
                str(start_record),
                str(page_size),
                str(days),
            ))
            payload = fetch_json(f"{path}?{query}", headers=headers)
            if payload.get("ErrorMessage"):
                raise RuntimeError(
                    "CareerOneStop returned an API error: "
                    + plain_text(payload["ErrorMessage"])[:240]
                )
            jobs = payload.get("Jobs") or []
            if not jobs:
                break
            for job in jobs:
                external_id = str(job.get("JvId") or "").strip()
                source_url = str(job.get("URL") or "").strip()
                description = plain_text(job.get("DescriptionSnippet"))
                if (
                    not external_id
                    or external_id in seen_ids
                    or not source_url.startswith("https://")
                    or not description
                ):
                    continue
                seen_ids.add(external_id)
                title = plain_text(job.get("JobTitle"))
                company = plain_text(job.get("Company"))
                location_text = plain_text(job.get("Location"))
                if not title or not company or not location_text:
                    continue
                records.append({
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "description": description,
                    "requirements": None,
                    "preferred_qualifications": None,
                    "experience": "See original listing requirements",
                    "category": classify_category(title, job.get("OnetCodes") or []),
                    "employment_type": None,
                    "is_remote": None,
                    "salary_min": None,
                    "salary_max": None,
                    "salary_period": None,
                    "source": source,
                    "external_job_id": external_id,
                    "source_url": source_url,
                    "posted_at": _date_only(job.get("AcquisitionDate")),
                    "expires_at": None,
                    "application_deadline": None,
                    "last_verified_at": utc_now(),
                })
                if len(records) >= maximum:
                    return source, records
            if len(jobs) < page_size:
                break
    return source, records
