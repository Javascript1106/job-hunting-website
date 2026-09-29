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
            "country_code": "US",
            "department": {"name": "Support"},
            "description": "Requirements<br>- Two years of customer support experience",
            "employment_type_code": "fulltime_permanent",
            "options_cover_letter": "optional",
            "salary": {
                "min": "20",
                "max": "25",
                "period": "hour",
                "currency": "USD",
            },
            "careers_url": "https://example.recruitee.com/o/support-specialist",
            "published_at": "2026-09-01T12:00:00Z",
        }]}
        with patch("job_sources.recruitee.fetch_json", return_value=payload) as fetch:
            source, records = recruitee.fetch_jobs({
                "employer": "Example Employer",
                "company_subdomain": "Example",
                "country_codes": ["US"],
            })

        self.assertEqual(source, "Recruitee:example")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_job_id"], "42")
        self.assertTrue(records[0]["is_remote"])
        self.assertEqual(records[0]["employment_type"], "Full-Time")
        self.assertEqual(records[0]["salary_min"], 20.0)
        self.assertIn("Cover letter is not required", records[0]["description"])
        self.assertIn("Denver", records[0]["location"])
        self.assertIn("customer support experience", records[0]["requirements"])
        self.assertEqual(fetch.call_args.args[0], "https://example.recruitee.com/api/offers")

    def test_rejects_unsafe_subdomain(self):
        with self.assertRaisesRegex(ValueError, "invalid Recruitee"):
            recruitee.fetch_jobs({
                "employer": "Example",
                "company_subdomain": "example/path",
            })

    def test_country_filter_excludes_other_countries(self):
        payload = {"offers": [{
            "id": 8,
            "title": "Support Specialist",
            "country_code": "GB",
            "location": "London, United Kingdom",
            "careers_url": "https://example.recruitee.com/o/support",
        }]}
        with patch("job_sources.recruitee.fetch_json", return_value=payload):
            _, records = recruitee.fetch_jobs({
                "employer": "Example",
                "company_subdomain": "example",
                "country_codes": ["US"],
            })
        self.assertEqual(records, [])

    def test_long_description_preserves_late_accommodation_information(self):
        payload = {"offers": [{
            "id": 9,
            "title": "Operations Associate",
            "country_code": "US",
            "location": "Denver, Colorado, United States",
            "description": (
                "This role supports daily operations and customer needs. " * 20
                + "Applicants may request a reasonable accommodation during "
                "the application process by contacting the recruiting team."
            ),
            "careers_url": "https://example.recruitee.com/o/operations",
        }]}
        with patch("job_sources.recruitee.fetch_json", return_value=payload):
            _, records = recruitee.fetch_jobs({
                "employer": "Example",
                "company_subdomain": "example",
                "country_codes": ["US"],
            })
        self.assertIn("reasonable accommodation", records[0]["description"])


if __name__ == "__main__":
    unittest.main()
