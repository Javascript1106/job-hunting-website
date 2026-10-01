"""Contract tests for the public Workday career-site adapter."""

import unittest
from unittest.mock import patch

from job_sources import workday


class WorkdaySourceTests(unittest.TestCase):
    def test_imports_only_explicitly_teen_eligible_regional_roles(self):
        listing = {
            "total": 1,
            "jobPostings": [{
                "title": "Restaurant Team Member",
                "externalPath": "/job/denver/team-member_JR1",
            }],
        }
        detail = {"jobPostingInfo": {
            "id": "internal-1",
            "title": "Restaurant Team Member",
            "jobDescription": (
                "Restaurant team member. Minimum age requirement (16+) "
                "Competitive pay: $15.00 - $18.00 per hour."
            ),
            "location": "Denver, CO",
            "timeType": "Part time",
            "jobReqId": "JR1",
            "startDate": "2026-09-20",
            "externalUrl": "https://example.myworkdayjobs.com/job/JR1",
            "jobRequisitionLocation": {
                "country": {"alpha2Code": "US"}
            },
        }}
        with patch("job_sources.workday._post_json", return_value=listing), patch(
            "job_sources.workday.fetch_json", return_value=detail
        ):
            source, records = workday.fetch_jobs({
                "employer": "Example",
                "host": "example.wd5",
                "tenant": "example",
                "site": "Careers",
                "title_patterns": ["team member"],
                "scan_limit": 20,
            })
        self.assertEqual(source, "Workday:example:Careers")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_job_id"], "JR1")
        self.assertEqual(records[0]["salary_min"], 15.0)
        self.assertIn("Minimum age stated by employer: 16", records[0]["requirements"])

    def test_rejects_roles_without_explicit_teen_age(self):
        listing = {
            "total": 1,
            "jobPostings": [{
                "title": "Cashier",
                "externalPath": "/job/cashier_JR2",
            }],
        }
        detail = {"jobPostingInfo": {
            "id": "internal-2",
            "title": "Cashier",
            "jobDescription": "Applicants must be at least 18.",
            "location": "Denver, CO",
            "externalUrl": "https://example.myworkdayjobs.com/job/JR2",
            "jobRequisitionLocation": {
                "country": {"alpha2Code": "US"}
            },
        }}
        with patch("job_sources.workday._post_json", return_value=listing), patch(
            "job_sources.workday.fetch_json", return_value=detail
        ):
            _, records = workday.fetch_jobs({
                "employer": "Example",
                "host": "example.wd5",
                "tenant": "example",
                "site": "Careers",
                "title_patterns": ["cashier"],
                "scan_limit": 20,
            })
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
