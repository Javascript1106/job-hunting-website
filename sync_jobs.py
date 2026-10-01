"""Synchronize authorized external job sources into PathForge's normalized job records."""

import argparse
import json
import os
from pathlib import Path

from database import DB_NAME, initialize_database
from job_sources import (
    ashby,
    greenhouse,
    lever,
    recruitee,
    smartrecruiters,
    usajobs,
    workable,
    workday,
)
from job_sources.common import synchronize_records
from job_discovery import _is_canada_location, _is_us_location
from local_env import load_local_environment


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "job_sources.json"


def enabled(configuration):
    return configuration.get("enabled", True)


def filter_catalog_countries(records, countries, verified_countries=None):
    """Keep only listings explicitly available in configured catalog countries."""
    allowed = {str(country).strip().upper() for country in countries}
    if not allowed:
        return list(records)
    verified = {
        str(country).strip().upper()
        for country in (verified_countries or [])
    }
    if verified and verified <= allowed:
        return list(records)
    filtered = []
    for record in records:
        location = record.get("location")
        if "US" in allowed and _is_us_location(location):
            filtered.append(record)
        elif "CA" in allowed and _is_canada_location(location):
            filtered.append(record)
    return filtered


# Each enabled adapter returns normalized records; the shared synchronizer owns writes.
def sync_all(mark_stale=False):
    os.chdir(BASE_DIR)
    load_local_environment(BASE_DIR / ".env")
    initialize_database()

    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        configuration = json.load(config_file)
    catalog_countries = configuration.get("catalog", {}).get(
        "countries", []
    )

    records = []
    completed_sources = set()
    source_results = []
    adapters = (
        ("greenhouse", greenhouse.fetch_jobs),
        ("lever", lever.fetch_jobs),
        ("smartrecruiters", smartrecruiters.fetch_jobs),
        ("ashby", ashby.fetch_jobs),
        ("recruitee", recruitee.fetch_jobs),
        ("workable", workable.fetch_jobs),
        ("workday", workday.fetch_jobs),
    )

    for source_type, adapter in adapters:
        for source_config in configuration.get(source_type, []):
            if not enabled(source_config):
                continue
            employer = source_config.get("employer", "Unknown employer")
            try:
                source, fetched = adapter(source_config)
                imported = filter_catalog_countries(
                    fetched,
                    catalog_countries,
                    source_config.get("country_codes"),
                )
                records.extend(imported)
                completed_sources.add(source)
                source_results.append({
                    "source": source,
                    "employer": employer,
                    "fetched": len(fetched),
                    "imported": len(imported),
                    "excluded_by_country": len(fetched) - len(imported),
                    "status": "ok"
                })
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                source_results.append({
                    "source": source_type,
                    "employer": employer,
                    "fetched": 0,
                    "status": "failed",
                    "error": str(error)
                })

    usajobs_config = configuration.get("usajobs", {})
    if enabled(usajobs_config):
        try:
            source, fetched = usajobs.fetch_jobs(usajobs_config)
            imported = filter_catalog_countries(
                fetched, catalog_countries
            )
            records.extend(imported)
            completed_sources.add(source)
            source_results.append({
                "source": source,
                "employer": "Federal agencies",
                "fetched": len(fetched),
                "imported": len(imported),
                "excluded_by_country": len(fetched) - len(imported),
                "status": "ok"
            })
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            source_results.append({
                "source": "USAJOBS",
                "employer": "Federal agencies",
                "fetched": 0,
                "status": "failed",
                "error": str(error)
            })

    summary = synchronize_records(
        BASE_DIR / DB_NAME,
        records,
        completed_sources,
        mark_stale=mark_stale
    )
    summary["sources"] = source_results
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize authorized Greenhouse, Lever, "
            "SmartRecruiters, Ashby, Recruitee, Workable, "
            "Workday, and USAJOBS listings "
            "into PathForge."
        )
    )
    parser.add_argument(
        "--mark-stale",
        action="store_true",
        help=(
            "Expire missing listings, but only for sources that "
            "completed successfully during this run."
        )
    )
    arguments = parser.parse_args()
    print(json.dumps(
        sync_all(mark_stale=arguments.mark_stale),
        indent=2
    ))
