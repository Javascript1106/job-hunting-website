"""Adapter for retrieving and normalizing jobs from authorized Ashby boards."""

from urllib.parse import quote

from .common import (
    MAX_JSON_BYTES,
    classify_category,
    concise_summary,
    extract_qualification_text,
    fetch_json,
    plain_text,
    utc_now,
)


US_COUNTRY_NAMES = {
    "us",
    "usa",
    "united states",
    "united states of america",
}


def _postal_address(location):
    address = (location or {}).get("address") or {}
    # Primary locations wrap their fields in postalAddress, while Ashby's
    # secondaryLocations entries expose the same fields directly.
    return address.get("postalAddress") or address


def _is_us_location(location):
    country = plain_text(
        _postal_address(location).get("addressCountry")
    ).lower()
    location_name = plain_text((location or {}).get("location")).lower()
    return (
        country in US_COUNTRY_NAMES
        or "united states" in location_name
        or "remote (us" in location_name
        or "remote - us" in location_name
        or location_name in {"us", "usa", "remote us"}
    )


def _has_us_location(job):
    primary = {
        "location": job.get("location"),
        "address": job.get("address"),
    }
    return _is_us_location(primary) or any(
        _is_us_location(location)
        for location in job.get("secondaryLocations") or []
    )


def _location_text(job):
    locations = []
    primary = plain_text(job.get("location"))
    if primary:
        locations.append(primary)
    locations.extend(
        plain_text(location.get("location"))
        for location in job.get("secondaryLocations") or []
        if _is_us_location(location) and location.get("location")
    )
    unique_locations = list(dict.fromkeys(locations))
    return ", ".join(unique_locations[:4]) or "United States"


def _salary_fields(job):
    compensation = job.get("compensation") or {}
    components = compensation.get("summaryComponents") or []
    if not components:
        tiers = compensation.get("compensationTiers") or []
        for tier in tiers:
            components.extend(tier.get("components") or [])

    periods = {
        "1 HOUR": "hour",
        "HOUR": "hour",
        "1 YEAR": "year",
        "YEAR": "year",
    }
    for component in components:
        if component.get("compensationType") != "Salary":
            continue
        if str(component.get("currencyCode") or "").upper() != "USD":
            continue
        minimum = component.get("minValue")
        maximum = component.get("maxValue")
        period = periods.get(
            str(component.get("interval") or "").upper()
        )
        if (
            isinstance(minimum, (int, float))
            and isinstance(maximum, (int, float))
            and period
        ):
            return float(minimum), float(maximum), period
    return None, None, None


# Convert provider-specific fields into the shared record schema in common.py.
def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    board_name = configuration["board_name"].strip()
    source = f"Ashby:{board_name}"
    payload = fetch_json(
        "https://api.ashbyhq.com/posting-api/job-board/"
        f"{quote(board_name, safe='')}?includeCompensation=true",
        max_bytes=configuration.get("max_response_bytes", MAX_JSON_BYTES),
    )
    records = []

    for job in payload.get("jobs", []):
        if not job.get("isListed", True) or not _has_us_location(job):
            continue
        if configuration.get("remote_only") and not job.get("isRemote"):
            continue

        title = plain_text(job.get("title"))
        description_source = (
            job.get("descriptionPlain")
            or job.get("descriptionHtml")
        )
        minimum, maximum, period = _salary_fields(job)
        departments = [
            value
            for value in (job.get("department"), job.get("team"))
            if value
        ]
        fallback = (
            f"Official {employer} posting for {title}. "
            "See the employer listing for complete requirements."
        )

        records.append({
            "title": title,
            "company": employer,
            "location": _location_text(job),
            "description": concise_summary(
                description_source,
                fallback,
            ),
            "requirements": extract_qualification_text(
                description_source
            ),
            "preferred_qualifications": None,
            "experience": "See published qualifications",
            "category": classify_category(title, departments),
            "employment_type": plain_text(
                job.get("employmentType")
            ) or None,
            "is_remote": (
                True if job.get("isRemote") is True else False
            ),
            "salary_min": minimum,
            "salary_max": maximum,
            "salary_period": period,
            "source": source,
            "external_job_id": str(job["id"]),
            "source_url": job.get("jobUrl") or job.get("applyUrl"),
            "posted_at": job.get("publishedAt"),
            "expires_at": None,
            "application_deadline": None,
            "last_verified_at": utc_now(),
        })

    maximum = int(configuration.get("max_jobs", 250))
    return source, records[:maximum]
