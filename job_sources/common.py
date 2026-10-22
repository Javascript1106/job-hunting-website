"""Shared fetching, sanitization, classification, and persistence helpers for job adapters."""

import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from database import get_connection
from job_history import record_job_changes


SYNC_COLUMNS = [
    "title", "company", "location", "pay", "description",
    "requirements", "preferred_qualifications",
    "schedule", "experience", "category", "application_method",
    "application_url", "employer_id", "status", "source",
    "external_job_id", "source_url", "posted_at", "expires_at",
    "application_deadline",
    "last_verified_at", "employment_type", "is_remote",
    "salary_min", "salary_max", "salary_period",
    "verification_status", "link_status", "last_link_checked_at"
]
MAX_JSON_BYTES = 10_000_000


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Network requests use a recognizable agent and bounded timeout for reliable sync runs.
def fetch_json(url, headers=None, timeout=30, retries=3):
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "PathForge/1.0"
    }
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)

    for attempt in range(max(0, int(retries)) + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"unexpected HTTP status {response.status}"
                    )
                payload = response.read(MAX_JSON_BYTES + 1)
                if len(payload) > MAX_JSON_BYTES:
                    raise RuntimeError("job source response exceeded the safe size limit")
                return json.loads(payload.decode("utf-8"))
        except HTTPError as error:
            retryable = error.code in {429, 502, 503, 504}
            if retryable and attempt < retries:
                retry_after = (error.headers or {}).get("Retry-After")
                delay = float(retry_after) if str(retry_after or "").isdigit() else 2 ** attempt
                time.sleep(min(max(delay, 0.25), 30))
                continue
            raise RuntimeError(
                f"HTTP {error.code} returned by {urlparse(url).netloc}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"could not reach {urlparse(url).netloc}: {error.reason}"
            ) from error
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"invalid JSON returned by {urlparse(url).netloc}"
            ) from error


def plain_text(value):
    if not value:
        return ""
    decoded = str(value)

    for _ in range(2):
        decoded = html.unescape(decoded)

    without_tags = re.sub(r"<[^>]+>", " ", decoded)
    return " ".join(without_tags.split())


def concise_summary(value, fallback, limit=320):
    text = plain_text(value)
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    accommodation = re.search(
        r"[^.!?]{0,180}\b(?:reasonable\s+accommodations?|"
        r"disability\s+accommodations?|request\s+(?:an?\s+)?"
        r"accommodations?|need\s+(?:an?\s+)?accommodations?\s+to\s+"
        r"(?:apply|participate|complete))\b[^.!?]{0,180}[.!?]?",
        text,
        re.I,
    )
    if accommodation and accommodation.start() >= limit:
        statement = accommodation.group(0).strip()
        statement_limit = min(180, max(100, limit // 2))
        if len(statement) > statement_limit:
            statement = statement[:statement_limit].rsplit(" ", 1)[0] + "…"
        opening_limit = max(80, limit - len(statement) - 4)
        opening = text[:opening_limit].rsplit(" ", 1)[0]
        return f"{opening}… {statement}"
    shortened = text[:limit].rsplit(" ", 1)[0]
    return f"{shortened}…"


def text_lines(value):
    """Preserve ATS headings and bullets while removing markup."""
    if not value:
        return []
    decoded = str(value)
    for _ in range(2):
        decoded = html.unescape(decoded)
    decoded = re.sub(
        r"(?i)<\s*(?:br\s*/?|/p|/li|/ul|/ol|/h[1-6]|/div)\s*>",
        "\n",
        decoded,
    )
    decoded = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", decoded)
    decoded = re.sub(r"<[^>]+>", " ", decoded)
    return [" ".join(line.split()) for line in decoded.splitlines() if line.strip()]


def extract_qualification_text(value, limit=1800):
    """Return employer-written qualifications, never a generic placeholder."""
    lines = text_lines(value)
    qualification_heading = re.compile(
        r"^(?:minimum|required|basic|preferred|desired|key)?\s*"
        r"(?:qualifications?|requirements?|skills(?:\s+and\s+experience)?|"
        r"what (?:you(?:'|’)ll|we) need|what (?:you|we) bring|who you are|"
        r"what we(?:'|’)re looking for|examples? of desirable skills(?:, knowledge and experience)?|"
        r"we(?:'|’)re excited about you because)\s*[?:]?$",
        re.I,
    )
    end_heading = re.compile(
        r"^(?:about(?: us| the (?:company|team|role))?|responsibilities|what you(?:'|’)ll do|"
        r"day in the life|benefits|perks|compensation|salary|additional information|"
        r"equal opportunity|privacy|how to apply|application process|our values|"
        r"the impact you(?:'|’)ll make|job description)\s*[?:]?$",
        re.I,
    )
    signal = re.compile(
        r"\b(?:required|must|minimum|at least|years? of experience|degree|diploma|"
        r"license|certification|proficien(?:t|cy)|fluency|bilingual|ability to|"
        r"experience (?:with|in)|knowledge of|eligible|authorization to work)\b",
        re.I,
    )
    collected = []
    in_section = False
    for line in lines:
        candidate = line.strip(" -:•")
        if qualification_heading.fullmatch(candidate):
            if in_section and collected:
                break
            in_section = True
            continue
        if in_section and end_heading.fullmatch(candidate):
            break
        if in_section:
            collected.append(line)
    if not collected:
        collected = [line for line in lines if signal.search(line)][:8]
    cleaned = []
    for line in collected:
        item = re.sub(r"^[\s•*\-]+", "", line).strip()
        if item and item not in cleaned:
            cleaned.append(item)
    if not cleaned:
        return None
    result = " • ".join(cleaned)
    return result if len(result) <= limit else result[:limit].rsplit(" ", 1)[0] + "…"


def extract_structured_qualifications(sections, limit=1800):
    items = []
    for section in sections or []:
        label = plain_text(section.get("text")).strip(" :").lower()
        if not re.search(
            r"\b(?:qualifications?|requirements?|what (?:you(?:'|’)ll|you|we) "
            r"(?:need|bring)|who you are|nice[- ]?to[- ]?have|"
            r"you(?:'|’)ll crush this role if you have|what you are good at)\b",
            label,
        ):
            continue
        for line in text_lines(section.get("content")):
            item = re.sub(r"^[\s•*\-]+", "", line).strip()
            if item and item not in items:
                items.append(item)
    if not items:
        return None
    result = " • ".join(items)
    return result if len(result) <= limit else result[:limit].rsplit(" ", 1)[0] + "…"


def classify_category(title, departments=None):
    title_text = plain_text(title).lower()
    department_text = " ".join(
        plain_text(value) for value in (departments or []) if value
    ).lower()

    def title_matches(*patterns):
        return any(re.search(pattern, title_text) for pattern in patterns)

    def context_matches(*patterns):
        searchable = f"{title_text} {department_text}"
        return any(re.search(pattern, searchable) for pattern in patterns)

    # High-precision physical warehouse and logistics titles. Generic words
    # such as "distribution" or "fulfillment" are deliberately insufficient.
    if title_matches(
        r"\bwarehouse\b", r"\bmaterial handler\b", r"\bpackage handler\b",
        r"\bpicker(?:/packer)?\b", r"\bpacker\b", r"\bforklift\b",
        r"\bshipping (?:and|&) receiving\b", r"\breceiving associate\b",
        r"\bfreight/receiving\b", r"\bdock worker\b", r"\bstocker\b",
        r"\binventory (?:associate|clerk|specialist|control)\b",
        r"\bfulfillment (?:associate|team member|specialist)\b",
        r"\bdashmart team member\b", r"\bdashmart site manager\b"
    ):
        return "Warehouse"
    if title_matches(r"\bpharmac(?:y|ist|ist technician)\b"):
        return "Pharmacy"
    if title_matches(
        r"\bregistered nurse\b", r"\bnurse\b", r"\btherapist\b",
        r"\bphysician\b", r"\bpatient care\b", r"\bphlebotomist\b",
        r"\bmedical (?:assistant|technician|technologist|coder|bill(?:er|ing))\b",
        r"\bdental (?:assistant|hygienist|technician)\b",
        r"\bclinical (?:specialist|coordinator|technician|researcher)\b",
        r"\bpsychologist\b", r"\bdiagnostic radiologic\b",
        r"\bmental health\b", r"\bsocial worker\b"
    ):
        return "Healthcare"
    if title_matches(
        r"\bbarista\b", r"\bcook\b", r"\bchef\b", r"\bkitchen\b",
        r"\bserver\b", r"\bfood service\b", r"\bdishwasher\b",
        r"\bcrew member\b", r"\brestaurant\b", r"\bshift leader\b",
        r"\bhost(?:ess)?\b", r"\bbusser\b", r"\bfood prepar(?:er|ation)\b"
    ):
        return "Food Service"
    if title_matches(
        r"\baccount executive\b", r"\bsales\b", r"\bbusiness development\b",
        r"\b(?:sales|account) development representative\b"
    ):
        return "Sales"
    if title_matches(
        r"\bcashier\b", r"\bretail\b", r"\bstore (?:associate|manager)\b",
        r"\bmerchandis(?:er|ing)\b", r"\bsales floor\b",
        r"\b(?:sales|stock|guest service) associate\b", r"\bteam member\b",
        r"\bpersonal shopper\b", r"\bgrocery\b", r"\bfront end associate\b"
    ):
        return "Retail"
    if title_matches(
        r"\bcustomer (?:service|support|care|success)\b",
        r"\bclient support\b", r"\bsupport (?:representative|specialist)\b",
        r"\bcall center\b"
    ):
        return "Customer Service"
    if title_matches(
        r"\bsoftware\b", r"\bdeveloper\b", r"\bdata (?:scientist|engineer)\b",
        r"\bcyber(?:security)?\b", r"\bmachine learning\b",
        r"\bsite reliability\b", r"\bdevops\b", r"\bcloud engineer\b",
        r"\bit (?:support|specialist|administrator|manager)\b",
        r"\btechnical support\b", r"\bvoip\b", r"\bfull[ -]?stack\b",
        r"\bfront[ -]?end\b", r"\bback[ -]?end\b",
        r"\bandroid (?:developer|engineer)\b", r"\bios (?:developer|engineer)\b",
        r"\b(?:security|platform|infrastructure|systems|solutions) engineer\b",
        r"\bmember of technical staff\b"
    ):
        return "Technology"
    if title_matches(
        r"\bmarketing\b", r"\bcontent (?:writer|manager|strategist)\b",
        r"\bpublic relations\b", r"\bbrand (?:manager|strategist)\b"
    ):
        return "Marketing"
    if title_matches(
        r"\baccountant\b", r"\baccounting\b", r"\bfinancial\b",
        r"\bfinance\b", r"\bpayroll\b", r"\bbookkeeper\b", r"\bfp&a\b"
    ):
        return "Finance"
    if title_matches(
        r"\bhuman resources\b", r"\bpeople operations\b", r"\brecruit(?:er|ing)\b",
        r"\btalent acquisition\b", r"\bhr (?:manager|generalist|specialist)\b"
    ):
        return "Human Resources"
    if title_matches(
        r"\bparalegal\b", r"\blegal\b", r"\battorney\b",
        r"\bcounsel\b", r"\bcompliance\b"
    ):
        return "Legal"
    if title_matches(
        r"\byouth program\b", r"\brecreation (?:assistant|aide|specialist)\b",
        r"\bcommunity (?:services?|outreach)\b", r"\bcase manager\b"
    ):
        return "Community & Social Services"
    if title_matches(
        r"\badministrative\b", r"\bexecutive assistant\b", r"\boffice manager\b",
        r"\breceptionist\b", r"\bdata entry\b", r"\boffice (?:assistant|clerk)\b",
        r"\bprogram assistant\b"
    ):
        return "Administrative"
    if title_matches(
        r"\bcivil engineer\b", r"\bmechanical engineer\b",
        r"\belectrical engineer\b", r"\bfield engineer\b",
        r"\bconstruction\b", r"\barchitect\b", r"\bsurveyor\b"
    ):
        return "Engineering & Construction"
    if context_matches(
        r"\boperations (?:associate|coordinator|specialist|manager)\b",
        r"\blogistics (?:associate|coordinator|specialist|manager)\b"
    ):
        return "Operations"
    if title_matches(
        r"\bteacher\b", r"\bteaching assistant\b", r"\binstructional\b",
        r"\btutor\b", r"\bschool counselor\b", r"\bprofessor\b"
    ):
        return "Education"
    if title_matches(
        r"\bhotel\b", r"\bhousekeep(?:er|ing)\b", r"\bfront desk\b",
        r"\bguest services?\b", r"\broom attendant\b", r"\bconcierge\b"
    ):
        return "Hospitality"
    if title_matches(
        r"\belectrician\b", r"\bplumber\b", r"\bwelder\b", r"\bcarpenter\b",
        r"\bhvac\b", r"\bmaintenance technician\b", r"\bapprentice\b",
        r"\b(?:aircraft |automotive |diesel )?mechanic\b", r"\bequipment repair\b"
    ):
        return "Skilled Trades"
    if title_matches(
        r"\bdelivery driver\b", r"\btruck driver\b", r"\bcdl\b",
        r"\bcourier\b", r"\btransportation\b", r"\bbus driver\b"
    ):
        return "Transportation"
    if title_matches(
        r"\bsecurity (?:officer|guard)\b", r"\bloss prevention\b",
        r"\basset protection\b"
    ):
        return "Security"
    if title_matches(
        r"\bproduction (?:associate|worker|operator)\b", r"\bmachine operator\b",
        r"\bassembler\b", r"\bmanufacturing\b"
    ):
        return "Manufacturing"
    if title_matches(
        r"\bproduct (?:manager|owner)\b", r"\bproduct operations\b"
    ):
        return "Product Management"
    if title_matches(
        r"\bproduct designer\b", r"\bux\b", r"\bui designer\b",
        r"\bgraphic designer\b", r"\bvisual designer\b", r"\bdesign lead\b"
    ):
        return "Design"
    if title_matches(
        r"\bproject manager\b", r"\bprogram manager\b", r"\bproject coordinator\b",
        r"\bprogram coordinator\b"
    ):
        return "Project & Program Management"
    if title_matches(
        r"\bpolice officer\b", r"\bcorrectional officer\b", r"\bfirefighter\b",
        r"\bemergency dispatcher\b", r"\bpublic safety\b"
    ):
        return "Public Safety"
    if title_matches(r"\bstore worker\b"):
        return "Retail"
    return "Other"


def valid_https_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme == "https" and bool(parsed.netloc)


def pay_text(job):
    minimum = job.get("salary_min")
    maximum = job.get("salary_max")
    period = job.get("salary_period")
    if minimum is None or maximum is None or not period:
        return "Not listed"
    return f"${minimum:g}-${maximum:g}/{period}"


def normalize_employment_type(value):
    cleaned = str(value or "").strip().rstrip(".")
    normalized = cleaned.lower()

    tokenized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()

    if tokenized in {"", "not listed", "not specified", "unknown", "n a"}:
        return None

    if (
        tokenized in {"part time", "parttime", "12 39 hours per week"}
        or re.search(r"\bpart\s*time\b", tokenized)
    ):
        return "Part-Time"

    if tokenized in {"full time", "fulltime"} or re.search(
        r"\bfull\s*time\b", tokenized
    ):
        return "Full-Time"

    if re.search(r"\b(?:intern|internship|co op|student trainee)\b", tokenized):
        return "Internship"

    if re.search(r"\b(?:seasonal|season|summer|holiday)\b", tokenized):
        return "Seasonal"

    if re.search(r"\b(?:temporary|temp|fixed term)\b", tokenized):
        return "Temporary"

    if re.search(r"\b(?:contract|contractor|1099)\b", tokenized):
        return "Contract"

    return cleaned or None


# Validation is shared across providers so trust requirements remain consistent.
def validate_record(job):
    required = (
        "title", "company", "location", "description",
        "experience", "category", "source", "external_job_id",
        "source_url", "last_verified_at"
    )
    missing = [field for field in required if not job.get(field)]
    if missing:
        raise ValueError(
            "missing required fields: " + ", ".join(missing)
        )
    if not valid_https_url(job["source_url"]):
        raise ValueError("source_url must be an HTTPS URL")
    if job.get("is_remote") not in (True, False, None):
        raise ValueError("is_remote must be true, false, or null")
    minimum = job.get("salary_min")
    maximum = job.get("salary_max")
    if (minimum is None) != (maximum is None):
        raise ValueError(
            "salary_min and salary_max must both be provided"
        )
    if minimum is not None and minimum > maximum:
        raise ValueError("salary_min cannot exceed salary_max")


def prepare_record(raw_job):
    validate_record(raw_job)
    job = dict(raw_job)
    job["employment_type"] = normalize_employment_type(
        job.get("employment_type")
    )
    if not job.get("application_deadline") and job.get("expires_at"):
        job["application_deadline"] = str(
            job["expires_at"]
        )[:10]
    job.update({
        "pay": pay_text(job),
        "schedule": job.get("employment_type") or "Not listed",
        "application_method": "employer_website",
        "application_url": job["source_url"],
        "employer_id": None,
        "status": "active",
        "verification_status": "verified",
        "link_status": "working",
        "last_link_checked_at": (
            job.get("last_verified_at") or utc_now()
        ),
        "is_remote": (
            None if job.get("is_remote") is None
            else int(job["is_remote"])
        )
    })
    return job


# Synchronization upserts normalized records and can mark missing listings stale
# without deleting historical application references.
def synchronize_records(
    database_path,
    records,
    completed_sources,
    mark_stale=False
):
    summary = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "expired": 0,
        "failed": 0
    }
    seen_keys = set()
    conn = get_connection(database_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    for index, raw_job in enumerate(records, start=1):
        try:
            job = prepare_record(raw_job)
            key = (job["source"], str(job["external_job_id"]))
            job["external_job_id"] = key[1]
            if key in seen_keys:
                raise ValueError("duplicate source and external_job_id")
            seen_keys.add(key)

            existing = cursor.execute(
                """
                SELECT *
                FROM jobs
                WHERE source = ?
                  AND external_job_id = ?
                """,
                key
            ).fetchone()
            values = [job.get(column) for column in SYNC_COLUMNS]

            if existing is None:
                placeholders = ", ".join("?" for _ in SYNC_COLUMNS)
                cursor.execute(
                    f"""
                    INSERT INTO jobs ({", ".join(SYNC_COLUMNS)})
                    VALUES ({placeholders})
                    """,
                    values
                )
                summary["inserted"] += 1
                continue

            changed = any(
                existing[column] != job.get(column)
                for column in SYNC_COLUMNS
            )
            if not changed:
                summary["skipped"] += 1
                continue

            assignments = ", ".join(
                f"{column} = ?" for column in SYNC_COLUMNS
            )
            record_job_changes(
                cursor,
                existing["id"],
                existing,
                {column: job.get(column) for column in SYNC_COLUMNS},
                "source_sync",
            )
            cursor.execute(
                f"""
                UPDATE jobs
                SET {assignments},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND employer_id IS NULL
                """,
                values + [existing["id"]]
            )
            summary["updated"] += cursor.rowcount
        except (KeyError, TypeError, ValueError) as error:
            summary["failed"] += 1
            print(f"Record {index} failed: {error}")

    if mark_stale:
        for source in completed_sources:
            source_keys = {
                external_id
                for seen_source, external_id in seen_keys
                if seen_source == source
            }
            existing_rows = cursor.execute(
                """
                SELECT *
                FROM jobs
                WHERE source = ?
                  AND employer_id IS NULL
                  AND verification_status = 'verified'
                """,
                (source,)
            ).fetchall()
            for row in existing_rows:
                if row["external_job_id"] in source_keys:
                    continue
                record_job_changes(
                    cursor,
                    row["id"],
                    row,
                    {"status": "closed", "verification_status": "expired", "link_status": "unavailable"},
                    "source_sync",
                )
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = 'closed',
                        verification_status = 'expired',
                        link_status = 'unavailable',
                        last_link_checked_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (row["id"],)
                )
                summary["expired"] += 1

    conn.commit()
    conn.close()
    return summary
