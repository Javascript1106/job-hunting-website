"""Adapter for verified public Workday career sites."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .common import (
    classify_category,
    concise_summary,
    extract_qualification_text,
    fetch_json,
    plain_text,
    utc_now,
)


MINIMUM_AGE = re.compile(
    r"\b(?:minimum age(?: requirement)?(?: is|:)?\s*\(?|"
    r"meet the minimum age requirement\s*\(?|at least\s+|must be\s+)"
    r"(1[4-9]|2[01])\+?",
    re.IGNORECASE,
)
PAY_RANGE = re.compile(
    r"\$(\d{1,3}(?:\.\d{1,2})?)\s*(?:-|to)\s*"
    r"\$(\d{1,3}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def _identifier(value):
    result = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", result):
        raise ValueError("invalid Workday identifier")
    return result


def _host(value):
    result = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", result) or ".." in result:
        raise ValueError("invalid Workday host")
    return result


def _post_json(url, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "PathForge/1.0",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(
            f"HTTP {error.code} returned by {urlparse(url).netloc}"
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"could not reach {urlparse(url).netloc}: {error.reason}"
        ) from error


def _minimum_age(text):
    ages = [int(value) for value in MINIMUM_AGE.findall(text or "")]
    return min(ages) if ages else None


def _pay_fields(text):
    match = PAY_RANGE.search(text or "")
    if not match:
        return None, None, None
    return float(match.group(1)), float(match.group(2)), "hour"


def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    host = _host(configuration["host"])
    tenant = _identifier(configuration["tenant"])
    site = _identifier(configuration["site"])
    source = f"Workday:{tenant}:{site}"
    base = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    page_size = 20
    scan_limit = max(page_size, int(configuration.get("scan_limit", 500)))
    maximum = int(configuration.get("max_jobs", 200))
    confirmed_teen_only = configuration.get("confirmed_teen_only", True) is not False
    allowed_countries = {
        str(country).strip().upper()
        for country in configuration.get("country_codes", ["US"])
    }
    patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in configuration.get("title_patterns", [])
    ]
    search_queries = configuration.get("search_queries") or [""]
    search_queries = [plain_text(query)[:100] for query in search_queries]
    candidates = []
    seen_paths = set()
    for search_query in search_queries:
        for offset in range(0, scan_limit, page_size):
            payload = _post_json(
                base + "/jobs",
                {
                    "appliedFacets": {},
                    "limit": page_size,
                    "offset": offset,
                    "searchText": search_query,
                },
            )
            postings = payload.get("jobPostings", [])
            if not postings:
                break
            for posting in postings:
                title = plain_text(posting.get("title"))
                path = posting.get("externalPath")
                if (
                    not path
                    or path in seen_paths
                    or (patterns and not any(pattern.search(title) for pattern in patterns))
                ):
                    continue
                seen_paths.add(path)
                candidates.append(posting)
            if offset + len(postings) >= int(payload.get("total") or 0):
                break

    details_to_scan = candidates[:int(
        configuration.get("detail_scan_limit", maximum * 3)
    )]
    workers = max(1, min(int(configuration.get("detail_workers", 12)), 16))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        details = executor.map(
            lambda posting: fetch_json(base + posting["externalPath"]),
            details_to_scan,
        )

    records = []
    for detail in details:
        info = detail.get("jobPostingInfo") or {}
        description_html = info.get("jobDescription")
        description_text = plain_text(description_html)
        minimum_age = _minimum_age(description_text)
        if confirmed_teen_only and (minimum_age is None or minimum_age > 17):
            continue
        country = (
            (info.get("jobRequisitionLocation") or {})
            .get("country", {})
            .get("alpha2Code")
        )
        if str(country or "").upper() not in allowed_countries:
            continue
        title = plain_text(info.get("title"))
        location = plain_text(info.get("location")) or "Location not listed"
        minimum, maximum_pay, period = _pay_fields(description_text)
        requirements = extract_qualification_text(description_html)
        age_text = (
            f"Minimum age stated by employer: {minimum_age}."
            if minimum_age is not None else ""
        )
        requirements = f"{age_text} {requirements or ''}".strip() or None
        records.append({
            "title": title,
            "company": employer,
            "location": location,
            "description": concise_summary(
                description_html,
                f"Official {employer} starter-role posting for {title}.",
            ),
            "requirements": requirements,
            "preferred_qualifications": None,
            "experience": (
                "Entry level / confirmed teen-friendly"
                if minimum_age is not None and minimum_age <= 17
                else "Entry level / check employer age requirements"
            ),
            "category": classify_category(title, ["Retail", "Food Service"]),
            "employment_type": info.get("timeType"),
            "is_remote": False,
            "salary_min": minimum,
            "salary_max": maximum_pay,
            "salary_period": period,
            "source": source,
            "external_job_id": str(info.get("jobReqId") or info["id"]),
            "source_url": info["externalUrl"],
            "posted_at": info.get("startDate"),
            "expires_at": None,
            "application_deadline": None,
            "last_verified_at": utc_now(),
        })
        if len(records) >= maximum:
            break
    return source, records
