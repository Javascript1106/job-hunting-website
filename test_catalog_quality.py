"""Focused tests for catalog normalization, classification, and diversity."""

import unittest
import sqlite3
import tempfile
from pathlib import Path

import database
from job_discovery import discover_jobs, us_state_codes
from job_sources.common import classify_category, normalize_employment_type
from sync_jobs import record_source_health


class CatalogQualityTests(unittest.TestCase):
    def test_frontline_and_underserved_categories(self):
        cases = {
            "Restaurant Crew Member": "Food Service",
            "Guest Service Associate": "Retail",
            "Hotel Front Desk Agent": "Hospitality",
            "HVAC Apprentice": "Skilled Trades",
            "CDL Truck Driver": "Transportation",
            "Production Worker": "Manufacturing",
            "Youth Program Assistant": "Community & Social Services",
            "Police Officer": "Public Safety",
            "Product Manager": "Product Management",
            "Product Designer": "Design",
            "Aircraft Mechanic": "Skilled Trades",
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

    def test_state_coverage_extracts_codes_and_names(self):
        self.assertEqual(us_state_codes("Denver, CO / Austin, Texas"), {"CO", "TX"})
        self.assertEqual(us_state_codes("Washington, D.C."), {"DC"})

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

    def test_source_health_retains_the_previous_import_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "health.db"
            database.initialize_database(path)
            first = [{
                "source": "Lever:test",
                "employer": "Test Employer",
                "status": "ok",
                "fetched": 20,
                "imported": 20,
                "excluded_by_country": 0,
            }]
            second = [{**first[0], "fetched": 4, "imported": 4}]
            record_source_health(path, first)
            record_source_health(path, second)
            connection = sqlite3.connect(path)
            row = connection.execute(
                "SELECT imported, previous_imported FROM catalog_sync_status"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (4, 20))


if __name__ == "__main__":
    unittest.main()
