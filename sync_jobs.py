"""Synchronize authorized external job sources into PathForge's normalized job records."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from database import DB_NAME, get_connection, initialize_database
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


def print_progress(message):
    """Write progress immediately while keeping the JSON report on stdout."""
    print(message, file=sys.stderr, flush=True)


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


def record_source_health(database_path, source_results):
    """Persist source failures and counts so administrators can act on them."""
    connection = get_connection(database_path)
    try:
        # A failed adapter may only know its generic provider name, while a
        # successful retry returns the board-specific source identifier. Clear
        # superseded failure aliases so recovered feeds do not keep generating
        # false administrator alerts.
        for result in source_results:
            if result.get("status") != "ok":
                continue
            connection.execute(
                """DELETE FROM catalog_sync_status
                   WHERE employer = ?
                     AND status = 'failed'
                     AND source <> ?""",
                (result.get("employer"), result.get("source")),
            )
        connection.executemany(
            """INSERT INTO catalog_sync_status
               (source, employer, status, fetched, imported,
                excluded_by_country, error, last_attempt_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(source, employer) DO UPDATE SET
                 status = excluded.status,
                 fetched = excluded.fetched,
                 imported = excluded.imported,
                 previous_imported = catalog_sync_status.imported,
                 excluded_by_country = excluded.excluded_by_country,
                 error = excluded.error,
                 last_attempt_at = CURRENT_TIMESTAMP""",
            [
                (
                    result.get("source", "Unknown"),
                    result.get("employer", "Unknown employer"),
                    result.get("status", "failed"),
                    result.get("fetched", 0),
                    result.get("imported", 0),
                    result.get("excluded_by_country", 0),
                    result.get("error"),
                )
                for result in source_results
            ],
        )
        connection.commit()
    finally:
        connection.close()


def catalog_health(database_path, source_results):
    """Return a compact post-sync health report for people operating the site."""
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    try:
        counts = connection.execute(
            """SELECT
                 SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
                 SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                 SUM(CASE WHEN status = 'active' AND
                    (last_verified_at IS NULL OR
                     last_verified_at < datetime('now', '-7 days'))
                     THEN 1 ELSE 0 END) AS stale,
                 SUM(CASE WHEN status = 'active' AND owner_user_id IS NULL
                    AND application_url IS NULL AND source_url IS NULL
                     THEN 1 ELSE 0 END) AS missing_application_link
               FROM jobs"""
        ).fetchone()
        current_keys = {
            (result.get("source"), result.get("employer"))
            for result in source_results
        }
        history = {
            (row["source"], row["employer"]): row
            for row in connection.execute(
                """SELECT source, employer, imported, previous_imported
                   FROM catalog_sync_status"""
            ).fetchall()
            if (row["source"], row["employer"]) in current_keys
        }
    finally:
        connection.close()

    failed_sources = [
        result["employer"]
        for result in source_results
        if result.get("status") == "failed"
    ]
    empty_sources = [
        result["employer"]
        for result in source_results
        if result.get("status") == "ok" and result.get("imported", 0) == 0
    ]
    large_drops = []
    for result in source_results:
        row = history.get((result.get("source"), result.get("employer")))
        if row is None or row["previous_imported"] is None:
            continue
        previous = row["previous_imported"]
        current = row["imported"]
        if previous >= 10 and current <= previous * 0.5:
            large_drops.append({
                "employer": result["employer"],
                "previous": previous,
                "current": current,
            })

    return {
        "active_jobs": counts["active"] or 0,
        "closed_jobs": counts["closed"] or 0,
        "stale_active_jobs": counts["stale"] or 0,
        "missing_application_links": counts["missing_application_link"] or 0,
        "failed_sources": failed_sources,
        "empty_sources": empty_sources,
        "large_source_drops": large_drops,
    }


# Each enabled adapter returns normalized records; the shared synchronizer owns writes.
def sync_all(mark_stale=False, progress=None):
    """Synchronize enabled sources and optionally report human-readable progress."""
    def report(message):
        if progress is not None:
            progress(message)

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

    enabled_sources = sum(
        1
        for source_type, _adapter in adapters
        for source_config in configuration.get(source_type, [])
        if enabled(source_config)
    )
    usajobs_config = configuration.get("usajobs", {})
    if enabled(usajobs_config):
        enabled_sources += 1
    current_source = 0

    for source_type, adapter in adapters:
        for source_config in configuration.get(source_type, []):
            if not enabled(source_config):
                continue
            current_source += 1
            employer = source_config.get("employer", "Unknown employer")
            report(
                f"[{current_source}/{enabled_sources}] Checking {employer} "
                f"({source_type})..."
            )
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
                report(
                    f"  Imported {len(imported)} U.S. jobs "
                    f"from {len(fetched)} fetched."
                )
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                source_results.append({
                    "source": source_type,
                    "employer": employer,
                    "fetched": 0,
                    "status": "failed",
                    "error": str(error)
                })
                report(f"  Source failed: {error}")

    if enabled(usajobs_config):
        current_source += 1
        report(
            f"[{current_source}/{enabled_sources}] Checking federal agencies "
            "(USAJOBS)..."
        )
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
            report(
                f"  Imported {len(imported)} U.S. jobs "
                f"from {len(fetched)} fetched."
            )
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            source_results.append({
                "source": "USAJOBS",
                "employer": "Federal agencies",
                "fetched": 0,
                "status": "failed",
                "error": str(error)
            })
            report(f"  Source failed: {error}")

    report("Updating the PathForge catalog...")
    summary = synchronize_records(
        BASE_DIR / DB_NAME,
        records,
        completed_sources,
        mark_stale=mark_stale
    )
    record_source_health(BASE_DIR / DB_NAME, source_results)
    summary["sources"] = source_results
    summary["catalog_health"] = catalog_health(
        BASE_DIR / DB_NAME, source_results
    )
    health = summary["catalog_health"]
    report(
        "Catalog update complete: "
        f"{summary.get('inserted', 0)} inserted, "
        f"{summary.get('updated', 0)} updated, "
        f"{summary.get('expired', 0)} expired, "
        f"{summary.get('failed', 0)} failed."
    )
    report(
        "Catalog health: "
        f"{health['active_jobs']} active, "
        f"{health['closed_jobs']} closed, "
        f"{health['stale_active_jobs']} stale, "
        f"{len(health['failed_sources'])} failed sources, "
        f"{len(health['empty_sources'])} empty sources, "
        f"{len(health['large_source_drops'])} large drops."
    )
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
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress live progress and print only the final JSON report."
    )
    arguments = parser.parse_args()
    progress_callback = None if arguments.quiet else print_progress
    print(json.dumps(
        sync_all(
            mark_stale=arguments.mark_stale,
            progress=progress_callback,
        ),
        indent=2
    ))
