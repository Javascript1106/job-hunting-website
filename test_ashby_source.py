"""Contract tests for the public Ashby job-board adapter."""

import unittest
from unittest.mock import patch

from job_sources import ashby


class AshbySourceTests(unittest.TestCase):
    def test_public_jobs_are_filtered_and_normalized(self):
        payload = {
            "jobs": [
                {
                    "id": "job-us",
                    "title": "Operations Associate",
                    "location": "Remote",
                    "address": {"postalAddress": {
                        "addressCountry": "United States",
                    }},
                    "secondaryLocations": [],
                    "department": "Operations",
                    "team": "Customer Experience",
                    "isListed": True,
                    "isRemote": True,
                    "workplaceType": "Remote",
                    "descriptionPlain": "Requirements\n- Ability to communicate clearly",
                    "publishedAt": "2026-09-01T12:00:00Z",
                    "employmentType": "FullTime",
                    "jobUrl": "https://jobs.ashbyhq.com/example/job-us",
                    "applyUrl": "https://jobs.ashbyhq.com/example/job-us/application",
                    "compensation": {"summaryComponents": [{
                        "compensationType": "Salary",
                        "currencyCode": "USD",
                        "minValue": 20,
                        "maxValue": 25,
                        "interval": "1 HOUR",
                    }]},
                },
                {
                    "id": "job-secondary-us",
                    "title": "Support Specialist",
                    "location": "Multiple locations",
                    "address": {},
                    "secondaryLocations": [{
                        "location": "Denver, Colorado, United States",
                        "address": {
                            "addressLocality": "Denver",
                            "addressRegion": "Colorado",
                            "addressCountry": "USA",
                        },
                    }],
                    "isListed": True,
                    "isRemote": False,
                    "descriptionPlain": "Help customers with product questions.",
                    "employmentType": "PartTime",
                    "jobUrl": "https://jobs.ashbyhq.com/example/job-secondary-us",
                },
                {
                    "id": "job-unlisted",
                    "title": "Confidential Role",
                    "location": "United States",
                    "address": {},
                    "secondaryLocations": [],
                    "isListed": False,
                    "isRemote": False,
                    "jobUrl": "https://jobs.ashbyhq.com/example/job-unlisted",
                },
                {
                    "id": "job-non-us",
                    "title": "London Role",
                    "location": "London",
                    "address": {"postalAddress": {
                        "addressCountry": "United Kingdom",
                    }},
                    "secondaryLocations": [],
                    "isListed": True,
                    "isRemote": False,
                    "jobUrl": "https://jobs.ashbyhq.com/example/job-non-us",
                },
            ]
        }

        with patch("job_sources.ashby.fetch_json", return_value=payload) as fetch:
            source, records = ashby.fetch_jobs({
                "employer": "Example Employer",
                "board_name": "Example Board",
                "max_jobs": 20,
            })

        self.assertEqual(source, "Ashby:Example Board")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["external_job_id"], "job-us")
        self.assertEqual(records[0]["salary_min"], 20.0)
        self.assertEqual(records[0]["salary_max"], 25.0)
        self.assertEqual(records[0]["salary_period"], "hour")
        self.assertTrue(records[0]["is_remote"])
        self.assertIn("Denver", records[1]["location"])
        self.assertIsNone(records[0]["application_deadline"])
        self.assertIn("includeCompensation=true", fetch.call_args.args[0])

    def test_remote_only_excludes_non_remote_jobs(self):
        payload = {"jobs": [{
            "id": "onsite-job",
            "title": "Operations Associate",
            "location": "Denver, Colorado, United States",
            "address": {"postalAddress": {"addressCountry": "USA"}},
            "secondaryLocations": [],
            "isListed": True,
            "isRemote": False,
            "jobUrl": "https://jobs.ashbyhq.com/example/onsite-job",
        }]}
        with patch("job_sources.ashby.fetch_json", return_value=payload):
            _, records = ashby.fetch_jobs({
                "employer": "Example Employer",
                "board_name": "example",
                "remote_only": True,
            })
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
