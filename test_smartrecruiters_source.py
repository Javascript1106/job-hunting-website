"""Contract tests for the public SmartRecruiters adapter."""

import unittest
from unittest.mock import patch

from job_sources import smartrecruiters


class SmartRecruitersSourceTests(unittest.TestCase):
    def test_general_catalog_mode_does_not_claim_teen_eligibility(self):
        listing = {"content": [{
            "name": "Sales Advisor",
            "id": "listing-1",
            "ref": "https://api.smartrecruiters.com/jobs/listing-1",
            "releasedDate": "2026-10-13",
            "location": {"country": "us", "region": "ME"},
            "typeOfEmployment": {"id": "part-time"},
        }]}
        detail = {
            "id": "listing-1",
            "name": "Sales Advisor",
            "location": {"fullLocation": "Portland, ME"},
            "typeOfEmployment": {"label": "Part-time"},
            "jobAd": {"sections": {
                "jobDescription": {"text": "Training is provided."},
                "qualifications": {"text": "Friendly and dependable."},
            }},
            "postingUrl": "https://jobs.smartrecruiters.com/example/listing-1",
            "releasedDate": "2026-10-13",
        }
        with patch(
            "job_sources.smartrecruiters.fetch_json",
            side_effect=[listing, {"content": []}, detail],
        ):
            source, records = smartrecruiters.fetch_jobs({
                "employer": "Example",
                "company_id": "Example",
                "confirmed_teen_only": False,
                "scan_limit": 200,
                "max_jobs": 10,
            })

        self.assertEqual(source, "SmartRecruiters:Example")
        self.assertEqual(len(records), 1)
        self.assertIn("check employer age", records[0]["experience"])
        self.assertNotIn("Minimum age", records[0]["requirements"] or "")

    def test_teen_mode_remains_the_default(self):
        listing = {"content": [{
            "name": "Sales Advisor",
            "id": "listing-2",
            "ref": "https://api.smartrecruiters.com/jobs/listing-2",
            "location": {"country": "us", "region": "ME"},
        }]}
        detail = {
            "id": "listing-2",
            "name": "Sales Advisor",
            "location": {"fullLocation": "Portland, ME"},
            "jobAd": {"sections": {
                "jobDescription": {"text": "Applicants must be at least 18."},
            }},
            "postingUrl": "https://jobs.smartrecruiters.com/example/listing-2",
        }
        with patch(
            "job_sources.smartrecruiters.fetch_json",
            side_effect=[listing, detail],
        ):
            _, records = smartrecruiters.fetch_jobs({
                "employer": "Example",
                "company_id": "Example",
                "scan_limit": 100,
                "max_jobs": 10,
            })

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
