"""Integration tests for employer-owned job listing management."""

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

import database
import main


VALID_PASSWORD = "A carefully chosen employer workflow passphrase 42!"


class EmployerJobManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = main.DB_NAME
        self.database_path = str(
            Path(self.temporary_directory.name) / "employer-jobs.db"
        )
        database.initialize_database(self.database_path)
        main.DB_NAME = self.database_path
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.DB_NAME = self.original_database
        self.temporary_directory.cleanup()

    def create_user(self, username, email, role):
        connection = database.get_connection(self.database_path)
        cursor = connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            (username, email, main.hash_password(VALID_PASSWORD), role),
        )
        user_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return user_id

    def login(self, username, client=None):
        target = client or self.client
        response = target.post(
            "/login",
            json={"identifier": username, "password": VALID_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)

    def job_payload(self, **updates):
        payload = {
            "title": "Junior Customer Support Specialist",
            "company": "Employer Workflow Company",
            "location": "Denver, CO",
            "pay": "$22 per hour",
            "description": "Help customers resolve common product questions.",
            "requirements": "Clear written communication",
            "preferred_qualifications": "Previous customer service experience",
            "schedule": "Full-time",
            "experience": "Entry level",
            "category": "Customer Service",
            "application_method": "pathforge",
            "status": "active",
        }
        payload.update(updates)
        return payload

    def test_employer_can_create_edit_close_reopen_and_delete_job(self):
        self.create_user("employer", "employer@example.com", "employer")
        self.login("employer")

        created = self.client.post("/jobs", json=self.job_payload())
        self.assertEqual(created.status_code, 201)
        job_id = created.json()["job"]["id"]
        self.assertEqual(
            [job["id"] for job in self.client.get("/employer/jobs").json()["jobs"]],
            [job_id],
        )
        self.assertIn(job_id, {job["id"] for job in self.client.get("/jobs").json()})

        edited = self.client.put(
            f"/employer/jobs/{job_id}",
            json=self.job_payload(title="Updated Support Specialist"),
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["job"]["title"], "Updated Support Specialist")

        closed = self.client.patch(
            f"/employer/jobs/{job_id}/status", json={"status": "closed"}
        )
        self.assertEqual(closed.status_code, 200)
        self.assertNotIn(job_id, {job["id"] for job in self.client.get("/jobs").json()})
        self.assertEqual(
            self.client.patch(
                f"/employer/jobs/{job_id}/status", json={"status": "active"}
            ).status_code,
            200,
        )
        self.assertEqual(self.client.delete(f"/employer/jobs/{job_id}").status_code, 200)
        self.assertEqual(self.client.get("/employer/jobs").json()["jobs"], [])

    def test_role_and_ownership_boundaries_cover_every_mutation(self):
        self.create_user("owner", "owner@example.com", "employer")
        self.create_user("intruder", "intruder@example.com", "employer")
        self.create_user("seeker", "seeker@example.com", "job_seeker")
        self.login("owner")
        job_id = self.client.post("/jobs", json=self.job_payload()).json()["job"]["id"]
        self.client.post("/logout")

        self.login("seeker")
        self.assertEqual(self.client.post("/jobs", json=self.job_payload()).status_code, 403)
        self.client.post("/logout")
        self.login("intruder")
        self.assertEqual(
            self.client.put(
                f"/employer/jobs/{job_id}", json=self.job_payload(title="Hijacked")
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/employer/jobs/{job_id}/status", json={"status": "closed"}
            ).status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"/employer/jobs/{job_id}").status_code, 404)

    def test_job_input_validation_rejects_invalid_workflows(self):
        self.create_user("validator", "validator@example.com", "employer")
        self.login("validator")

        missing_url = self.client.post(
            "/jobs", json=self.job_payload(application_method="employer_website")
        )
        blank_title = self.client.post("/jobs", json=self.job_payload(title="   "))
        invalid_status = self.client.post(
            "/jobs", json=self.job_payload(status="unknown")
        )

        self.assertEqual(missing_url.status_code, 400)
        self.assertEqual(blank_title.status_code, 400)
        self.assertEqual(invalid_status.status_code, 400)

    def test_job_with_tracked_application_must_be_closed_instead_of_deleted(self):
        employer_id = self.create_user("hiring_team", "hiring@example.com", "employer")
        seeker_id = self.create_user("applicant", "applicant@example.com", "job_seeker")
        self.login("hiring_team")
        job_id = self.client.post("/jobs", json=self.job_payload()).json()["job"]["id"]
        connection = database.get_connection(self.database_path)
        connection.execute(
            """INSERT INTO applications (user_id, job_id, application_method, status)
               VALUES (?, ?, 'pathforge', 'Applied')""",
            (seeker_id, job_id),
        )
        connection.commit()
        connection.close()

        deletion = self.client.delete(f"/employer/jobs/{job_id}")

        self.assertEqual(deletion.status_code, 409)
        self.assertIn("Close the job", deletion.json()["detail"])
        self.assertEqual(
            self.client.patch(
                f"/employer/jobs/{job_id}/status", json={"status": "closed"}
            ).status_code,
            200,
        )


if __name__ == "__main__":
    unittest.main()
