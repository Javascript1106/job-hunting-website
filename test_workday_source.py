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

    def test_general_catalog_mode_keeps_age_claims_unconfirmed(self):
        listing = {
            "total": 1,
            "jobPostings": [{
                "title": "Store Team Member",
                "externalPath": "/job/store-team-member_JR4",
            }],
        }
        detail = {"jobPostingInfo": {
            "id": "internal-4",
            "title": "Store Team Member",
            "jobDescription": "Training is provided. Apply on our official site.",
            "location": "Portland, ME",
            "externalUrl": "https://example.myworkdayjobs.com/job/JR4",
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
                "title_patterns": ["team member"],
                "confirmed_teen_only": False,
                "scan_limit": 20,
            })
        self.assertEqual(len(records), 1)
        self.assertIn("check employer age", records[0]["experience"])
        self.assertNotIn("Minimum age", records[0]["requirements"] or "")

    def test_targeted_queries_are_sent_and_duplicate_paths_are_removed(self):
        listing = {
            "total": 1,
            "jobPostings": [{
                "title": "Guest Advocate",
                "externalPath": "/job/guest-advocate_JR5",
            }],
        }
        detail = {"jobPostingInfo": {
            "id": "internal-5",
            "title": "Guest Advocate",
            "jobDescription": "Training provided.",
            "location": "Bangor, ME",
            "externalUrl": "https://example.myworkdayjobs.com/job/JR5",
            "jobRequisitionLocation": {"country": {"alpha2Code": "US"}},
        }}
        with patch(
            "job_sources.workday._post_json", return_value=listing
        ) as post_json, patch(
            "job_sources.workday.fetch_json", return_value=detail
        ) as fetch_json:
            _, records = workday.fetch_jobs({
                "employer": "Example",
                "host": "example.wd5",
                "tenant": "example",
                "site": "Careers",
                "search_queries": ["guest advocate", "cashier"],
                "confirmed_teen_only": False,
                "scan_limit": 20,
            })

        self.assertEqual(post_json.call_count, 2)
        self.assertEqual(
            [call.args[1]["searchText"] for call in post_json.call_args_list],
            ["guest advocate", "cashier"],
        )
        self.assertEqual(fetch_json.call_count, 1)
        self.assertEqual(len(records), 1)

    def test_rejects_countries_outside_the_configured_catalog(self):
        listing = {
            "total": 1,
            "jobPostings": [{
                "title": "Cashier",
                "externalPath": "/job/cashier_JR3",
            }],
        }
        detail = {"jobPostingInfo": {
            "id": "internal-3",
            "title": "Cashier",
            "jobDescription": "Applicants must be at least 16.",
            "location": "Toronto, Ontario",
            "externalUrl": "https://example.myworkdayjobs.com/job/JR3",
            "jobRequisitionLocation": {
                "country": {"alpha2Code": "CA"}
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
                "country_codes": ["US"],
                "scan_limit": 20,
            })
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
