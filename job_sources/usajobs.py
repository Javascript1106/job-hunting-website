"""Adapter for retrieving and normalizing public federal listings from USAJOBS."""

import os
from urllib.parse import urlencode

from .common import (
    classify_category,
    concise_summary,
    fetch_json,
    plain_text,
    utc_now
)


def first_name(items):
    if not items:
        return None
    first = items[0]
    if isinstance(first, dict):
        return plain_text(first.get("Name"))
    return plain_text(first)


def salary_period(code):
    return {
        "Per Year": "year",
        "PA": "year",
        "Per Hour": "hour",
        "PH": "hour"
    }.get(str(code or ""))


def date_only(value):
    if not value:
        return None

    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


# USAJOBS credentials come from the environment and are never stored in source data.
def fetch_jobs(configuration):
    api_key = os.getenv("USAJOBS_API_KEY")
    user_agent = os.getenv("USAJOBS_USER_AGENT")
    if not api_key or not user_agent:
        raise RuntimeError(
            "USAJOBS_API_KEY and USAJOBS_USER_AGENT must be set"
        )

    query = {
        "ResultsPerPage": min(
            int(configuration.get("results_per_page", 100)),
            500
        )
    }
    if configuration.get("keyword"):
        query["Keyword"] = configuration["keyword"]
    if configuration.get("location"):
        query["LocationName"] = configuration["location"]
    if configuration.get("remote_only"):
        query["RemoteIndicator"] = "true"

    items = []
    # Smaller pages keep each response inside the shared safety limit. The
    # higher page ceiling preserves broad catalog coverage without accepting
    # an oversized single response.
    page_count = max(1, min(int(configuration.get("pages", 1)), 30))
    headers = {
        "Authorization-Key": api_key,
        "User-Agent": user_agent,
        "Host": "data.usajobs.gov"
    }
    for page in range(1, page_count + 1):
        page_query = {**query, "Page": page}
        payload = fetch_json(
            "https://data.usajobs.gov/api/Search?" + urlencode(page_query),
            headers=headers,
        )
        page_items = (
            payload.get("SearchResult", {})
            .get("SearchResultItems", [])
        )
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < query["ResultsPerPage"]:
            break
    source = "USAJOBS"
    records = []
    seen_position_ids = set()

    for item in items:
        descriptor = item.get("MatchedObjectDescriptor") or {}
        position_id = str(descriptor.get("PositionID") or "").strip()
        if not position_id or position_id in seen_position_ids:
            continue
        seen_position_ids.add(position_id)
        details = (
            descriptor.get("UserArea", {})
            .get("Details", {})
        )
        title = plain_text(descriptor.get("PositionTitle"))
        locations = [
            plain_text(location.get("LocationName"))
            for location in descriptor.get("PositionLocation", [])
            if location.get("LocationName")
        ]
        location = ", ".join(locations) or "Location not listed"
        remote_value = details.get("RemoteIndicator")
        is_remote = (
            True
            if remote_value is True or str(remote_value).lower() == "true"
            else False
            if location != "Location not listed"
            else None
        )
        remuneration = descriptor.get("PositionRemuneration") or []
        pay = remuneration[0] if remuneration else {}
        period = salary_period(pay.get("RateIntervalCode"))
        try:
            minimum = float(pay["MinimumRange"]) if period else None
            maximum = float(pay["MaximumRange"]) if period else None
        except (KeyError, TypeError, ValueError):
            minimum = maximum = None
        employment_type = first_name(
            descriptor.get("PositionSchedule")
        )
        organization = (
            plain_text(descriptor.get("OrganizationName"))
            or "United States Federal Government"
        )
        fallback = (
            f"Official federal posting for {title}. "
            "See USAJOBS for complete eligibility and requirements."
        )
        job_categories = descriptor.get("JobCategory") or []
        category_name = first_name(job_categories) or ""
        application_close_date = (
            descriptor.get("ApplicationCloseDate")
            or descriptor.get("PositionEndDate")
        )

        records.append({
            "title": title,
            "company": organization,
            "location": location,
            "description": concise_summary(
                details.get("JobSummary"),
                fallback
            ),
            "requirements": (
                concise_summary(
                    details.get("QualificationsSummary"),
                    "",
                    limit=1800
                ) or None
            ),
            "preferred_qualifications": None,
            "experience": "See official eligibility requirements",
            "category": classify_category(
                title,
                [category_name]
            ),
            "employment_type": employment_type,
            "is_remote": is_remote,
            "salary_min": minimum,
            "salary_max": maximum,
            "salary_period": period,
            "source": source,
            "external_job_id": position_id,
            "source_url": descriptor["PositionURI"],
            "posted_at": descriptor.get("PublicationStartDate"),
            "expires_at": application_close_date,
            "application_deadline": date_only(
                application_close_date
            ),
            "last_verified_at": utc_now()
        })

    return source, records
