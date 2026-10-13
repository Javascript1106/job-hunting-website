"""Tests for scheduler-safe catalog maintenance."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from catalog_maintenance import run_maintenance


class CatalogMaintenanceTests(unittest.TestCase):
    def test_successful_run_backs_up_syncs_and_writes_report(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def backup():
                calls.append("backup")
                return root / "backup.db"

            def sync(*, mark_stale, progress):
                calls.append(("sync", mark_stale))
                return {
                    "inserted": 2,
                    "catalog_health": {
                        "failed_sources": [],
                        "large_source_drops": [],
                    },
                }

            report = run_maintenance(
                log_directory=root / "logs",
                lock_path=root / "sync.lock",
                backup_func=backup,
                sync_func=sync,
                progress=lambda _message: None,
            )

            self.assertEqual(calls, ["backup", ("sync", True)])
            self.assertEqual(report["status"], "success")
            self.assertTrue(Path(report["report_path"]).is_file())
            self.assertFalse((root / "sync.lock").exists())

    def test_source_failure_requires_attention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = run_maintenance(
                log_directory=root / "logs",
                lock_path=root / "sync.lock",
                backup_func=lambda: root / "backup.db",
                sync_func=lambda **_kwargs: {
                    "catalog_health": {
                        "failed_sources": ["Example Employer"],
                        "large_source_drops": [],
                    }
                },
                progress=lambda _message: None,
            )
            self.assertEqual(report["status"], "attention_required")

    def test_record_failure_requires_attention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = run_maintenance(
                log_directory=root / "logs",
                lock_path=root / "sync.lock",
                backup_func=lambda: root / "backup.db",
                sync_func=lambda **_kwargs: {
                    "failed": 1,
                    "catalog_health": {
                        "failed_sources": [],
                        "large_source_drops": [],
                    },
                },
                progress=lambda _message: None,
            )
            self.assertEqual(report["status"], "attention_required")

    def test_post_sync_automations_are_included_in_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = run_maintenance(
                log_directory=root / "logs",
                lock_path=root / "sync.lock",
                backup_func=lambda: root / "backup.db",
                sync_func=lambda **_kwargs: {
                    "catalog_health": {
                        "failed_sources": [],
                        "large_source_drops": [],
                    }
                },
                insights_func=lambda: {"active_jobs": 25},
                link_check_func=lambda: {"checked": 4, "closed": 0},
                progress=lambda _message: None,
            )
            self.assertEqual(report["catalog_insights"]["active_jobs"], 25)
            self.assertEqual(report["stale_link_check"]["checked"], 4)

    def test_existing_lock_prevents_overlapping_syncs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "sync.lock"
            lock.write_text("already running", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "already running"):
                run_maintenance(
                    log_directory=root / "logs",
                    lock_path=lock,
                    backup_func=lambda: root / "backup.db",
                    sync_func=lambda **_kwargs: {},
                    progress=lambda _message: None,
                )

    def test_abandoned_process_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "sync.lock"
            lock.write_text("pid=99999999\n", encoding="utf-8")
            with patch("catalog_maintenance.os.kill", side_effect=ProcessLookupError):
                report = run_maintenance(
                    log_directory=root / "logs",
                    lock_path=lock,
                    backup_func=lambda: root / "backup.db",
                    sync_func=lambda **_kwargs: {
                        "catalog_health": {
                            "failed_sources": [],
                            "large_source_drops": [],
                        }
                    },
                    progress=lambda _message: None,
                )
            self.assertEqual(report["status"], "success")
            self.assertFalse(lock.exists())

    def test_old_lock_without_pid_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / "sync.lock"
            lock.write_text("incomplete", encoding="utf-8")
            old_time = (
                datetime.now(timezone.utc) - timedelta(hours=5)
            ).timestamp()
            os.utime(lock, (old_time, old_time))
            report = run_maintenance(
                log_directory=root / "logs",
                lock_path=lock,
                backup_func=lambda: root / "backup.db",
                sync_func=lambda **_kwargs: {
                    "catalog_health": {
                        "failed_sources": [],
                        "large_source_drops": [],
                    }
                },
                progress=lambda _message: None,
            )
            self.assertEqual(report["status"], "success")


if __name__ == "__main__":
    unittest.main()
