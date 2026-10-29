"""Tests for daily local site maintenance and readiness reporting."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database
from site_maintenance import (
    ensure_fresh_backup, prune_runtime_files, run_site_maintenance,
    verify_restore_candidate,
)


class SiteMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "pathforge.db"
        database.initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _seed_active_job_and_old_security_data(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """INSERT INTO jobs
               (title, company, location, pay, description, schedule, experience, category)
               VALUES ('Crew Member', 'Example', 'Utah', 'Pay listed', 'Teen friendly',
                       'Part-time', 'Entry level', 'Food Service')"""
        )
        connection.execute(
            """INSERT INTO auth_attempts
               (action, subject_hash, ip_hash, succeeded, created_at)
               VALUES ('login', 'subject', 'source', 0, datetime('now', '-31 days'))"""
        )
        connection.commit()
        connection.close()

    def test_run_cleans_old_data_and_writes_private_reports(self):
        self._seed_active_job_and_old_security_data()
        backup = self.root / "backups" / "pathforge-test.db"

        def create_backup(_database_path):
            backup.parent.mkdir()
            source = sqlite3.connect(self.database_path)
            target = sqlite3.connect(backup)
            source.backup(target)
            target.close()
            source.close()
            return backup

        report = run_site_maintenance(
            database_path=self.database_path,
            log_directory=self.root / "logs",
            lock_path=self.root / "maintenance.lock",
            backup_func=create_backup,
            link_check_func=lambda: {"checked": 0, "closed": 0, "results": []},
            smoke_test_func=lambda: {"status": "success", "checks": [], "slowest_ms": 0},
            source_recovery_func=lambda: {
                "status": "nothing_due", "employers": [], "retried": 0,
                "recovered": 0, "still_failed": 0,
            },
        )
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["database"]["old_auth_attempts_removed"], 1)
        self.assertTrue(Path(report["json_report"]).is_file())
        self.assertTrue(Path(report["markdown_report"]).is_file())
        self.assertFalse((self.root / "maintenance.lock").exists())
        self.assertIn("priority_employer_health", report["database"])
        self.assertIn("western_coverage_priorities", report["catalog"])

    def test_invalid_recent_backup_is_replaced(self):
        backups = self.root / "backups"
        backups.mkdir()
        invalid = backups / "pathforge-20990101-000000.db"
        invalid.write_text("not sqlite", encoding="utf-8")
        replacement = backups / "pathforge-replacement.db"

        def create_backup(_database_path):
            source = sqlite3.connect(self.database_path)
            target = sqlite3.connect(replacement)
            source.backup(target)
            target.close()
            source.close()
            return replacement

        result = ensure_fresh_backup(self.database_path, backup_func=create_backup)
        self.assertTrue(result["created"])
        self.assertEqual(Path(result["path"]), replacement.resolve())

    def test_recent_valid_backup_is_reused(self):
        backups = self.root / "backups"
        backups.mkdir()
        existing = backups / "pathforge-20990101-000000.db"
        source = sqlite3.connect(self.database_path)
        target = sqlite3.connect(existing)
        source.backup(target)
        target.close()
        source.close()
        os.utime(existing, None)
        result = ensure_fresh_backup(
            self.database_path,
            backup_func=lambda _path: self.fail("fresh valid backup should be reused"),
        )
        self.assertFalse(result["created"])

    def test_restore_candidate_is_verified_without_touching_live_database(self):
        backup = self.root / "backup.db"
        source = sqlite3.connect(self.database_path)
        target = sqlite3.connect(backup)
        source.backup(target); target.close(); source.close()
        result = verify_restore_candidate(backup)
        self.assertTrue(result["passed"])

    def test_retention_keeps_minimum_backup_count(self):
        backups = self.root / "backups"; backups.mkdir()
        for index in range(14):
            path = backups / f"pathforge-{index:02}.db"; path.write_bytes(b"test")
            old = (datetime.now(timezone.utc) - timedelta(days=60 + index)).timestamp()
            os.utime(path, (old, old))
        result = prune_runtime_files(self.database_path, self.root / "logs")
        self.assertGreaterEqual(result["backups_retained"], 12)
        self.assertGreater(result["backups_removed"], 0)


if __name__ == "__main__":
    unittest.main()
