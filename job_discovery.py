"""Server-side filtering and ranking for public PathForge job discovery."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable


SEARCH_SYNONYMS = {
    "developer": ("developer", "engineer", "programmer", "software"),
    "programmer": ("programmer", "developer", "engineer", "software"),
    "cashier": ("cashier", "checkout", "front end", "guest advocate"),
    "restaurant": ("restaurant", "food service", "crew member", "team member", "server", "cook", "barista"),
    "warehouse": ("warehouse", "fulfillment", "picker", "packer", "material handler", "stocking"),
    "remote": ("remote", "work from home"),
    "receptionist": ("receptionist", "front desk", "administrative assistant"),
    "support": ("support", "customer service", "customer care", "help desk"),
    "sales": ("sales", "account executive", "business development"),
    "healthcare": ("healthcare", "medical", "clinical", "patient care"),
    "marketing": ("marketing", "content", "brand", "communications"),
}
IGNORED_SEARCH_TERMS = {"job", "jobs", "role", "roles", "position", "positions", "work"}
NON_US_MARKERS = (
    "canada", "united kingdom", "australia", "india", "germany", "france",
    "mexico", "ireland", "singapore", "philippines", "south africa",
)
US_MARKERS = (
    "united states", "u.s.", "usa", "nationwide", "remote - us", "remote, us",
)
US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except ValueError:
        return None


def _search_concepts(query: str) -> list[tuple[str, ...]]:
    terms = re.sub(r"[^a-z0-9+#.\-]+", " ", query.lower()).split()
    return [SEARCH_SYNONYMS.get(term, (term,)) for term in terms if term not in IGNORED_SEARCH_TERMS]


def _search_fields(job: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(job.get("title")),
        _text(job.get("company")),
        _text(job.get("category")),
        " ".join(_text(job.get(field)) for field in ("description", "requirements", "preferred_qualifications")),
    )


def _matches_query(job: dict[str, Any], query: str) -> bool:
    concepts = _search_concepts(query)
    if not concepts:
        return True
    combined = " ".join(_search_fields(job))
    return all(any(term in combined for term in alternatives) for alternatives in concepts)


def _employment_type(value: Any) -> str:
    normalized = re.sub(r"[\s_]+", "-", _text(value))
    if normalized in {"full-time", "fulltime"}:
        return "full-time"
    if normalized in {"part-time", "parttime", "12-39-hours-per-week"}:
        return "part-time"
    return ""


def _work_setting(job: dict[str, Any]) -> str:
    combined = " ".join(_text(job.get(field)) for field in ("title", "location", "description", "requirements"))
    if re.search(r"\bhybrid\b|partly remote|remote and (?:in[- ]?office|on[- ]?site)", combined):
        return "hybrid"
    if job.get("is_remote") == 1:
        return "remote"
    if job.get("is_remote") == 0:
        return "onsite"
    return ""


def _experience_group(job: dict[str, Any]) -> str:
    stated = _text(job.get("experience"))
    if re.search(r"entry|no experience", stated):
        return "entry-level"
    if "experienced" in stated:
        return "experienced"
    title = _text(job.get("title"))
    details = " ".join(_text(job.get(field)) for field in ("title", "experience", "requirements", "description"))
    if re.search(r"\b(?:intern(?:ship)?|apprentice|trainee|junior|entry[ -]?level|student|no experience|crew member|team member|cashier|customer service rep(?:resentative)?|pizza maker)\b", details):
        return "entry-level"
    if re.search(r"\b(?:senior|sr\.?|manager|supervisor|director|lead|principal|chief|engineer|analyst|specialist|consultant|architect|attorney|counsel|accountant|registered|licensed|certification required|bachelor'?s|master'?s|doctorate|[1-9]\+? years?|one or more years|two or more years)\b", details):
        return "experienced"
    if re.search(r"see (?:published|official) (?:qualifications|eligibility requirements)", stated) and not re.search(r"\b(?:assistant|associate|aide|support|representative|coordinator)\b", title):
        return "experienced"
    return ""


def _minimum_age(job: dict[str, Any]) -> int | None:
    details = " ".join(str(job.get(field) or "") for field in ("description", "requirements"))
    matches = re.findall(r"\b(?:minimum age stated by employer:|at least|minimum age(?: is|:)?|must be)\s*(1[4-9]|2[01])\b", details, re.I)
    return min(map(int, matches)) if matches else None


def _teen_friendly(job: dict[str, Any]) -> bool:
    title = _text(job.get("title"))
    details = " ".join(_text(job.get(field)) for field in ("title", "description", "requirements", "experience"))
    clearly_allows = bool(re.search(r"\b(?:age 14|age 15|age 16|age 17|14 years old|15 years old|16 years old|17 years old|teen(?:ager)?s? welcome|high school student)\b", details))
    starter_role = bool(re.search(r"\b(?:cashier|crew member|team member|counter attendant|food service|host|hostess|busser|dishwasher|barista|ice cream|grocery|cart attendant|store associate|retail associate|sales associate|stock(?:er|ing)?|guest advocate|park attendant|recreation aide|lifeguard|camp counselor|tutor|pet sitter|dog walker|babysitter)\b", title))
    adult_only = bool(re.search(r"\b(?:must be (?:18|19|20|21)|(?:18|19|20|21)\+|at least (?:18|19|20|21)|bachelor'?s|master'?s|doctorate|professional license|driver'?s license|cdl|security clearance|armed|alcohol|bartender|forklift|heavy machinery|[2-9]\+? years?|two or more years|three or more years)\b", details))
    senior_role = bool(re.search(r"\b(?:senior|sr\.?|manager|supervisor|director|engineer|registered|licensed|lead|principal|specialist|executive|accountant|analyst|technician)\b", title))
    return not adult_only and not senior_role and (
        (_minimum_age(job) or 100) <= 17
        or clearly_allows
        or (starter_role and _experience_group(job) == "entry-level")
    )


def _matches_age(job: dict[str, Any], selected: str) -> bool:
    if selected in {"all", "age-18-plus"}:
        return True
    minimum = _minimum_age(job)
    if selected == "age-14":
        return minimum is not None and minimum <= 14
    if selected == "age-15":
        return minimum is not None and minimum <= 15
    return (minimum is not None and minimum <= 17) or _teen_friendly(job)


def _is_us_location(value: Any) -> bool:
    location = _text(value)
    if not location:
        return False
    if any(marker in location for marker in NON_US_MARKERS):
        return False
    if any(marker in location for marker in US_MARKERS):
        return True
    tokens = set(re.findall(r"\b[a-z]{2}\b", location))
    return bool(tokens & US_STATE_CODES) or any(name in location for name in US_STATE_NAMES)


def _has_pay(job: dict[str, Any]) -> bool:
    return job.get("salary_min") is not None or job.get("salary_max") is not None or _text(job.get("pay")) not in {"", "not listed"}


ACCOMMODATION_PATTERN = re.compile(
    r"\b(?:reasonable\s+accommodations?|disability\s+accommodations?|"
    r"accommodations?\s+(?:during|for|throughout|in)\s+(?:the\s+)?"
    r"(?:application|interview|hiring|recruit(?:ing|ment)|selection)\s+process|"
    r"request\s+(?:an?\s+)?accommodations?|need\s+(?:an?\s+)?"
    r"accommodations?\s+to\s+(?:apply|participate|complete)|"
    r"alternative\s+(?:method|way)\s+(?:of|to)\s+appl(?:y|ication))\b",
    re.I,
)


def has_accommodation_information(job: dict[str, Any]) -> bool:
    """Detect explicit application or hiring accommodation language."""
    details = " ".join(
        str(job.get(field) or "")
        for field in (
            "description", "requirements", "preferred_qualifications",
        )
    )
    return bool(ACCOMMODATION_PATTERN.search(details))


def _quality_score(job: dict[str, Any]) -> int:
    checks = (
        _has_pay(job),
        bool(_employment_type(job.get("employment_type") or job.get("schedule"))),
        job.get("is_remote") in {0, 1},
        bool(_text(job.get("requirements"))),
        bool(job.get("application_deadline") or job.get("expires_at")),
        bool(job.get("source_url") or job.get("application_url")),
        bool(job.get("last_verified_at")),
    )
    return sum(checks)


def _relevance(job: dict[str, Any], query: str, location: str) -> tuple[int, list[str]]:
    title, company, category, details = _search_fields(job)
    normalized_query = query.strip().lower()
    score = 0
    reasons: list[str] = []
    if re.search(r"\bcustomer (?:support|service)\b", normalized_query) and re.search(r"\bcustomer (?:service|support) (?:rep(?:resentative)?|associate|agent)\b", title):
        score += 50
        reasons.append("Customer-service role match")
    if re.search(r"\bsoftware (?:developer|programmer|engineer)\b", normalized_query) and re.search(r"\bsoftware (?:developer|programmer|engineer)\b", title):
        score += 40
        reasons.append("Software role match")
    if normalized_query and title == normalized_query:
        score += 80
        reasons.append("Exact job-title match")
    elif normalized_query and normalized_query in title:
        score += 55
        reasons.append("Strong job-title match")
    title_matches = 0
    for alternatives in _search_concepts(query):
        if any(term in title for term in alternatives):
            title_matches += 1
        elif any(term in company for term in alternatives):
            score += 12
        elif any(term in category for term in alternatives):
            score += 8
        elif any(term in details for term in alternatives):
            score += 2
    if title_matches:
        score += title_matches * 18
        reasons.append(f"{title_matches} search term{'s' if title_matches != 1 else ''} matched the title")
    if location and location in _text(job.get("location")):
        score += 18
        reasons.append("Location match")
    posted = _parse_date(job.get("posted_at") or job.get("created_at"))
    if posted:
        age_days = max(0, (datetime.now(timezone.utc) - posted.astimezone(timezone.utc)).total_seconds() / 86400)
        if age_days <= 7:
            score += 10
            reasons.append("Posted recently")
        elif age_days <= 30:
            score += 5
    if job.get("verification_status") == "verified":
        score += 7
    if _has_pay(job):
        score += 3
    return score, reasons[:3]


def _pay_value(job: dict[str, Any]) -> float:
    raw = job.get("salary_max") if job.get("salary_max") is not None else job.get("salary_min")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return -1
    return value * 2080 if job.get("salary_period") == "hour" else value


def _minimum_annual_pay(job: dict[str, Any]) -> float:
    try:
        value = float(job.get("salary_min"))
    except (TypeError, ValueError):
        return -1
    period = _text(job.get("salary_period"))
    if period in {"hour", "hourly", "hr"}:
        return value * 2080
    if period in {"month", "monthly"}:
        return value * 12
    if period in {"week", "weekly"}:
        return value * 52
    return value


def _remote_eligibility(job: dict[str, Any]) -> str:
    if _work_setting(job) != "remote":
        return "not-remote"
    location = _text(job.get("location"))
    if re.search(r"\b(?:worldwide|anywhere|global|all countries)\b", location):
        return "anywhere"
    if _is_us_location(location):
        return "us"
    return "restricted"


EXCLUSION_PATTERNS = {
    "senior": ("title", re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|head|chief|vp|vice president)\b", re.I)),
    "staffing": ("all", re.compile(r"\b(?:staffing agency|staffing firm|recruiting agency|recruitment agency|third[- ]party recruiter)\b", re.I)),
    "commission": ("all", re.compile(r"\b(?:commission[- ]only|100% commission|commission based|independent contractor|1099)\b", re.I)),
    "clearance": ("all", re.compile(r"\b(?:security clearance|secret clearance|top secret|ts/sci)\b", re.I)),
    "unpaid": ("all", re.compile(r"\b(?:unpaid|volunteer position|no compensation)\b", re.I)),
}


def _matches_exclusions(job: dict[str, Any], exclusions: set[str], excluded_terms: list[str]) -> bool:
    title = str(job.get("title") or "")
    combined = " ".join(str(job.get(field) or "") for field in (
        "title", "company", "description", "requirements", "preferred_qualifications"
    ))
    lowered = combined.lower()
    if any(term in lowered for term in excluded_terms):
        return True
    for name in exclusions:
        definition = EXCLUSION_PATTERNS.get(name)
        if definition and definition[1].search(title if definition[0] == "title" else combined):
            return True
    return False


def _duplicate_key(job: dict[str, Any]) -> str:
    return "|".join(re.sub(r"[^a-z0-9]+", " ", _text(job.get(field))).strip() for field in ("title", "company", "location"))


def _group_duplicates(jobs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for original in jobs:
        job = dict(original)
        key = _duplicate_key(job)
        existing = groups.get(key)
        if existing is None:
            job.update(duplicate_count=1, alternate_sources=[])
            groups[key] = job
            continue
        existing["duplicate_count"] += 1
        source = job.get("source") or job.get("company")
        if source and source not in existing["alternate_sources"]:
            existing["alternate_sources"].append(source)
        if not existing.get("source_url") and job.get("source_url"):
            count, sources = existing["duplicate_count"], existing["alternate_sources"]
            existing.clear()
            existing.update(job, duplicate_count=count, alternate_sources=sources)
    return list(groups.values())


def discover_jobs(jobs: Iterable[dict[str, Any]], *, query: str = "", location: str = "", location_scope: str = "us", location_mode: str = "nearby", category: str = "all", employment_type: str = "all", remote: str = "all", remote_eligibility: str = "all", experience: str = "all", age_fit: str = "all", date_posted: str = "all", listing_quality: str = "all", minimum_pay: float = 0, exclusions: str = "", exclude_terms: str = "", sort: str = "recommended") -> list[dict[str, Any]]:
    """Apply the public job-search rules and return grouped, ranked results."""
    normalized_location = _text(location)
    cutoff_days = int(date_posted) if date_posted.isdigit() else None
    selected_exclusions = {value for value in exclusions.split(",") if value in EXCLUSION_PATTERNS}
    excluded_terms = [term.strip().lower() for term in exclude_terms.split(",") if term.strip()]
    now = datetime.now(timezone.utc)
    matches = []
    for job in jobs:
        if not _matches_query(job, query):
            continue
        if normalized_location:
            job_location = _text(job.get("location"))
            if location_mode == "exact":
                components = [part.strip() for part in re.split(r"[;/]", job_location)]
                if not any(component == normalized_location or component.startswith(f"{normalized_location},") for component in components):
                    continue
            elif normalized_location not in job_location:
                continue
        if location_scope == "us" and not _is_us_location(job.get("location")):
            continue
        if category != "all" and job.get("category") != category:
            continue
        if employment_type != "all" and _employment_type(job.get("employment_type") or job.get("schedule")) != employment_type:
            continue
        if remote != "all" and _work_setting(job) != remote:
            continue
        eligibility = _remote_eligibility(job)
        if remote_eligibility == "us" and eligibility not in {"us", "anywhere"}:
            continue
        if remote_eligibility == "anywhere" and eligibility != "anywhere":
            continue
        if experience != "all" and _experience_group(job) != experience:
            continue
        if not _matches_age(job, age_fit):
            continue
        if cutoff_days is not None:
            posted = _parse_date(job.get("posted_at") or job.get("created_at"))
            if posted is None or (now - posted.astimezone(timezone.utc)).total_seconds() > cutoff_days * 86400:
                continue
        quality = _quality_score(job)
        if listing_quality == "pay" and not _has_pay(job):
            continue
        if listing_quality == "deadline" and not (job.get("application_deadline") or job.get("expires_at")):
            continue
        if listing_quality == "accommodation" and not has_accommodation_information(job):
            continue
        if listing_quality == "complete" and quality < 6:
            continue
        if minimum_pay > 0 and _minimum_annual_pay(job) < minimum_pay:
            continue
        if _matches_exclusions(job, selected_exclusions, excluded_terms):
            continue
        matches.append(job)

    grouped = _group_duplicates(matches)
    for job in grouped:
        score, reasons = _relevance(job, query, normalized_location)
        job["_relevanceScore"] = score
        job["_relevanceReasons"] = reasons
    if sort == "newest":
        grouped.sort(key=lambda job: _parse_date(job.get("posted_at") or job.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif sort == "pay-high":
        grouped.sort(key=_pay_value, reverse=True)
    elif sort == "verified":
        grouped.sort(key=lambda job: (_quality_score(job), job["_relevanceScore"]), reverse=True)
    else:
        grouped.sort(key=lambda job: (job["_relevanceScore"], _parse_date(job.get("posted_at") or job.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return grouped


def compact_job(job: dict[str, Any]) -> dict[str, Any]:
    """Trim long card text; full text remains available from /jobs/{id}."""
    compact = dict(job)
    compact["accommodation_info"] = has_accommodation_information(job)
    for field in ("description", "requirements", "preferred_qualifications"):
        value = str(compact.get(field) or "")
        if len(value) > 240:
            shortened = value[:240].rsplit(" ", 1)[0].rstrip()
            compact[field] = f"{shortened}…"
            compact["details_truncated"] = True
    return compact
