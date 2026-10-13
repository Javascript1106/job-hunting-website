"""Adapter for retrieving and normalizing jobs from authorized SmartRecruiters boards."""

import re
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from .common import (
    classify_category,
    concise_summary,
    extract_qualification_text,
    fetch_json,
    plain_text,
    utc_now,
)


STARTER_TITLE = re.compile(
    r"\b(?:customer service rep(?:resentative)?|pizza maker|crew member|"
    r"team member|cashier|counter (?:person|staff|associate)|insider|"
    r"sales associate|retail associate|brand associate|brand representative|"
    r"sales advisor|store associate|shop associate|cast member|lifeguard|pool attendant|"
    r"recreation attendant|food (?:and|&) beverage attendant|"
    r"concession(?:s)? attendant|host|hostess|busser|dishwasher)\b",
    re.IGNORECASE,
)
EXCLUDED_TITLE = re.compile(
    r"\b(?:senior|sr\.?|driver|manager|assistant manager|general manager|shift lead|"
    r"supervisor|technician|corporate|warehouse)\b",
    re.IGNORECASE,
)
MINIMUM_AGE = re.compile(
    r"\b(?:(?:you\s+are\s+)?at least|minimum age(?: is|:)?|(?:you\s+)?must be)\s*(1[4-9]|2[01])"
    r"(?:\s*years?(?:\s*of)?\s*age|\s*years?\s*old)?\b",
    re.IGNORECASE,
)


def _section_text(detail):
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    return " ".join(
        plain_text(section.get("text"))
        for section in sections.values()
        if isinstance(section, dict) and section.get("text")
    )


def _minimum_age(text):
    ages = [int(value) for value in MINIMUM_AGE.findall(text or "")]
    return min(ages) if ages else None


def _qualification_text(detail):
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    explicit = sections.get("qualifications") or {}
    qualification_text = extract_qualification_text(explicit.get("text"))
    if qualification_text:
        return qualification_text
    job_description = sections.get("jobDescription") or {}
    return extract_qualification_text(job_description.get("text"))


def _nationwide_order(postings):
    """Round-robin states so one large market cannot consume the result cap."""
    by_region = defaultdict(deque)
    for posting in postings:
        location = posting.get("location") or {}
        region = plain_text(location.get("region")) or "Other"
        by_region[region].append(posting)
    ordered = []
    regions = sorted(by_region)
    while regions:
        remaining = []
        for region in regions:
            queue = by_region[region]
            if queue:
                ordered.append(queue.popleft())
            if queue:
                remaining.append(region)
        regions = remaining
    return ordered


# Apply configured limits before normalizing provider records to keep syncs bounded.
def fetch_jobs(configuration):
    company_id = configuration["company_id"].strip()
    employer = configuration["employer"].strip()
    source = f"SmartRecruiters:{company_id}"
    page_size = min(int(configuration.get("page_size", 100)), 100)
    scan_limit = int(configuration.get("scan_limit", 1200))
    maximum = int(configuration.get("max_jobs", 150))
    confirmed_teen_only = configuration.get("confirmed_teen_only", True) is not False
    candidates = []

    for offset in range(0, scan_limit, page_size):
        payload = fetch_json(
            "https://api.smartrecruiters.com/v1/companies/"
            f"{quote(company_id, safe='')}/postings?limit={page_size}&offset={offset}"
        )
        postings = payload.get("content", [])
        if not postings:
            break
        for posting in postings:
            title = plain_text(posting.get("name"))
            location = posting.get("location") or {}
            if (
                str(location.get("country") or "").lower() != "us"
                or not STARTER_TITLE.search(title)
                or EXCLUDED_TITLE.search(title)
            ):
                continue
            candidates.append(posting)

    candidates.sort(
        key=lambda posting: (
            (posting.get("typeOfEmployment") or {}).get("id") != "part-time",
            posting.get("releasedDate") or "",
        )
    )
    candidates = _nationwide_order(candidates)
    records = []
    detail_scan_limit = min(
        len(candidates),
        int(configuration.get("detail_scan_limit", maximum * 3)),
    )
    detail_candidates = candidates[:detail_scan_limit]
    worker_count = max(1, min(int(configuration.get("detail_workers", 12)), 16))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        details = executor.map(
            lambda posting: fetch_json(posting["ref"]),
            detail_candidates,
        )

    for detail in details:
        if len(records) >= maximum:
            break
        full_text = _section_text(detail)
        minimum_age = _minimum_age(full_text)
        if confirmed_teen_only and (minimum_age is None or minimum_age > 17):
            continue
        location = detail.get("location") or {}
        title = plain_text(detail.get("name"))
        employment = (detail.get("typeOfEmployment") or {}).get("label")
        qualification_text = _qualification_text(detail)
        age_text = (
            f"Minimum age stated by employer: {minimum_age}."
            if minimum_age is not None else ""
        )
        qualification_age = _minimum_age(qualification_text)
        requirements = (
            f"{age_text} {qualification_text}".strip()
            if qualification_text and qualification_age is None
            else qualification_text or age_text or None
        )
        records.append({
            "title": title,
            "company": employer,
            "location": plain_text(location.get("fullLocation")) or "United States",
            "description": concise_summary(
                full_text,
                f"Official {employer} starter-role posting for {title}.",
            ),
            "requirements": requirements,
            "preferred_qualifications": None,
            "experience": (
                "Entry level / confirmed teen-friendly"
                if minimum_age is not None and minimum_age <= 17
                else "Entry level / check employer age requirements"
            ),
            "category": classify_category(title, ["Restaurants", "Customer Service"]),
            "employment_type": employment,
            "is_remote": False,
            "salary_min": None,
            "salary_max": None,
            "salary_period": None,
            "source": source,
            "external_job_id": str(detail["id"]),
            "source_url": detail["postingUrl"],
            "posted_at": detail.get("releasedDate"),
            "expires_at": None,
            "application_deadline": None,
            "last_verified_at": utc_now(),
        })

    return source, records
