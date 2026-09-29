"""Backup and restore regression tests for PathForge SQLite data."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import database
from backup_database import backup_database
from restore_database import restore_database


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "pathforge.db"
        database.initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_verified_backup_can_restore_prior_state(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            ("backup-user", "backup@example.com", "test-hash", "job_seeker"),
        )
        connection.commit()
        connection.close()

        backup = backup_database(self.database_path, self.root / "backups")
        connection = sqlite3.connect(self.database_path)
        connection.execute("DELETE FROM users WHERE username = 'backup-user'")
        connection.commit()
        connection.close()

        restored, safety = restore_database(backup, self.database_path, confirm=True)
        connection = sqlite3.connect(restored)
        count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE username = 'backup-user'"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(count, 1)
        self.assertTrue(safety.is_file())

    def test_restore_requires_explicit_confirmation(self):
        backup = backup_database(self.database_path, self.root / "backups")
        with self.assertRaisesRegex(RuntimeError, "--confirm"):
            restore_database(backup, self.database_path)


if __name__ == "__main__":
    unittest.main()
