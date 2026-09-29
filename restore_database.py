"""Validate and restore a PathForge SQLite backup with an automatic safety copy."""

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from database import DB_NAME, resolve_database_path


def validate_backup(path):
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("The selected backup failed SQLite integrity validation.")
        issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        if issues:
            raise RuntimeError(f"The selected backup contains {len(issues)} foreign-key issue(s).")
        required = {"users", "jobs", "applications", "schema_migrations"}
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not required <= tables:
            raise RuntimeError("The selected file is not a complete PathForge database backup.")
    finally:
        connection.close()


def restore_database(backup_path, database_path=DB_NAME, confirm=False):
    if not confirm:
        raise RuntimeError("Restore requires the explicit --confirm option.")
    backup = Path(backup_path).resolve()
    destination = Path(resolve_database_path(database_path))
    if not backup.is_file() or backup == destination:
        raise RuntimeError("Choose an existing backup file different from the live database.")
    validate_backup(backup)

    safety_directory = destination.parent / "backups"
    safety_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safety_copy = safety_directory / f"pre-restore-{timestamp}.db"
    if destination.exists():
        current = sqlite3.connect(destination)
        safety = sqlite3.connect(safety_copy)
        try:
            current.backup(safety)
        finally:
            safety.close()
            current.close()

    temporary = destination.with_suffix(destination.suffix + ".restore")
    shutil.copy2(backup, temporary)
    temporary.replace(destination)
    return destination, safety_copy if safety_copy.exists() else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore a verified PathForge database backup.")
    parser.add_argument("backup")
    parser.add_argument("--database", default=DB_NAME)
    parser.add_argument("--confirm", action="store_true")
    arguments = parser.parse_args()
    restored, safety = restore_database(arguments.backup, arguments.database, arguments.confirm)
    print(f"Restored: {restored}")
    if safety:
        print(f"Previous database backup: {safety}")
