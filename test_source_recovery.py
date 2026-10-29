"""Tests for bounded, non-destructive catalog source recovery."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import get_connection, initialize_database
from sync_jobs import record_source_health, retry_due_sources


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "recovery.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_failures_back_off_and_success_resets_recovery_state(self):
        failure = [{
            "source": "Workday:Example", "employer": "Example",
            "status": "failed", "error": "temporary failure",
        }]
        record_source_health(self.database_path, failure)
        record_source_health(self.database_path, failure)
        connection = get_connection(self.database_path)
        row = connection.execute(
            """SELECT consecutive_failures, next_retry_at
               FROM catalog_sync_status WHERE employer = 'Example'"""
        ).fetchone()
        connection.close()
        self.assertEqual(row[0], 2)
        self.assertIsNotNone(row[1])

        record_source_health(self.database_path, [{
            "source": "Workday:Example", "employer": "Example",
            "status": "ok", "fetched": 5, "imported": 5,
        }])
        connection = get_connection(self.database_path)
        row = connection.execute(
            """SELECT consecutive_failures, next_retry_at
               FROM catalog_sync_status WHERE employer = 'Example'"""
        ).fetchone()
        connection.close()
        self.assertEqual(row[0], 0)
        self.assertIsNone(row[1])

    def test_due_retry_is_bounded_and_never_marks_stale(self):
        connection = get_connection(self.database_path)
        for index in range(5):
            connection.execute(
                """INSERT INTO catalog_sync_status
                   (source, employer, status, next_retry_at)
                   VALUES (?, ?, 'failed', datetime('now', '-1 minute'))""",
                (f"Source:{index}", f"Employer {index}"),
            )
        connection.commit()
        connection.close()

        with patch("sync_jobs.sync_all") as sync:
            sync.return_value = {
                "sources": [
                    {"employer": f"Employer {index}", "status": "ok"}
                    for index in range(3)
                ]
            }
            report = retry_due_sources(self.database_path, max_sources=3)

        self.assertEqual(report["retried"], 3)
        self.assertEqual(report["recovered"], 3)
        self.assertFalse(sync.call_args.kwargs["mark_stale"])
        self.assertEqual(len(sync.call_args.kwargs["employer_filter"]), 3)


if __name__ == "__main__":
    unittest.main()
