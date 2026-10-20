"""Tests for scheduled, deterministic user automations."""

from pathlib import Path
import tempfile
import unittest

import database
import main
from run_user_automations import run_user_automations


class UserAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temporary_directory.name) / "automation.db")
        self.lock_path = str(Path(self.temporary_directory.name) / "automation.lock")
        database.initialize_database(self.database_path)
        self.connection = database.get_connection(self.database_path)
        self.connection.row_factory = main.sqlite3.Row

    def tearDown(self):
        self.connection.close()
        self.temporary_directory.cleanup()

    def test_runner_creates_idempotent_application_checkpoints(self):
        user_id = self.connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES ('seeker', 's@example.com', 'hash', 'job_seeker')"
        ).lastrowid
        job_id = self.connection.execute(
            """
            INSERT INTO jobs (
                title, company, location, pay, description, schedule,
                experience, category, application_method, status
            ) VALUES ('Stock Associate', 'Example Store', 'Salt Lake City, UT',
                      '$16/hour', 'Entry-level role', 'Part-time', 'None',
                      'Retail', 'employer_website', 'active')
            """
        ).lastrowid
        self.connection.execute(
            """
            INSERT INTO applications (
                user_id, job_id, application_method, status, applied_at,
                updated_at
            ) VALUES (?, ?, 'employer_website', 'Applied', date('now', '-15 day'),
                      datetime('now', '-15 day'))
            """,
            (user_id, job_id),
        )
        self.connection.commit()

        first = run_user_automations(self.database_path, self.lock_path)
        second = run_user_automations(self.database_path, self.lock_path)
        events = self.connection.execute(
            "SELECT event_key FROM notifications ORDER BY event_key"
        ).fetchall()

        self.assertEqual(first["notifications_created"], 1)
        self.assertEqual(second["notifications_created"], 0)
        self.assertEqual(
            [row["event_key"] for row in events],
            [
                "application-check-in:1:14",
            ],
        )

    def test_runner_respects_notification_preference(self):
        user_id = self.connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES ('quiet', 'q@example.com', 'hash', 'job_seeker')"
        ).lastrowid
        self.connection.execute(
            "INSERT INTO privacy_settings (user_id, security_notifications) VALUES (?, 0)",
            (user_id,),
        )
        self.connection.commit()

        result = run_user_automations(self.database_path, self.lock_path)

        self.assertEqual(result["users_checked"], 0)
        self.assertEqual(result["notifications_created"], 0)

    def test_runner_rejects_overlapping_execution(self):
        import os

        Path(self.lock_path).write_text(f"pid={os.getpid()}\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "already running"):
            run_user_automations(self.database_path, self.lock_path)


if __name__ == "__main__":
    unittest.main()
