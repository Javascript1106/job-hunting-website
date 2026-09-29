"""Contract tests for the public Workable career-site adapter."""

import unittest
from unittest.mock import patch

from job_sources import workable


class WorkableSourceTests(unittest.TestCase):
    def test_public_jobs_are_normalized_and_remote_filter_works(self):
        payload = {"jobs": [{
            "shortcode": "ABC123",
            "title": "Software Engineer",
            "location": {"city": "Remote", "country": "United States"},
            "workplace_type": "remote",
            "department": {"name": "Engineering"},
            "description": "Requirements<p>Experience with Python</p>",
            "employment_type": "Full-time",
            "url": "https://apply.workable.com/example/j/ABC123/",
            "published_on": "2026-09-02",
        }, {
            "shortcode": "ONSITE",
            "title": "Office Manager",
            "location": "Denver, Colorado",
            "workplace_type": "on-site",
            "url": "https://apply.workable.com/example/j/ONSITE/",
        }]}
        with patch("job_sources.workable.fetch_json", return_value=payload) as fetch:
            source, records = workable.fetch_jobs({
                "employer": "Example Employer",
                "account_subdomain": "Example",
                "remote_only": True,
            })

        self.assertEqual(source, "Workable:example")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_job_id"], "ABC123")
        self.assertTrue(records[0]["is_remote"])
        self.assertIn("details=true", fetch.call_args.args[0])

    def test_rejects_unknown_payload_shape(self):
        with patch("job_sources.workable.fetch_json", return_value={"data": {}}):
            with self.assertRaisesRegex(ValueError, "unexpected Workable"):
                workable.fetch_jobs({
                    "employer": "Example",
                    "account_subdomain": "example",
                })


if __name__ == "__main__":
    unittest.main()
