"""End-to-end API tests for authentication and authorization boundaries."""

import sqlite3
import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import database
import main


VALID_PASSWORD = "A carefully chosen integration passphrase 42!"
TRUSTED_ORIGIN_HEADERS = {"Origin": "https://pathforge.example"}


class AuthenticationApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = main.DB_NAME
        self.database_path = str(
            Path(self.temporary_directory.name) / "api-integration.db"
        )
        database.initialize_database(self.database_path)
        main.DB_NAME = self.database_path
        self.client = TestClient(
            main.app,
            headers=TRUSTED_ORIGIN_HEADERS,
            base_url="https://pathforge.example",
        )

    def tearDown(self):
        self.client.close()
        main.DB_NAME = self.original_database
        self.temporary_directory.cleanup()

    def register(self, username="jobseeker", email="jobseeker@example.com"):
        return self.client.post("/register", json={
            "username": username,
            "email": email,
            "password": VALID_PASSWORD,
        })

    def login(self, identifier="jobseeker"):
        return self.client.post("/login", json={
            "identifier": identifier,
            "password": VALID_PASSWORD,
        })

    def create_account_directly(self, username, email, role):
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            (username, email, main.hash_password(VALID_PASSWORD), role),
        )
        connection.commit()
        connection.close()

    def test_registration_login_session_and_logout_flow(self):
        registration = self.register()
        self.assertEqual(registration.status_code, 200)

        connection = sqlite3.connect(self.database_path)
        stored_hash = connection.execute(
            "SELECT password FROM users WHERE username = 'jobseeker'"
        ).fetchone()[0]
        connection.close()
        self.assertTrue(stored_hash.startswith("$argon2id$"))

        login = self.login()
        self.assertEqual(login.status_code, 200)
        set_cookie = login.headers["set-cookie"].lower()
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)
        if main.IS_PRODUCTION:
            self.assertIn("secure", set_cookie)

        current_user = self.client.get("/me")
        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(current_user.json()["username"], "jobseeker")

        self.assertEqual(self.client.post("/logout").status_code, 200)
        self.assertEqual(self.client.get("/me").status_code, 401)

    def test_optional_session_status_is_quiet_for_public_pages(self):
        signed_out = self.client.get("/session-status")
        self.assertEqual(signed_out.status_code, 200)
        self.assertEqual(signed_out.json(), {"authenticated": False, "user": None})

        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(self.login().status_code, 200)
        signed_in = self.client.get("/session-status")
        self.assertEqual(signed_in.status_code, 200)
        self.assertTrue(signed_in.json()["authenticated"])
        self.assertEqual(signed_in.json()["user"]["role"], "job_seeker")

    def test_protected_routes_reject_anonymous_requests(self):
        for path in (
            "/me", "/saved-jobs", "/applications", "/employer/jobs",
            "/admin/health/email",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_job_seeker_cannot_use_employer_or_admin_routes(self):
        self.assertEqual(self.register().status_code, 200)
        self.assertEqual(self.login().status_code, 200)

        self.assertEqual(self.client.get("/employer/jobs").status_code, 403)
        self.assertEqual(self.client.get("/admin/health/email").status_code, 403)

    def test_expired_session_is_rejected(self):
        self.create_account_directly("expired_user", "expired@example.com", "job_seeker")
        raw_token = "expired-integration-session-token"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        connection = sqlite3.connect(self.database_path)
        user_id = connection.execute(
            "SELECT id FROM users WHERE username = 'expired_user'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO user_sessions (user_id, token_hash, expires_at)
               VALUES (?, ?, datetime('now', '-1 minute'))""",
            (user_id, token_hash),
        )
        connection.commit()
        connection.close()
        self.client.cookies.set("pathforge_session", raw_token)

        self.assertEqual(self.client.get("/me").status_code, 401)

    def test_administrator_can_access_protected_diagnostics(self):
        self.create_account_directly("site_admin", "admin@example.com", "admin")
        login = self.client.post("/login", json={
            "identifier": "site_admin", "password": VALID_PASSWORD,
        })

        self.assertEqual(login.status_code, 200)
        diagnostics = self.client.get("/admin/health/email")
        self.assertEqual(diagnostics.status_code, 200)
        self.assertEqual(diagnostics.json()["provider"], "resend")

    def test_employer_cannot_modify_another_employers_job(self):
        self.create_account_directly("employer_one", "one@example.com", "employer")
        self.create_account_directly("employer_two", "two@example.com", "employer")

        first_client = TestClient(
            main.app,
            headers=TRUSTED_ORIGIN_HEADERS,
            base_url="https://pathforge.example",
        )
        second_client = TestClient(
            main.app,
            headers=TRUSTED_ORIGIN_HEADERS,
            base_url="https://pathforge.example",
        )
        try:
            first_login = first_client.post("/login", json={
                "identifier": "employer_one", "password": VALID_PASSWORD,
            })
            second_login = second_client.post("/login", json={
                "identifier": "employer_two", "password": VALID_PASSWORD,
            })
            self.assertEqual(first_login.status_code, 200)
            self.assertEqual(second_login.status_code, 200)

            created = first_client.post("/jobs", json={
                "title": "Junior Support Specialist",
                "company": "Example Company",
                "location": "Denver, CO",
                "pay": "$22 per hour",
                "description": "Help customers resolve common product questions.",
                "schedule": "Full-time",
                "experience": "Entry level",
                "category": "Customer Service",
                "application_method": "pathforge",
                "status": "active",
            })
            self.assertEqual(created.status_code, 201)
            job_id = created.json()["job"]["id"]

            denied = second_client.patch(
                f"/employer/jobs/{job_id}/status", json={"status": "closed"}
            )
            self.assertEqual(denied.status_code, 404)

            owner_update = first_client.patch(
                f"/employer/jobs/{job_id}/status", json={"status": "closed"}
            )
            self.assertEqual(owner_update.status_code, 200)
        finally:
            first_client.close()
            second_client.close()

    def test_security_headers_are_present_on_real_api_responses(self):
        response = self.client.get("/")

        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("content-security-policy", response.headers)
        script_policy = response.headers["content-security-policy"]
        self.assertIn("script-src 'self'", script_policy)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", script_policy)


if __name__ == "__main__":
    unittest.main()
