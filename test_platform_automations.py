"""Tests for non-destructive operational and account automations."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import database
from platform_automations import run_platform_automations


class PlatformAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "automations.db"
        database.initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_risky_and_old_jobs_are_flagged_but_never_closed(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """INSERT INTO jobs
               (title, company, location, pay, description, schedule, experience,
                category, status, posted_at)
               VALUES ('Assistant', 'Example', 'Utah',
                       'Pay listed', 'Contact us on Telegram and buy equipment',
                       'Part-time', 'Entry level', 'Other', 'active',
                       datetime('now', '-150 days'))"""
        )
        job_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.commit(); connection.close()
        report = run_platform_automations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        flags = connection.execute(
            "SELECT flag_type FROM automation_review_flags WHERE job_id = ? AND status = 'open'",
            (job_id,),
        ).fetchall()
        status = connection.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
        connection.close()
        self.assertEqual(status, "active")
        self.assertEqual({row[0] for row in flags}, {"suspicious_listing", "ghost_listing"})
        self.assertEqual(report["open_review_flags"], 2)

    def test_dismissed_flag_stays_dismissed_while_signal_remains(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """INSERT INTO jobs
               (title, company, location, pay, description, schedule, experience,
                category, status)
               VALUES ('Assistant', 'Example', 'Utah', 'Pay listed',
                       'Contact us via Telegram', 'Part-time', 'Entry level',
                       'Other', 'active')"""
        )
        connection.commit(); connection.close()
        run_platform_automations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "UPDATE automation_review_flags SET status = 'dismissed'"
        )
        connection.commit(); connection.close()
        run_platform_automations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        status = connection.execute(
            "SELECT status FROM automation_review_flags"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(status, "dismissed")

    def test_recovered_source_clears_unread_operations_alert(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, 'admin')",
            ("admin", "admin@example.com", "unused"),
        )
        connection.execute(
            """INSERT INTO catalog_sync_status
               (source, employer, status, fetched, imported,
                excluded_by_country, error)
               VALUES ('test', 'Example', 'failed', 0, 0, 0, 'offline')"""
        )
        connection.commit(); connection.close()
        run_platform_automations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE event_key LIKE 'admin-operations:%'"
            ).fetchone()[0],
            1,
        )
        connection.execute(
            "UPDATE catalog_sync_status SET status = 'ok', error = NULL"
        )
        connection.commit(); connection.close()
        run_platform_automations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        remaining = connection.execute(
            "SELECT COUNT(*) FROM notifications WHERE event_key LIKE 'admin-operations:%'"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(remaining, 0)

    def test_quality_alert_only_counts_severe_missing_details(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, 'admin')",
            ("admin", "admin@example.com", "unused"),
        )
        connection.execute(
            """INSERT INTO jobs
               (title, company, location, pay, description, requirements,
                schedule, experience, category, status, salary_min,
                application_deadline)
               VALUES ('Severe gap', 'Example', 'Utah', 'Not listed',
                       'Description', '', 'Part-time', 'Entry level', 'Other',
                       'active', NULL, NULL),
                      ('Only pay missing', 'Example', 'Utah', 'Not listed',
                       'Description', 'Must be 16.', 'Part-time', 'Entry level',
                       'Other', 'active', NULL, '2026-12-31')"""
        )
        connection.commit(); connection.close()
        run_platform_automations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        message = connection.execute(
            "SELECT message FROM notifications WHERE event_key LIKE 'quality-review:%'"
        ).fetchone()[0]
        connection.close()
        self.assertIn("1 active listing", message)
        self.assertIn("pay, requirements, and a deadline", message)


if __name__ == "__main__":
    unittest.main()
