"""Run a safe, observable PathForge catalog refresh for any scheduler."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from backup_database import backup_database
from sync_jobs import print_progress, sync_all


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_DIRECTORY = PROJECT_ROOT / "automation-logs"
DEFAULT_LOCK_PATH = PROJECT_ROOT / ".catalog-maintenance.lock"


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_report(report, log_directory):
    directory = Path(log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = directory / f"catalog-sync-{stamp}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def run_maintenance(
    *,
    log_directory=DEFAULT_LOG_DIRECTORY,
    lock_path=DEFAULT_LOCK_PATH,
    backup_func=backup_database,
    sync_func=sync_all,
    progress=print_progress,
):
    """Back up, synchronize, log health, and reject overlapping executions."""
    lock = Path(lock_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(
            "Catalog maintenance is already running. If no sync is active, "
            f"remove the stale lock file at {lock}."
        ) from error

    started_at = _utc_timestamp()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
            lock_file.write(f"pid={os.getpid()}\nstarted_at={started_at}\n")

        progress("Creating a verified database backup...")
        backup_path = backup_func()
        progress(f"Backup ready: {backup_path}")
        summary = sync_func(mark_stale=True, progress=progress)
        health = summary.get("catalog_health", {})
        failed_sources = health.get("failed_sources", [])
        large_drops = health.get("large_source_drops", [])
        report = {
            "status": "attention_required" if failed_sources or large_drops else "success",
            "started_at": started_at,
            "finished_at": _utc_timestamp(),
            "backup_path": str(backup_path),
            "summary": summary,
        }
        report_path = _write_report(report, log_directory)
        report["report_path"] = str(report_path)
        return report
    except Exception as error:
        report = {
            "status": "failed",
            "started_at": started_at,
            "finished_at": _utc_timestamp(),
            "error": str(error),
        }
        report_path = _write_report(report, log_directory)
        raise RuntimeError(
            f"Catalog maintenance failed. Review {report_path}: {error}"
        ) from error
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Back up and refresh the PathForge job catalog safely."
    )
    parser.add_argument(
        "--log-directory",
        default=str(DEFAULT_LOG_DIRECTORY),
        help="Directory for timestamped JSON maintenance reports.",
    )
    arguments = parser.parse_args()
    try:
        report = run_maintenance(log_directory=arguments.log_directory)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
