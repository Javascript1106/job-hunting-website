"""Generate aggregate, privacy-safe catalog coverage and quality reports."""

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from database import DB_NAME, get_connection
from job_discovery import US_STATE_CODES, age_eligibility, us_state_codes


def build_catalog_insights(database_path=DB_NAME):
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    try:
        jobs = [
            dict(row)
            for row in connection.execute(
                """SELECT title, company, location, pay, description,
                          requirements, schedule, category, employment_type,
                          salary_min, salary_max, application_deadline,
                          application_url, source_url
                   FROM jobs
                   WHERE status = 'active' AND owner_user_id IS NULL"""
            ).fetchall()
        ]
    finally:
        connection.close()

    state_counts = {code.upper(): 0 for code in US_STATE_CODES}
    confirmed_teen_by_state = {code.upper(): 0 for code in US_STATE_CODES}
    possible_teen_by_state = {code.upper(): 0 for code in US_STATE_CODES}
    employers = Counter()
    categories = Counter()
    unlocated = 0
    quality = Counter()
    teen_totals = Counter()

    for job in jobs:
        employers[job.get("company") or "Unknown employer"] += 1
        categories[job.get("category") or "Uncategorized"] += 1
        states = us_state_codes(job.get("location"))
        if not states:
            unlocated += 1
        for state in states:
            state_counts[state] += 1

        eligibility = age_eligibility(job)["age_eligibility"]
        teen_totals[eligibility] += 1
        if eligibility in {"confirmed_14_15", "confirmed_16_17"}:
            for state in states:
                confirmed_teen_by_state[state] += 1
        elif eligibility == "possible_teen_fit":
            for state in states:
                possible_teen_by_state[state] += 1

        pay = str(job.get("pay") or "").strip().lower()
        if job.get("salary_min") is None and job.get("salary_max") is None and (
            not pay or pay == "not listed"
        ):
            quality["missing_pay"] += 1
        if not str(job.get("description") or "").strip():
            quality["missing_description"] += 1
        if not str(job.get("requirements") or "").strip():
            quality["missing_requirements"] += 1
        if not str(job.get("application_deadline") or "").strip():
            quality["missing_deadline"] += 1
        if not (job.get("application_url") or job.get("source_url")):
            quality["missing_application_link"] += 1
        if not str(job.get("employment_type") or job.get("schedule") or "").strip():
            quality["missing_schedule"] += 1

    state_rows = [
        {
            "state": state,
            "active_jobs": state_counts[state],
            "confirmed_teen_jobs": confirmed_teen_by_state[state],
            "possible_teen_jobs": possible_teen_by_state[state],
        }
        for state in sorted(state_counts)
    ]
    lowest_coverage = sorted(
        state_rows,
        key=lambda row: (
            row["active_jobs"], row["confirmed_teen_jobs"], row["state"]
        ),
    )[:15]
    no_confirmed_teen = [
        row["state"] for row in state_rows if row["confirmed_teen_jobs"] == 0
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active_jobs": len(jobs),
        "jobs_without_specific_state": unlocated,
        "teen_jobs": {
            "confirmed_age_14_15": teen_totals["confirmed_14_15"],
            "confirmed_age_16_17": teen_totals["confirmed_16_17"],
            "possible_age_not_stated": teen_totals["possible_teen_fit"],
            "states_without_confirmed_teen_jobs": no_confirmed_teen,
        },
        "listing_quality_gaps": dict(sorted(quality.items())),
        "top_employers": [
            {"employer": name, "active_jobs": count}
            for name, count in employers.most_common(15)
        ],
        "top_categories": [
            {"category": name, "active_jobs": count}
            for name, count in categories.most_common(15)
        ],
        "lowest_state_coverage": lowest_coverage,
        "state_coverage": state_rows,
    }


def _markdown_report(insights):
    teen = insights["teen_jobs"]
    lines = [
        "# PathForge catalog insights",
        "",
        f"Generated: {insights['generated_at']}",
        f"Active public jobs: {insights['active_jobs']}",
        f"Jobs without a specific state: {insights['jobs_without_specific_state']}",
        "",
        "## Teen-job coverage",
        "",
        f"- Confirmed for ages 14–15: {teen['confirmed_age_14_15']}",
        f"- Confirmed for ages 16–17: {teen['confirmed_age_16_17']}",
        f"- Possible teen fit, age not stated: {teen['possible_age_not_stated']}",
        "- States without a confirmed teen job: "
        + (", ".join(teen["states_without_confirmed_teen_jobs"]) or "None"),
        "",
        "## Lowest state coverage",
        "",
        "| State | Active jobs | Confirmed teen | Possible teen |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row['state']} | {row['active_jobs']} | "
        f"{row['confirmed_teen_jobs']} | {row['possible_teen_jobs']} |"
        for row in insights["lowest_state_coverage"]
    )
    lines.extend(["", "## Listing-quality gaps", ""])
    lines.extend(
        f"- {name.replace('_', ' ').title()}: {count}"
        for name, count in insights["listing_quality_gaps"].items()
    )
    lines.extend(["", "## Largest employers", ""])
    lines.extend(
        f"- {row['employer']}: {row['active_jobs']}"
        for row in insights["top_employers"]
    )
    return "\n".join(lines) + "\n"


def write_catalog_insights(database_path=DB_NAME, log_directory="automation-logs"):
    insights = build_catalog_insights(database_path)
    directory = Path(log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "catalog-insights-latest.json"
    markdown_path = directory / "catalog-insights-latest.md"
    json_path.write_text(json.dumps(insights, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown_report(insights), encoding="utf-8")
    return {
        "json_report": str(json_path.resolve()),
        "markdown_report": str(markdown_path.resolve()),
        "active_jobs": insights["active_jobs"],
        "states_without_confirmed_teen_jobs": insights["teen_jobs"][
            "states_without_confirmed_teen_jobs"
        ],
        "lowest_state_coverage": insights["lowest_state_coverage"],
        "listing_quality_gaps": insights["listing_quality_gaps"],
    }
