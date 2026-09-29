"""Regression tests for PathForge's centralized SQLite connection policy."""

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database


class DatabaseConnectionTests(unittest.TestCase):
    def test_default_path_is_project_root_database(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PATHFORGE_DATABASE_PATH", None)
            expected = (database.PROJECT_ROOT / "jobs.db").resolve()
            self.assertEqual(Path(database.resolve_database_path()), expected)

    def test_relative_override_is_resolved_from_project_root(self):
        with patch.dict(
            os.environ,
            {"PATHFORGE_DATABASE_PATH": "data/pathforge-test.db"},
        ):
            expected = (database.PROJECT_ROOT / "data/pathforge-test.db").resolve()
            self.assertEqual(Path(database.resolve_database_path()), expected)

    def test_connection_enables_integrity_and_lock_timeout(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "connection.db"
            connection = database.get_connection(database_path)
            try:
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
                busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
                self.assertEqual(foreign_keys, 1)
                self.assertEqual(busy_timeout, 5000)
            finally:
                connection.close()

    def test_connection_enforces_foreign_keys(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "foreign-keys.db"
            connection = database.get_connection(database_path)
            try:
                connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
                connection.execute(
                    "CREATE TABLE children (parent_id INTEGER REFERENCES parents(id))"
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO children (parent_id) VALUES (999)")
            finally:
                connection.close()

    def test_standard_sqlite_connect_is_not_monkey_patched(self):
        self.assertIsNot(sqlite3.connect, database.get_connection)
        self.assertFalse(hasattr(database, "connect_with_integrity"))


if __name__ == "__main__":
    unittest.main()
