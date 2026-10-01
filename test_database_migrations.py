"""Regression tests for the versioned SQLite migration runner."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import database


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(
            Path(self.temporary_directory.name) / "migration-tests.db"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_fresh_database_receives_versioned_baseline(self):
        applied = database.initialize_database(self.database_path)

        connection = sqlite3.connect(self.database_path)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        migration = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        connection.close()

        self.assertEqual(applied, [1, 2, 3, 4, 5, 6, 7])
        self.assertIn("users", tables)
        self.assertIn("jobs", tables)
        self.assertIn("auth_attempts", tables)
        self.assertEqual(
            migration,
            [
                (1, "baseline_pathforge_schema"),
                (2, "public_job_catalog_indexes"),
                (3, "saved_search_parity_and_job_history"),
                (4, "repair_application_history_integrity"),
                (5, "saved_search_application_feature"),
                (6, "catalog_sync_status"),
                (7, "catalog_sync_comparison"),
            ],
        )

    def test_completed_migration_is_not_reapplied(self):
        database.initialize_database(self.database_path)

        self.assertEqual(database.initialize_database(self.database_path), [])
        connection = sqlite3.connect(self.database_path)
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(migration_count, 1)


if __name__ == "__main__":
    unittest.main()
