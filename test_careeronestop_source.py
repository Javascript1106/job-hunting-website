"""Security and normalization tests for the CareerOneStop adapter."""

import os
import unittest
from unittest.mock import patch

from job_sources import careeronestop


class CareerOneStopSourceTests(unittest.TestCase):
    def setUp(self):
        self.configuration = {
            "locations": ["UT"],
            "page_size": 25,
            "pages_per_location": 1,
            "days": 60,
            "max_jobs": 100,
        }

    def test_credentials_are_required_from_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must be set"):
                careeronestop.fetch_jobs(self.configuration)

    def test_jobs_v2_response_is_normalized_and_token_stays_in_header(self):
        payload = {
            "ErrorMessage": "",
            "Jobs": [{
                "JvId": "abc-123",
                "JobTitle": "Crew Member",
                "Company": "Example Employer",
                "DescriptionSnippet": "Help customers and prepare orders.",
                "AcquisitionDate": "2026-11-02T00:00:00",
                "URL": "https://example.org/jobs/abc-123",
                "Location": "Salt Lake City, UT",
                "OnetCodes": ["35-3023.00"],
            }],
        }
        with patch.dict(os.environ, {
            "CAREERONESTOP_USER_ID": "pathforge-user",
            "CAREERONESTOP_API_TOKEN": "secret-token",
        }), patch("job_sources.careeronestop.fetch_json", return_value=payload) as fetch:
            source, jobs = careeronestop.fetch_jobs(self.configuration)

        self.assertEqual(source, "CareerOneStop")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["external_job_id"], "abc-123")
        self.assertEqual(jobs[0]["company"], "Example Employer")
        url = fetch.call_args.args[0]
        headers = fetch.call_args.kwargs["headers"]
        self.assertNotIn("secret-token", url)
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertIn("enableJobDescriptionSnippet=true", url)

    def test_duplicate_job_ids_across_locations_are_removed(self):
        configuration = {**self.configuration, "locations": ["UT", "ID"]}
        payload = {
            "Jobs": [{
                "JvId": "same-job",
                "JobTitle": "Sales Associate",
                "Company": "Example Employer",
                "DescriptionSnippet": "Assist customers.",
                "URL": "https://example.org/jobs/same-job",
                "Location": "Remote, United States",
            }],
        }
        with patch.dict(os.environ, {
            "CAREERONESTOP_USER_ID": "user",
            "CAREERONESTOP_API_TOKEN": "token",
        }), patch("job_sources.careeronestop.fetch_json", return_value=payload):
            _source, jobs = careeronestop.fetch_jobs(configuration)
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
