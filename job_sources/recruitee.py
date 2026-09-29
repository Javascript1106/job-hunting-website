"""Adapter for public jobs published on employer Recruitee career sites."""

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
        raise ValueError("invalid Recruitee company subdomain")
    return identifier


def _location(job):
    location = job.get("location")
    if isinstance(location, dict):
        parts = [
            location.get("city"),
            location.get("region") or location.get("state"),
            location.get("country"),
        ]
        return ", ".join(plain_text(part) for part in parts if part)
    parts = [job.get("city"), job.get("state"), job.get("country")]
    return plain_text(location) or ", ".join(
        plain_text(part) for part in parts if part
    )


def _country_codes(job):
    codes = {str(job.get("country_code") or "").strip().upper()}
    for location in job.get("locations") or []:
        if isinstance(location, dict):
            codes.add(str(location.get("country_code") or "").strip().upper())
    return codes - {""}


def _salary_fields(job):
    salary = job.get("salary") or {}
    if str(salary.get("currency") or "").upper() != "USD":
        return None, None, None
    try:
        minimum = float(salary["min"])
        maximum = float(salary["max"])
    except (KeyError, TypeError, ValueError):
        return None, None, None
    period = str(salary.get("period") or "").lower()
    if period not in {"hour", "year"}:
        return None, None, None
    return minimum, maximum, period


def _employment_type(job):
    value = plain_text(
        job.get("employment_type")
        or job.get("employmentType")
        or job.get("employment_type_code")
    )
    return {
        "fulltime_permanent": "Full-Time",
        "parttime_permanent": "Part-Time",
        "temporary": "Temporary",
        "contract": "Contract",
        "internship": "Internship",
    }.get(value.lower(), value or None)


def _is_remote(job, location):
    remote = job.get("remote")
    if isinstance(remote, bool):
        return remote
    if str(remote or "").lower() in {"true", "yes", "remote"}:
        return True
    return "remote" in location.lower()


def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    company = _identifier(configuration["company_subdomain"])
    source = f"Recruitee:{company}"
    payload = fetch_json(
        f"https://{quote(company, safe='')}.recruitee.com/api/offers"
    )
    jobs = payload.get("offers", payload.get("jobs", []))
    if not isinstance(jobs, list):
        raise ValueError("unexpected Recruitee response format")

    records = []
    allowed_countries = {
        str(code).strip().upper()
        for code in configuration.get("country_codes", [])
        if str(code).strip()
    }
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if allowed_countries and not (_country_codes(job) & allowed_countries):
            continue
        external_id = job.get("id") or job.get("slug")
        source_url = (
            job.get("careers_url")
            or job.get("careers_apply_url")
            or job.get("url")
        )
        title = plain_text(job.get("title"))
        if not external_id or not title or not source_url:
            continue
        location = _location(job) or "Location not listed"
        is_remote = _is_remote(job, location)
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
        description = concise_summary(description_source, fallback)
        cover_letter_option = job.get("options_cover_letter")
        if (
            cover_letter_option is False
            or str(cover_letter_option or "").lower() in {"off", "optional"}
        ):
            description = f"{description} Cover letter is not required."
        department = job.get("department")
        if isinstance(department, dict):
            department = department.get("name")
        minimum, maximum, period = _salary_fields(job)

        records.append({
            "title": title,
            "company": employer,
            "location": location,
            "description": description,
            "requirements": extract_qualification_text(
                job.get("requirements") or description_source
            ),
            "preferred_qualifications": None,
            "experience": "See published qualifications",
            "category": classify_category(title, [department] if department else []),
            "employment_type": _employment_type(job),
            "is_remote": is_remote,
            "salary_min": minimum,
            "salary_max": maximum,
            "salary_period": period,
            "source": source,
            "external_job_id": str(external_id),
            "source_url": source_url,
            "posted_at": job.get("published_at") or job.get("created_at"),
            "expires_at": job.get("expires_at"),
            "application_deadline": job.get("closing_date"),
            "last_verified_at": utc_now(),
        })

    maximum = int(configuration.get("max_jobs", 250))
    return source, records[:maximum]
