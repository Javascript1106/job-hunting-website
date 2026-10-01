"""Focused tests for catalog normalization, classification, and diversity."""

import unittest

from job_discovery import discover_jobs
from job_sources.common import classify_category, normalize_employment_type


class CatalogQualityTests(unittest.TestCase):
    def test_frontline_and_underserved_categories(self):
        cases = {
            "Restaurant Crew Member": "Food Service",
            "Guest Service Associate": "Retail",
            "Hotel Front Desk Agent": "Hospitality",
            "HVAC Apprentice": "Skilled Trades",
            "CDL Truck Driver": "Transportation",
            "Production Worker": "Manufacturing",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify_category(title), expected)

    def test_provider_schedule_values_are_normalized(self):
        cases = {
            "parttime_fixed_term": "Part-Time",
            "FullTime": "Full-Time",
            "Summer Internship": "Internship",
            "seasonal-hourly": "Seasonal",
            "temporary assignment": "Temporary",
            "contractor": "Contract",
            "Not listed": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_employment_type(raw), expected)

    def test_broad_recommendations_are_employer_diverse(self):
        jobs = []
        for index in range(8):
            jobs.append({
                "id": index,
                "title": f"Role {index}",
                "company": "Large Employer" if index < 6 else f"Employer {index}",
                "location": "Denver, CO",
                "category": "Other",
                "description": "",
                "status": "active",
            })
        results = discover_jobs(jobs, location_scope="us")
        self.assertLessEqual(
            sum(job["company"] == "Large Employer" for job in results[:4]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
