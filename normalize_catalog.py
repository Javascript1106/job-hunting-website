"""Safely improve category and schedule metadata on existing catalog jobs."""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from database import DB_NAME, get_connection
from job_sources.common import classify_category, normalize_employment_type


BASE_DIR = Path(__file__).resolve().parent


def normalize_catalog(database_path, apply=False):
    connection = get_connection(database_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT id, title, description, category, employment_type, schedule
           FROM jobs WHERE status = 'active' AND owner_user_id IS NULL"""
    ).fetchall()
    updates = []
    category_changes = 0
    type_changes = 0
    for row in rows:
        category = row["category"] or "Other"
        if category == "Other":
            category = classify_category(row["title"], [row["description"] or ""])
        employment_type = normalize_employment_type(
            row["employment_type"] or row["schedule"]
        )
        if category != (row["category"] or "Other"):
            category_changes += 1
        if employment_type != row["employment_type"]:
            type_changes += 1
        if category != row["category"] or employment_type != row["employment_type"]:
            updates.append((category, employment_type, employment_type or "Not listed", row["id"]))

    backup_path = None
    if apply and updates:
        backup_dir = BASE_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"pathforge-before-normalization-{stamp}.db"
        connection.close()
        shutil.copy2(database_path, backup_path)
        connection = get_connection(database_path)
        connection.executemany(
            """UPDATE jobs SET category = ?, employment_type = ?, schedule = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            updates,
        )
        connection.commit()
    connection.close()
    return {
        "active_jobs_scanned": len(rows),
        "jobs_changed": len(updates),
        "category_changes": category_changes,
        "employment_type_changes": type_changes,
        "applied": apply,
        "backup": str(backup_path) if backup_path else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up the database and apply changes.")
    arguments = parser.parse_args()
    result = normalize_catalog(BASE_DIR / DB_NAME, apply=arguments.apply)
    for key, value in result.items():
        print(f"{key}: {value}")
