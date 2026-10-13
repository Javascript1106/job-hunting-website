"""Conservatively verify stale public job links and close definitive dead ends."""

import argparse
import html
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backup_database import backup_database
from database import DB_NAME, get_connection, initialize_database


CLOSED_MARKERS = (
    "job is no longer available",
    "job is no longer active",
    "position has been filled",
    "job posting has expired",
    "this job has expired",
    "position is no longer available",
)


def plain_page_text(payload):
    text = payload.decode("utf-8", errors="ignore")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip().lower()


def verify_listing(job, timeout=15):
    url = job["application_url"] or job["source_url"]
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; PathForgeCatalogVerifier/1.0; "
                "+https://pathforge.example)"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            page_text = plain_page_text(response.read(2_000_000))
    except HTTPError as error:
        if error.code in {404, 410}:
            return {"id": job["id"], "result": "closed", "http_status": error.code}
        return {"id": job["id"], "result": "blocked", "http_status": error.code}
    except (OSError, TimeoutError, URLError) as error:
        return {"id": job["id"], "result": "error", "error": str(error)}

    if any(marker in page_text for marker in CLOSED_MARKERS):
        result = "closed"
    elif job["title"].strip().lower() in page_text:
        result = "verified"
    else:
        result = "reachable"
    return {"id": job["id"], "result": result, "http_status": status}


def stale_jobs(database_path, stale_days, limit=None):
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    try:
        query = """SELECT id, title, company, source_url, application_url
                   FROM jobs
                   WHERE status = 'active' AND owner_user_id IS NULL
                     AND COALESCE(application_url, source_url) IS NOT NULL
                     AND (last_verified_at IS NULL OR
                          last_verified_at < datetime('now', ?))
                   ORDER BY COALESCE(last_verified_at, ''), company, title"""
        parameters = [f"-{stale_days} days"]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(max(0, int(limit)))
        return [
            dict(row)
            for row in connection.execute(query, parameters).fetchall()
        ]
    finally:
        connection.close()


def apply_results(database_path, results):
    connection = get_connection(database_path)
    try:
        closed_ids = [row["id"] for row in results if row["result"] == "closed"]
        verified_ids = [row["id"] for row in results if row["result"] == "verified"]
        connection.executemany(
            """UPDATE jobs SET status = 'closed', updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'active'""",
            [(job_id,) for job_id in closed_ids],
        )
        connection.executemany(
            """UPDATE jobs SET last_verified_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'active'""",
            [(job_id,) for job_id in verified_ids],
        )
        connection.commit()
    finally:
        connection.close()


def verify_stale_links(
    database_path=DB_NAME, stale_days=7, workers=8, apply=False, limit=None
):
    initialize_database(database_path)
    jobs = stale_jobs(database_path, stale_days, limit=limit)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as executor:
        results = list(executor.map(verify_listing, jobs))
    backup = None
    if apply and any(row["result"] in {"closed", "verified"} for row in results):
        backup = str(backup_database(database_path))
        apply_results(database_path, results)
    counts = {
        outcome: sum(row["result"] == outcome for row in results)
        for outcome in ("verified", "closed", "reachable", "blocked", "error")
    }
    return {
        "checked": len(results),
        "applied": apply,
        "backup": backup,
        **counts,
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify stale employer links without closing ambiguous results."
    )
    parser.add_argument("--database", default=DB_NAME)
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up the database, close definitive dead links, and refresh confirmed jobs.",
    )
    arguments = parser.parse_args()
    print(json.dumps(verify_stale_links(
        database_path=arguments.database,
        stale_days=arguments.stale_days,
        workers=arguments.workers,
        apply=arguments.apply,
        limit=arguments.limit,
    ), indent=2))
