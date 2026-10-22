"""Focused tests for catalog normalization, classification, and diversity."""

import json
import unittest
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database
from job_discovery import age_eligibility, discover_jobs, us_state_codes
from job_sources.common import classify_category, normalize_employment_type
from job_sources.smartrecruiters import _nationwide_order
from sync_jobs import catalog_health, record_source_health
from verify_job_links import plain_page_text


class CatalogQualityTests(unittest.TestCase):
    def test_every_job_filter_returns_cards_with_matching_evidence(self):
        now = datetime.now(timezone.utc)
        jobs = [
            {
                "id": 1,
                "title": "Crew Member",
                "company": "Neighborhood Market",
                "location": "Denver, CO",
                "category": "Retail",
                "employment_type": "Part-Time",
                "is_remote": 0,
                "experience": "No experience required",
                "requirements": "Minimum age stated by employer: 16. Training provided.",
                "description": (
                    "No cover letter is required. Applicants who need a reasonable "
                    "accommodation during the application process may contact recruiting."
                ),
                "application_method": "pathforge",
                "salary_min": 20,
                "salary_max": 22,
                "salary_period": "hour",
                "application_deadline": "2026-12-31",
                "source_url": "https://example.com/crew",
                "last_verified_at": now.isoformat(),
                "posted_at": now.isoformat(),
            },
            {
                "id": 2,
                "title": "Senior Remote Engineer",
                "company": "Worldwide Technology",
                "location": "Worldwide",
                "category": "Technology",
                "employment_type": "Full-Time",
                "is_remote": 1,
                "experience": "Experienced",
                "requirements": "Five years of experience required.",
                "description": "Build distributed software systems.",
                "posted_at": (now - timedelta(days=45)).isoformat(),
            },
        ]

        def result_ids(**filters):
            return {
                job["id"] for job in discover_jobs(
                    [dict(job) for job in jobs],
                    location_scope="all",
                    **filters,
                )
            }

        cases = [
            ({"query": "crew", "query_mode": "strict"}, {1}),
            ({"location": "Denver", "location_mode": "exact"}, {1}),
            ({"category": "Retail"}, {1}),
            ({"employment_type": "part-time"}, {1}),
            ({"remote": "onsite"}, {1}),
            ({"remote_eligibility": "anywhere"}, {2}),
            ({"experience": "first-job"}, {1}),
            ({"age_fit": "age-16-17"}, {1}),
            ({"date_posted": "7"}, {1}),
            ({"listing_quality": "pay"}, {1}),
            ({"listing_quality": "deadline"}, {1}),
            ({"listing_quality": "accommodation"}, {1}),
            ({"listing_quality": "complete"}, {1}),
            ({"application_feature": "direct_apply"}, {1}),
            ({"application_feature": "no_cover_letter"}, {1}),
            ({"application_feature": "accommodation_contact"}, {1}),
            ({"minimum_pay": 40_000}, {1}),
            ({"exclusions": "senior"}, {1}),
            ({"exclude_terms": "engineer"}, {1}),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                self.assertEqual(result_ids(**filters), expected)

    def test_link_verifier_extracts_visible_page_text(self):
        payload = b"<style>hidden</style><h1>Cashier &amp; Store Support</h1>"
        self.assertEqual(plain_page_text(payload), "cashier & store support")

    def test_age_eligibility_separates_confirmed_and_estimated_fit(self):
        confirmed = age_eligibility({
            "title": "Cashier",
            "requirements": "Minimum age stated by employer: 16.",
        })
        estimated = age_eligibility({
            "title": "Crew Member",
            "experience": "Entry level / no experience required",
        })
        adult = age_eligibility({
            "title": "Warehouse Associate",
            "requirements": "Applicants must be 18 years old.",
        })

        self.assertEqual(confirmed["age_eligibility"], "confirmed_16_17")
        self.assertEqual(confirmed["minimum_age"], 16)
        self.assertEqual(estimated["age_eligibility"], "possible_teen_fit")
        self.assertIsNone(estimated["minimum_age"])
        self.assertEqual(adult["age_eligibility"], "confirmed_18_plus")

    def test_years_of_experience_are_not_misread_as_minimum_age(self):
        result = age_eligibility({
            "title": "Mammography Technologist",
            "requirements": "At least 15 years of experience is preferred.",
        })
        self.assertEqual(result["age_eligibility"], "unknown")
        self.assertIsNone(result["minimum_age"])

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

    def test_first_job_filter_rejects_professional_credentials(self):
        jobs = [
            {"id": 1, "title": "Entry-Level Licensed Massage Therapist", "company": "Spa", "location": "Denver, CO", "experience": "Entry level", "requirements": "Active professional license required"},
            {"id": 2, "title": "Anesthesiologist", "company": "Hospital", "location": "Denver, CO", "experience": "Entry level", "requirements": "Medical degree and board certified"},
            {"id": 3, "title": "Crew Member", "company": "Restaurant", "location": "Denver, CO", "requirements": "No prior experience required. Training provided."},
        ]
        results = discover_jobs(jobs, location_scope="us", experience="first-job")
        self.assertEqual([job["title"] for job in results], ["Crew Member"])

    def test_strict_search_ignores_description_only_matches(self):
        jobs = [
            {"id": 1, "title": "Office Assistant", "company": "Example", "location": "Denver, CO", "category": "Administrative", "description": "Supports software engineers."},
            {"id": 2, "title": "Software Engineer", "company": "Example", "location": "Denver, CO", "category": "Technology", "description": "Builds products."},
        ]
        broad = discover_jobs(jobs, query="software engineer", location_scope="us")
        strict = discover_jobs(jobs, query="software engineer", query_mode="strict", location_scope="us")
        self.assertEqual({job["id"] for job in broad}, {1, 2})
        self.assertEqual([job["id"] for job in strict], [2])

    def test_broad_recommendations_include_starter_roles_near_the_top(self):
        jobs = [
            {"id": 1, "title": "Staff Engineer", "company": "Tech", "location": "New York, NY", "requirements": "8 years experience"},
            {"id": 2, "title": "Director", "company": "Finance", "location": "Boston, MA", "requirements": "5 years experience"},
            {"id": 3, "title": "Cashier", "company": "Market", "location": "Denver, CO", "requirements": "No experience required"},
        ]
        results = discover_jobs(jobs, location_scope="us")
        self.assertEqual(results[0]["title"], "Cashier")

    def test_teen_recommendations_rank_confirmed_age_before_estimates(self):
        jobs = [
            {"id": 1, "title": "Cashier", "company": "Market", "location": "Denver, CO", "experience": "No experience", "posted_at": "2026-10-20"},
            {"id": 2, "title": "Crew Member", "company": "Restaurant", "location": "Boise, ID", "requirements": "Minimum age stated by employer: 16."},
        ]
        results = discover_jobs(jobs, location_scope="us", age_fit="age-16-17")
        self.assertEqual(results[0]["title"], "Crew Member")

    def test_teen_source_scans_full_board_and_balances_states(self):
        configuration = json.loads(
            (Path(__file__).resolve().parent / "job_sources.json")
            .read_text(encoding="utf-8")
        )
        dominos = next(
            source for source in configuration["smartrecruiters"]
            if source["employer"] == "Domino's"
        )
        self.assertGreaterEqual(dominos["detail_scan_limit"], 5000)
        self.assertGreaterEqual(dominos["max_jobs"], 750)

        postings = [
            {"id": "co-1", "location": {"region": "CO"}},
            {"id": "co-2", "location": {"region": "CO"}},
            {"id": "ut-1", "location": {"region": "UT"}},
            {"id": "az-1", "location": {"region": "AZ"}},
        ]
        ordered = _nationwide_order(postings)
        self.assertEqual(
            [posting["location"]["region"] for posting in ordered[:3]],
            ["AZ", "CO", "UT"],
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

    def test_success_clears_superseded_failure_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovered-source.db"
            database.initialize_database(path)
            record_source_health(path, [{
                "source": "ashby",
                "employer": "Example Employer",
                "status": "failed",
                "fetched": 0,
                "error": "temporary failure",
            }])
            record_source_health(path, [{
                "source": "Ashby:example",
                "employer": "Example Employer",
                "status": "ok",
                "fetched": 12,
                "imported": 12,
                "excluded_by_country": 0,
            }])
            connection = sqlite3.connect(path)
            rows = connection.execute(
                "SELECT source, status FROM catalog_sync_status"
            ).fetchall()
            connection.close()
            self.assertEqual(rows, [("Ashby:example", "ok")])

    def test_catalog_health_reports_empty_failed_and_dropped_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog-health.db"
            database.initialize_database(path)
            previous = [{
                "source": "Lever:test",
                "employer": "Dropped Employer",
                "status": "ok",
                "fetched": 20,
                "imported": 20,
                "excluded_by_country": 0,
            }]
            current = [
                {**previous[0], "fetched": 4, "imported": 4},
                {
                    "source": "Ashby:empty",
                    "employer": "Empty Employer",
                    "status": "ok",
                    "fetched": 0,
                    "imported": 0,
                    "excluded_by_country": 0,
                },
                {
                    "source": "Greenhouse:failed",
                    "employer": "Failed Employer",
                    "status": "failed",
                    "fetched": 0,
                    "error": "HTTP 404",
                },
            ]
            record_source_health(path, previous)
            record_source_health(path, current)

            health = catalog_health(path, current)

            self.assertEqual(health["empty_sources"], ["Empty Employer"])
            self.assertEqual(health["failed_sources"], ["Failed Employer"])
            self.assertEqual(
                health["large_source_drops"],
                [{"employer": "Dropped Employer", "previous": 20, "current": 4}],
            )


if __name__ == "__main__":
    unittest.main()
