"""Regression tests for persistent authentication abuse protection."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

import main


class AuthenticationRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = main.DB_NAME
        main.DB_NAME = str(Path(self.temporary_directory.name) / "auth-tests.db")
        connection = sqlite3.connect(main.DB_NAME)
        connection.executescript("""
            CREATE TABLE auth_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                subject_hash TEXT NOT NULL,
                ip_hash TEXT NOT NULL,
                succeeded INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_auth_attempts_lookup
            ON auth_attempts(action, subject_hash, ip_hash, created_at);
            CREATE INDEX idx_auth_attempts_ip
            ON auth_attempts(action, ip_hash, created_at);
        """)
        connection.close()
        self.request = Request({
            "type": "http",
            "method": "POST",
            "path": "/login",
            "headers": [],
            "client": ("203.0.113.10", 54321),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        })

    def tearDown(self):
        main.DB_NAME = self.original_database
        self.temporary_directory.cleanup()

    def test_login_is_blocked_after_five_failures(self):
        for _ in range(5):
            main.enforce_authentication_rate_limit("login", self.request, "person@example.com")
            main.record_authentication_attempt("login", self.request, "person@example.com", False)

        with self.assertRaises(HTTPException) as raised:
            main.enforce_authentication_rate_limit("login", self.request, "person@example.com")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "900")

    def test_successful_login_clears_prior_failures(self):
        for _ in range(4):
            main.record_authentication_attempt("login", self.request, "person@example.com", False)
        main.record_authentication_attempt("login", self.request, "person@example.com", True)

        main.enforce_authentication_rate_limit("login", self.request, "person@example.com")
        connection = sqlite3.connect(main.DB_NAME)
        attempts = connection.execute(
            "SELECT succeeded FROM auth_attempts WHERE action = 'login'"
        ).fetchall()
        connection.close()
        self.assertEqual(attempts, [(1,)])

    def test_identifiers_are_hashed_before_storage(self):
        identifier = "Private.Person@example.com"
        main.record_authentication_attempt("login", self.request, identifier, False)
        connection = sqlite3.connect(main.DB_NAME)
        stored_subject, stored_ip = connection.execute(
            "SELECT subject_hash, ip_hash FROM auth_attempts"
        ).fetchone()
        connection.close()

        self.assertNotIn("private.person", stored_subject)
        self.assertNotIn("203.0.113.10", stored_ip)
        self.assertEqual(len(stored_subject), 64)
        self.assertEqual(len(stored_ip), 64)

    def test_reset_requests_count_even_when_delivery_succeeds(self):
        for _ in range(3):
            main.enforce_authentication_rate_limit(
                "password_reset_request", self.request, "person@example.com"
            )
            main.record_authentication_attempt(
                "password_reset_request", self.request, "person@example.com", True
            )

        with self.assertRaises(HTTPException) as raised:
            main.enforce_authentication_rate_limit(
                "password_reset_request", self.request, "person@example.com"
            )
        self.assertEqual(raised.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
