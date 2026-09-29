"""Integration tests for public job discovery and user-scoped bookmarks."""

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

import database
import main


VALID_PASSWORD = "A carefully chosen job workflow passphrase 42!"


class JobWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = main.DB_NAME
        self.database_path = str(
            Path(self.temporary_directory.name) / "job-workflows.db"
        )
        database.initialize_database(self.database_path)
        main.DB_NAME = self.database_path
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.DB_NAME = self.original_database
        self.temporary_directory.cleanup()

    def create_user(self, username, email, role="job_seeker"):
        connection = database.get_connection(self.database_path)
        cursor = connection.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            (username, email, main.hash_password(VALID_PASSWORD), role),
        )
        user_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return user_id

    def login(self, username):
        response = self.client.post(
            "/login",
            json={"identifier": username, "password": VALID_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)

    def create_job(self, title, status="active", owner_user_id=None):
        connection = database.get_connection(self.database_path)
        cursor = connection.execute(
            """
            INSERT INTO jobs (
                title, company, location, pay, description,
                schedule, experience, category, application_method,
                status, owner_user_id
            ) VALUES (?, 'PathForge Test Company', 'Denver, CO', '$22 per hour',
                      'A safe integration-test listing.', 'Full-time',
                      'Entry level', 'Customer Service', 'pathforge', ?, ?)
            """,
            (title, status, owner_user_id),
        )
        job_id = cursor.lastrowid
        connection.commit()
        connection.close()
        return job_id

    def test_public_discovery_only_returns_active_public_jobs(self):
        active_job = self.create_job("Visible Support Role")
        self.create_job("Closed Support Role", status="closed")
        owner_id = self.create_user("private_owner", "private@example.com")
        self.create_job("Private Tracker Role", owner_user_id=owner_id)

        response = self.client.get("/jobs")

        self.assertEqual(response.status_code, 200)
        returned_ids = {job["id"] for job in response.json()}
        self.assertEqual(returned_ids, {active_job})

    def test_catalog_truncates_cards_and_full_details_remain_available(self):
        job_id = self.create_job("Long Description Role")
        connection = database.get_connection(self.database_path)
        long_description = "Detailed responsibility " * 100
        connection.execute(
            "UPDATE jobs SET description = ?, requirements = ? WHERE id = ?",
            (long_description, long_description, job_id),
        )
        connection.commit()
        connection.close()

        catalog_job = self.client.get("/jobs/catalog").json()[0]
        detail_job = self.client.get(f"/jobs/{job_id}").json()

        self.assertTrue(catalog_job["details_truncated"])
        self.assertLessEqual(len(catalog_job["description"]), 241)
        self.assertEqual(detail_job["description"], long_description)

    def test_catalog_pagination_validates_limits(self):
        for index in range(3):
            self.create_job(f"Paginated Role {index}")

        first_page = self.client.get("/jobs/catalog?limit=2&offset=0")
        second_page = self.client.get("/jobs/catalog?limit=2&offset=2")

        self.assertEqual(len(first_page.json()), 2)
        self.assertEqual(len(second_page.json()), 1)
        self.assertEqual(self.client.get("/jobs/catalog?limit=501").status_code, 400)
        self.assertEqual(self.client.get("/jobs/catalog?offset=-1").status_code, 400)

    def test_server_side_search_returns_paginated_metadata(self):
        self.create_job("First Paginated Search Role")
        self.create_job("Second Paginated Search Role")
        response = self.client.get("/jobs/search?limit=1&offset=0&location_scope=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["jobs"]), min(1, data["total"]))
        self.assertEqual(data["offset"], 0)
        self.assertEqual(data["limit"], 1)
        self.assertEqual(data["has_more"], data["total"] > 1)
        self.assertIsInstance(data["categories"], list)

    def test_server_side_search_filters_before_pagination(self):
        self.create_job("Visible Support Specialist")
        jobs = self.client.get("/jobs?location_scope=all").json()
        self.assertTrue(jobs)
        target = jobs[0]
        response = self.client.get(
            "/jobs/search",
            params={
                "query": target["title"],
                "location_scope": "all",
                "category": target["category"],
                "limit": 25,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(data["total"], 1)
        self.assertTrue(all(job["category"] == target["category"] for job in data["jobs"]))

    def test_server_side_search_applies_minimum_pay_and_strict_exclusions(self):
        junior_id = self.create_job("Customer Support Representative")
        senior_id = self.create_job("Senior Customer Support Manager")
        connection = database.get_connection(self.database_path)
        connection.execute(
            "UPDATE jobs SET salary_min = 30, salary_max = 35, salary_period = 'hour' WHERE id = ?",
            (junior_id,),
        )
        connection.execute(
            "UPDATE jobs SET salary_min = 120000, salary_max = 140000, salary_period = 'year' WHERE id = ?",
            (senior_id,),
        )
        connection.commit()
        connection.close()

        response = self.client.get(
            "/jobs/search",
            params={"location_scope": "all", "minimum_pay": 50_000, "exclusions": "senior"},
        )
        self.assertEqual(response.status_code, 200)
        returned_ids = {job["id"] for job in response.json()["jobs"]}
        self.assertIn(junior_id, returned_ids)
        self.assertNotIn(senior_id, returned_ids)

    def test_server_side_search_finds_application_accommodation_information(self):
        accessible_id = self.create_job("Accessible Application Role")
        ordinary_id = self.create_job("Ordinary Application Role")
        connection = database.get_connection(self.database_path)
        connection.execute(
            "UPDATE jobs SET description = ? WHERE id = ?",
            (
                "Applicants who need a reasonable accommodation during the "
                "application process may contact our recruiting team.",
                accessible_id,
            ),
        )
        connection.commit()
        connection.close()

        response = self.client.get(
            "/jobs/search",
            params={"location_scope": "all", "listing_quality": "accommodation"},
        )

        self.assertEqual(response.status_code, 200)
        jobs = response.json()["jobs"]
        self.assertEqual({job["id"] for job in jobs}, {accessible_id})
        self.assertTrue(jobs[0]["accommodation_info"])
        self.assertNotIn(ordinary_id, {job["id"] for job in jobs})

    def test_server_side_search_filters_explicit_application_features(self):
        no_letter_id = self.create_job("Resume Only Role")
        contact_id = self.create_job("Accommodation Contact Role")
        connection = database.get_connection(self.database_path)
        connection.execute(
            "UPDATE jobs SET description = ? WHERE id = ?",
            ("Submit your resume only. No cover letter is required.", no_letter_id),
        )
        connection.execute(
            "UPDATE jobs SET description = ? WHERE id = ?",
            (
                "If you need a reasonable accommodation during the application "
                "process, contact the recruiting team.",
                contact_id,
            ),
        )
        connection.commit()
        connection.close()

        no_letter = self.client.get(
            "/jobs/search",
            params={"location_scope": "all", "application_feature": "no_cover_letter"},
        ).json()["jobs"]
        contact = self.client.get(
            "/jobs/search",
            params={"location_scope": "all", "application_feature": "accommodation_contact"},
        ).json()["jobs"]

        self.assertEqual({job["id"] for job in no_letter}, {no_letter_id})
        self.assertTrue(no_letter[0]["no_cover_letter"])
        self.assertEqual({job["id"] for job in contact}, {contact_id})
        self.assertTrue(contact[0]["accommodation_contact"])

    def test_server_side_search_supports_exact_location_and_remote_eligibility(self):
        denver_id = self.create_job("Denver Exact Role")
        worldwide_id = self.create_job("Worldwide Remote Role")
        connection = database.get_connection(self.database_path)
        connection.execute("UPDATE jobs SET location = 'Denver, CO' WHERE id = ?", (denver_id,))
        connection.execute(
            "UPDATE jobs SET location = 'Worldwide', is_remote = 1 WHERE id = ?",
            (worldwide_id,),
        )
        connection.commit()
        connection.close()

        exact = self.client.get(
            "/jobs/search",
            params={"location_scope": "all", "location": "Denver", "location_mode": "exact"},
        ).json()
        worldwide = self.client.get(
            "/jobs/search",
            params={"location_scope": "all", "remote_eligibility": "anywhere"},
        ).json()
        self.assertIn(denver_id, {job["id"] for job in exact["jobs"]})
        self.assertEqual({job["id"] for job in worldwide["jobs"]}, {worldwide_id})

    def test_public_job_detail_rejects_private_tracker_jobs(self):
        owner_id = self.create_user("detail_owner", "detail-owner@example.com")
        private_job = self.create_job("Private Detail Role", owner_user_id=owner_id)

        self.assertEqual(self.client.get(f"/jobs/{private_job}").status_code, 404)

    def test_bookmark_lifecycle_and_duplicate_save_are_idempotent(self):
        self.create_user("bookmark_user", "bookmark@example.com")
        job_id = self.create_job("Bookmarkable Role")
        self.login("bookmark_user")

        first_save = self.client.post(f"/saved-jobs/{job_id}")
        duplicate_save = self.client.post(f"/saved-jobs/{job_id}")
        saved_jobs = self.client.get("/saved-jobs")
        removal = self.client.delete(f"/saved-jobs/{job_id}")
        missing_removal = self.client.delete(f"/saved-jobs/{job_id}")

        self.assertEqual(first_save.status_code, 200)
        self.assertFalse(first_save.json()["already_saved"])
        self.assertEqual(duplicate_save.status_code, 200)
        self.assertTrue(duplicate_save.json()["already_saved"])
        self.assertEqual([job["id"] for job in saved_jobs.json()["saved_jobs"]], [job_id])
        self.assertEqual(removal.status_code, 200)
        self.assertEqual(missing_removal.status_code, 404)

    def test_bookmarks_are_scoped_to_the_authenticated_user(self):
        self.create_user("first_seeker", "first@example.com")
        self.create_user("second_seeker", "second@example.com")
        job_id = self.create_job("User Scoped Role")

        self.login("first_seeker")
        self.assertEqual(self.client.post(f"/saved-jobs/{job_id}").status_code, 200)
        self.client.post("/logout")
        self.login("second_seeker")

        self.assertEqual(self.client.get("/saved-jobs").json()["saved_jobs"], [])
        self.assertEqual(self.client.delete(f"/saved-jobs/{job_id}").status_code, 404)

    def test_anonymous_and_invalid_bookmark_requests_are_rejected(self):
        job_id = self.create_job("Protected Bookmark Role")
        self.assertEqual(self.client.get("/saved-jobs").status_code, 401)
        self.assertEqual(self.client.post(f"/saved-jobs/{job_id}").status_code, 401)
        self.assertEqual(self.client.delete(f"/saved-jobs/{job_id}").status_code, 401)

        self.create_user("valid_seeker", "valid@example.com")
        self.login("valid_seeker")
        self.assertEqual(self.client.post("/saved-jobs/999999").status_code, 404)

    def test_non_public_jobs_cannot_be_bookmarked_by_identifier(self):
        owner_id = self.create_user("tracker_owner", "tracker@example.com")
        self.create_user("other_seeker", "other@example.com")
        private_job = self.create_job("Private Role", owner_user_id=owner_id)
        closed_job = self.create_job("Closed Role", status="closed")
        self.login("other_seeker")

        self.assertEqual(self.client.post(f"/saved-jobs/{private_job}").status_code, 404)
        self.assertEqual(self.client.post(f"/saved-jobs/{closed_job}").status_code, 404)

    def test_company_research_summarizes_public_listings(self):
        job_id = self.create_job("Company Research Role")

        response = self.client.get("/companies/PathForge%20Test%20Company")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company"]["name"], "PathForge Test Company")
        self.assertEqual(response.json()["summary"]["active_job_count"], 1)
        self.assertEqual(response.json()["active_jobs"][0]["id"], job_id)
        self.assertEqual(self.client.get("/companies/Unknown%20Company").status_code, 404)

    def test_company_research_excludes_expired_listings(self):
        job_id = self.create_job("Expired Company Role")
        connection = database.get_connection(self.database_path)
        connection.execute(
            "UPDATE jobs SET application_deadline = '2000-01-01' WHERE id = ?",
            (job_id,),
        )
        connection.commit()
        connection.close()

        self.assertEqual(
            self.client.get("/companies/PathForge%20Test%20Company").status_code,
            404,
        )

    def test_job_chat_never_exposes_private_tracker_jobs(self):
        tracker_owner = self.create_user("chat_tracker_owner", "chat-owner@example.com")
        self.create_job("Visible Chat Role")
        private_job = self.create_job(
            "Private Chat Tracker Role",
            owner_user_id=tracker_owner,
        )
        self.create_user("chat_seeker", "chat-seeker@example.com")
        self.login("chat_seeker")

        response = self.client.post(
            "/chat",
            json={"message": "Show me current jobs"},
        )

        self.assertEqual(response.status_code, 200)
        returned_ids = {job["id"] for job in response.json()["job_results"]}
        self.assertNotIn(private_job, returned_ids)

    def test_job_report_submission_duplicate_protection_and_admin_resolution(self):
        self.create_user("reporter", "reporter@example.com")
        self.create_user("moderator", "moderator@example.com", role="admin")
        job_id = self.create_job("Reportable Role")
        self.login("reporter")

        report = self.client.post(
            f"/jobs/{job_id}/report",
            json={"reason": "misleading_information", "details": "The location appears incorrect."},
        )
        self.assertEqual(report.status_code, 201)
        report_id = report.json()["report"]["id"]
        self.assertEqual(
            self.client.post(
                f"/jobs/{job_id}/report",
                json={"reason": "misleading_information"},
            ).status_code,
            409,
        )
        self.assertEqual(len(self.client.get("/job-reports/mine").json()["reports"]), 1)
        self.assertEqual(self.client.get("/admin/job-reports").status_code, 403)

        self.client.post("/logout")
        self.login("moderator")
        queue = self.client.get("/admin/job-reports")
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.json()["counts"]["submitted"], 1)
        resolved = self.client.patch(
            f"/admin/job-reports/{report_id}",
            json={"status": "resolved", "moderation_note": "Reviewed by test moderator."},
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["report"]["status"], "resolved")
        self.assertIsNotNone(resolved.json()["report"]["resolved_at"])


if __name__ == "__main__":
    unittest.main()
