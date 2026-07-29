from urllib.parse import quote

from .common import (
    classify_category,
    concise_summary,
    fetch_json,
    plain_text,
    utc_now
)


def salary_fields(posting):
    salary = posting.get("salaryRange") or {}
    currency = str(salary.get("currency") or "").upper()
    minimum = salary.get("min")
    maximum = salary.get("max")
    interval = str(salary.get("interval") or "").lower()
    periods = {
        "per-hour-salary": "hour",
        "per-year-salary": "year",
        "hour": "hour",
        "year": "year"
    }
    if (
        currency not in ("", "USD")
        or not isinstance(minimum, (int, float))
        or not isinstance(maximum, (int, float))
        or interval not in periods
    ):
        return None, None, None
    return float(minimum), float(maximum), periods[interval]


def fetch_jobs(configuration):
    employer = configuration["employer"].strip()
    site = configuration["site"].strip()
    source = f"Lever:{site}"
    url = (
        "https://api.lever.co/v0/postings/"
        f"{quote(site, safe='')}?mode=json"
    )
    postings = fetch_json(url)
    records = []

    for posting in postings:
        categories = posting.get("categories") or {}
        title = plain_text(posting.get("text"))
        location = plain_text(categories.get("location"))
        workplace = str(posting.get("workplaceType") or "").lower()
        if not location and workplace == "remote":
            location = "Remote"
        location = location or "Location not listed"
        is_remote = {
            "remote": True,
            "on-site": False,
            "onsite": False,
            "hybrid": False
        }.get(workplace)
        if configuration.get("remote_only") and is_remote is not True:
            continue
        employment_type = (
            plain_text(categories.get("commitment")) or None
        )
        department_values = [
            categories.get("team"),
            categories.get("department")
        ]
        minimum, maximum, period = salary_fields(posting)
        fallback = (
            f"Official {employer} posting for {title}. "
            "See the employer listing for complete requirements."
        )

        records.append({
            "title": title,
            "company": employer,
            "location": location,
            "description": concise_summary(
                posting.get("descriptionPlain")
                or posting.get("description"),
                fallback
            ),
            "experience": "Not listed",
            "category": classify_category(
                title,
                [value for value in department_values if value]
            ),
            "employment_type": employment_type,
            "is_remote": is_remote,
            "salary_min": minimum,
            "salary_max": maximum,
            "salary_period": period,
            "source": source,
            "external_job_id": str(posting["id"]),
            "source_url": (
                posting.get("hostedUrl")
                or posting.get("applyUrl")
            ),
            "posted_at": None,
            "expires_at": None,
            "last_verified_at": utc_now()
        })

    maximum = int(configuration.get("max_jobs", 250))
    return source, records[:maximum]
