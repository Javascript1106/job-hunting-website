"""Contract tests for the public Recruitee career-site adapter."""

import unittest
from unittest.mock import patch

from job_sources import recruitee


class RecruiteeSourceTests(unittest.TestCase):
    def test_public_offers_are_normalized(self):
        payload = {"offers": [{
            "id": 42,
            "title": "Customer Support Specialist",
            "location": {"city": "Denver", "region": "Colorado", "country": "US"},
            "remote": True,
            "department": {"name": "Support"},
            "description": "Requirements<br>- Two years of customer support experience",
            "employment_type": "Full time",
            "careers_url": "https://example.recruitee.com/o/support-specialist",
            "published_at": "2026-09-01T12:00:00Z",
        }]}
        with patch("job_sources.recruitee.fetch_json", return_value=payload) as fetch:
            source, records = recruitee.fetch_jobs({
                "employer": "Example Employer",
                "company_subdomain": "Example",
            })

        self.assertEqual(source, "Recruitee:example")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_job_id"], "42")
        self.assertTrue(records[0]["is_remote"])
        self.assertIn("Denver", records[0]["location"])
        self.assertIn("customer support experience", records[0]["requirements"])
        self.assertEqual(fetch.call_args.args[0], "https://example.recruitee.com/api/offers")

    def test_rejects_unsafe_subdomain(self):
        with self.assertRaisesRegex(ValueError, "invalid Recruitee"):
            recruitee.fetch_jobs({
                "employer": "Example",
                "company_subdomain": "example/path",
            })


if __name__ == "__main__":
    unittest.main()
