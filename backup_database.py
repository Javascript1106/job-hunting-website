"""Create and verify a consistent SQLite backup for PathForge."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from database import DB_NAME, resolve_database_path


def backup_database(database_path=DB_NAME, output_directory="backups"):
    source_path = Path(resolve_database_path(database_path))
    destination_directory = Path(output_directory)
    if not destination_directory.is_absolute():
        destination_directory = source_path.parent / destination_directory
    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = destination_directory / f"pathforge-{timestamp}.db"

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = target.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"Backup verification failed: integrity={integrity}, "
                f"foreign_key_issues={len(foreign_keys)}"
            )
    finally:
        target.close()
        source.close()

    return destination.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a verified PathForge database backup.")
    parser.add_argument("--database", default=DB_NAME)
    parser.add_argument("--output-directory", default="backups")
    arguments = parser.parse_args()
    print(backup_database(arguments.database, arguments.output_directory))
