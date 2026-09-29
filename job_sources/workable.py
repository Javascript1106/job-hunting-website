"""Adapter for public jobs published on employer Workable career sites."""

import re
from urllib.parse import quote

from .common import (
    classify_category,
    concise_summary,
    extract_qualification_text,
    fetch_json,
    plain_text,
    utc_now,
)


def _identifier(value):
    identifier = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", identifier):
        raise ValueError("invalid Workable account subdomain")
    return identifier


def _jobs(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("jobs", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("unexpected Workable response format")


def _location(job):
    location = job.get("location")
    if isinstance(location, str):
        return plain_text(location)
    if not isinstance(location, dict):
        return "Location not listed"
    return ", ".join(
        plain_text(location.get(key))
        for key in ("city", "region", "country")
        if location.get(key)
    ) or plain_text(location.get("location_str")) or "Location not listed"


def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    account = _identifier(configuration["account_subdomain"])
    source = f"Workable:{account}"
    payload = fetch_json(
        "https://www.workable.com/api/accounts/"
        f"{quote(account, safe='')}?details=true"
    )
    records = []

    for job in _jobs(payload):
        if not isinstance(job, dict):
            continue
        external_id = job.get("shortcode") or job.get("id")
        title = plain_text(job.get("title") or job.get("full_title"))
        source_url = (
            job.get("url")
            or job.get("application_url")
            or job.get("shortlink")
        )
        if not external_id or not title or not source_url:
            continue
        location = _location(job)
        workplace = str(
            job.get("workplace") or job.get("workplace_type") or ""
        ).lower()
        remote_value = job.get("telecommuting")
        is_remote = (
            remote_value is True
            or str(remote_value or "").lower() in {"true", "yes"}
            or workplace == "remote"
            or "remote" in location.lower()
        )
        if configuration.get("remote_only") and not is_remote:
            continue
        description_source = (
            job.get("description")
            or job.get("description_html")
            or job.get("requirements")
        )
        fallback = (
            f"Official {employer} posting for {title}. "
            "See the employer listing for complete requirements."
        )
        department = job.get("department")
        if isinstance(department, dict):
            department = department.get("name")

        records.append({
            "title": title,
            "company": employer,
            "location": location,
            "description": concise_summary(description_source, fallback),
            "requirements": extract_qualification_text(
                job.get("requirements") or description_source
            ),
            "preferred_qualifications": None,
            "experience": "See published qualifications",
            "category": classify_category(title, [department] if department else []),
            "employment_type": plain_text(
                job.get("employment_type") or job.get("employmentType")
            ) or None,
            "is_remote": is_remote,
            "salary_min": None,
            "salary_max": None,
            "salary_period": None,
            "source": source,
            "external_job_id": str(external_id),
            "source_url": source_url,
            "posted_at": job.get("published_on") or job.get("created_at"),
            "expires_at": job.get("expires_at"),
            "application_deadline": job.get("application_deadline"),
            "last_verified_at": utc_now(),
        })

    maximum = int(configuration.get("max_jobs", 250))
    return source, records[:maximum]
