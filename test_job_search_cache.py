"""Regression tests for fast, automatically invalidated job pagination."""

from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
import job_routes


class JobSearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temporary_directory.name) / "search-cache.db")
        database.initialize_database(self.database_path)
        connection = database.get_connection(self.database_path)
        for index in range(5):
            connection.execute(
                """
                INSERT INTO jobs (
                    title, company, location, pay, description, schedule,
                    experience, category, application_method, status,
                    verification_status
                ) VALUES (?, 'Cache Test Employer', 'Denver, CO', '$20/hour',
                          'Public test listing', 'Full-time', 'Entry level',
                          'Customer Service', 'employer_website', 'active', 'verified')
                """,
                (f"Support Role {index}",),
            )
        connection.commit()
        connection.close()
        app = FastAPI()
        app.include_router(
            job_routes.create_job_router(
                lambda: self.database_path,
                lambda job: job,
            )
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.temporary_directory.cleanup()

    def test_pagination_reuses_the_filtered_result_order(self):
        original = job_routes.discover_jobs
        with patch("job_routes.discover_jobs", wraps=original) as discovery:
            first = self.client.get("/jobs/search?limit=2&offset=0")
            second = self.client.get("/jobs/search?limit=2&offset=2")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(discovery.call_count, 1)
        self.assertNotEqual(
            [job["id"] for job in first.json()["jobs"]],
            [job["id"] for job in second.json()["jobs"]],
        )

    def test_database_change_invalidates_cached_results(self):
        first = self.client.get("/jobs/search?limit=10&offset=0")
        connection = database.get_connection(self.database_path)
        connection.execute(
            """
            INSERT INTO jobs (
                title, company, location, pay, description, schedule,
                experience, category, application_method, status,
                verification_status
            ) VALUES ('Newly Added Role', 'Cache Test Employer', 'Denver, CO',
                      '$21/hour', 'New listing', 'Full-time', 'Entry level',
                      'Customer Service', 'employer_website', 'active', 'verified')
            """
        )
        connection.commit()
        connection.close()

        second = self.client.get("/jobs/search?limit=10&offset=0")

        self.assertEqual(first.json()["total"], 5)
        self.assertEqual(second.json()["total"], 6)


if __name__ == "__main__":
    unittest.main()
