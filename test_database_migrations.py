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

        self.assertEqual(applied, [1, 2, 3, 4, 5, 6, 7, 8])
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
                (8, "close_bundled_sample_jobs"),
            ],
        )

    def test_bundled_sample_jobs_are_not_public(self):
        database.initialize_database(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """INSERT INTO jobs
                   (title, company, location, pay, description, schedule,
                    experience, category, application_method, status)
                   VALUES ('Crew Member', 'Taco Bell', 'Saratoga Springs, UT',
                           '$12-$15/hr', 'Sample listing', 'Part-Time',
                           'No experience required', 'Food Service',
                           'pathforge', 'active')"""
            )
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = 8"
            )
            connection.commit()
        finally:
            connection.close()

        database.initialize_database(self.database_path)
        connection = sqlite3.connect(self.database_path)
        status = connection.execute(
            """SELECT status FROM jobs
               WHERE title = 'Crew Member' AND company = 'Taco Bell'"""
        ).fetchone()[0]
        connection.close()

        self.assertEqual(status, "closed")

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
