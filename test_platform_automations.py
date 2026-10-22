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


if __name__ == "__main__":
    unittest.main()
