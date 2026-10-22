"""Run free, local PathForge operational checks without exposing private data."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backup_database import backup_database
from catalog_insights import build_catalog_insights
from database import DB_NAME, get_connection, initialize_database, resolve_database_path
from verify_job_links import verify_stale_links


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_DIRECTORY = PROJECT_ROOT / "automation-logs"
DEFAULT_LOCK_PATH = PROJECT_ROOT / ".site-maintenance.lock"
BACKUP_MAX_AGE = timedelta(days=8)
LOCK_MAX_AGE = timedelta(hours=2)


def _utc_now():
    return datetime.now(timezone.utc)


def _atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def _latest_backup(database_path):
    directory = Path(resolve_database_path(database_path)).parent / "backups"
    candidates = sorted(directory.glob("pathforge-*.db"), key=lambda path: path.stat().st_mtime)
    return candidates[-1] if candidates else None


def _backup_is_valid(path):
    try:
        connection = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
        try:
            return (
                connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                and not connection.execute("PRAGMA foreign_key_check").fetchall()
            )
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False


def ensure_fresh_backup(database_path=DB_NAME, backup_func=backup_database):
    latest = _latest_backup(database_path)
    now = _utc_now()
    if latest:
        modified = datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc)
        if now - modified <= BACKUP_MAX_AGE and _backup_is_valid(latest):
            return {"created": False, "path": str(latest.resolve()), "age_days": (now - modified).days}
    created = Path(backup_func(database_path)).resolve()
    return {"created": True, "path": str(created), "age_days": 0}


def _acquire_lock(lock_path):
    lock = Path(lock_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        age = _utc_now() - datetime.fromtimestamp(lock.stat().st_mtime, timezone.utc)
        if age <= LOCK_MAX_AGE:
            raise RuntimeError(f"Site maintenance is already running. Lock: {lock}")
        lock.unlink(missing_ok=True)
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f"pid={os.getpid()}\nstarted_at={_utc_now().isoformat(timespec='seconds')}\n")
    return lock


def inspect_and_clean_database(database_path=DB_NAME):
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        expired_sessions = connection.execute(
            "SELECT COUNT(*) FROM user_sessions WHERE expires_at <= ?",
            (_utc_now().isoformat(),),
        ).fetchone()[0]
        connection.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (_utc_now().isoformat(),))
        old_attempts = connection.execute(
            "SELECT COUNT(*) FROM auth_attempts WHERE created_at < datetime('now', '-30 days')"
        ).fetchone()[0]
        connection.execute("DELETE FROM auth_attempts WHERE created_at < datetime('now', '-30 days')")
        failed_logins = connection.execute(
            """SELECT COUNT(*) AS attempts, COUNT(DISTINCT ip_hash) AS sources
               FROM auth_attempts
               WHERE action = 'login' AND succeeded = 0
                 AND created_at >= datetime('now', '-7 days')"""
        ).fetchone()
        job_counts = connection.execute(
            """SELECT
                   SUM(CASE WHEN status = 'active' AND owner_user_id IS NULL THEN 1 ELSE 0 END) AS active,
                   SUM(CASE WHEN status = 'closed' AND owner_user_id IS NULL THEN 1 ELSE 0 END) AS closed
               FROM jobs"""
        ).fetchone()
        source_rows = connection.execute(
            """SELECT source, employer, status, fetched, imported, error, last_attempt_at
               FROM catalog_sync_status ORDER BY employer, source"""
        ).fetchall()
        connection.commit()
    finally:
        connection.close()

    failed_sources = [
        {"source": row["source"], "employer": row["employer"], "last_attempt_at": row["last_attempt_at"]}
        for row in source_rows if row["status"] == "failed"
    ]
    latest_sync = max((row["last_attempt_at"] for row in source_rows), default=None)
    return {
        "integrity": integrity,
        "foreign_key_issues": foreign_key_issues,
        "expired_sessions_removed": expired_sessions,
        "old_auth_attempts_removed": old_attempts,
        "failed_login_attempts_7_days": int(failed_logins["attempts"] or 0),
        "failed_login_source_hashes_7_days": int(failed_logins["sources"] or 0),
        "active_public_jobs": int(job_counts["active"] or 0),
        "closed_public_jobs": int(job_counts["closed"] or 0),
        "configured_sources": len(source_rows),
        "failed_sources": failed_sources,
        "latest_source_attempt_at": latest_sync,
    }


def _markdown(report):
    database = report["database"]
    teen = report["catalog"]["teen_jobs"]
    links = report["link_check"]
    return "\n".join([
        "# PathForge showcase readiness",
        "",
        f"Generated: {report['generated_at']}",
        f"Status: {report['status']}",
        "",
        "## Catalog",
        "",
        f"- Active public jobs: {database['active_public_jobs']}",
        f"- Closed public jobs: {database['closed_public_jobs']}",
        f"- Configured sources: {database['configured_sources']}",
        f"- Failed sources: {len(database['failed_sources'])}",
        f"- Last source attempt: {database['latest_source_attempt_at'] or 'Not recorded'}",
        "",
        "## Teen and state coverage",
        "",
        f"- Confirmed ages 14–15: {teen['confirmed_age_14_15']}",
        f"- Confirmed ages 16–17: {teen['confirmed_age_16_17']}",
        f"- States without confirmed teen jobs: {', '.join(teen['states_without_confirmed_teen_jobs']) or 'None'}",
        "",
        "## Maintenance and security",
        "",
        f"- Database integrity: {database['integrity']}",
        f"- Foreign-key issues: {database['foreign_key_issues']}",
        f"- Expired sessions removed: {database['expired_sessions_removed']}",
        f"- Failed login attempts in 7 days: {database['failed_login_attempts_7_days']}",
        f"- Stale links checked safely: {links['checked']}",
        f"- Definitively closed links requiring review: {links['closed']}",
        f"- Verified backup: {report['backup']['path']}",
        "",
    ])


def run_site_maintenance(
    database_path=DB_NAME,
    log_directory=DEFAULT_LOG_DIRECTORY,
    lock_path=DEFAULT_LOCK_PATH,
    backup_func=backup_database,
    link_check_func=None,
):
    initialize_database(database_path)
    lock = _acquire_lock(lock_path)
    started = _utc_now()
    try:
        backup = ensure_fresh_backup(database_path, backup_func=backup_func)
        database_report = inspect_and_clean_database(database_path)
        insights = build_catalog_insights(database_path)
        check_links = link_check_func or (lambda: verify_stale_links(
            database_path=database_path, stale_days=7, workers=4, apply=False, limit=25
        ))
        links = check_links()
        attention = bool(
            database_report["integrity"] != "ok"
            or database_report["foreign_key_issues"]
            or database_report["active_public_jobs"] == 0
            or database_report["failed_sources"]
            or links.get("closed", 0)
        )
        report = {
            "status": "attention_required" if attention else "success",
            "generated_at": _utc_now().isoformat(timespec="seconds"),
            "started_at": started.isoformat(timespec="seconds"),
            "backup": backup,
            "database": database_report,
            "catalog": insights,
            "link_check": links,
        }
        directory = Path(log_directory)
        stamp = _utc_now().strftime("%Y%m%d-%H%M%S")
        _atomic_json(directory / "site-readiness-latest.json", report)
        _atomic_json(directory / f"site-maintenance-{stamp}.json", report)
        markdown = directory / "site-readiness-latest.md"
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(_markdown(report), encoding="utf-8")
        report["json_report"] = str((directory / "site-readiness-latest.json").resolve())
        report["markdown_report"] = str(markdown.resolve())
        return report
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Run local PathForge site maintenance and readiness checks.")
    parser.add_argument("--database", default=DB_NAME)
    parser.add_argument("--log-directory", default=str(DEFAULT_LOG_DIRECTORY))
    arguments = parser.parse_args()
    try:
        report = run_site_maintenance(arguments.database, arguments.log_directory)
    except Exception as error:
        print(f"Site maintenance failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, default=str))
    # A completed check is a successful scheduled-task run. Review status lives
    # in the report so Task Scheduler does not mislabel an actionable report as
    # a broken automation.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
