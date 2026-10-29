"""Tests for aggregate catalog coverage automation."""

import tempfile
import unittest
from pathlib import Path

from catalog_insights import build_catalog_insights, write_catalog_insights
from database import get_connection, initialize_database


class CatalogInsightsTests(unittest.TestCase):
    def test_reports_state_and_confirmed_teen_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "insights.db"
            initialize_database(database_path)
            connection = get_connection(database_path)
            try:
                connection.execute(
                    """INSERT INTO jobs (
                           title, company, location, pay, description,
                           requirements, schedule, experience, category,
                           application_method, application_url, status,
                           owner_user_id, source
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "Crew Member", "Example", "Salt Lake City, Utah",
                        "$15/hour", "Minimum age stated by employer: 16",
                        "No experience required", "Part-time", "Entry level",
                        "Food Service", "employer_website",
                        "https://example.com/job", "active", None, "Test",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            insights = build_catalog_insights(database_path)
            utah = next(
                row for row in insights["state_coverage"]
                if row["state"] == "UT"
            )
            self.assertEqual(utah["active_jobs"], 1)
            self.assertEqual(utah["confirmed_teen_jobs"], 1)
            western_priority = next(
                row for row in insights["western_coverage_priorities"]
                if row["state"] == "UT"
            )
            self.assertTrue(western_priority["needs_general_coverage"])
            self.assertTrue(western_priority["needs_confirmed_teen_coverage"])

    def test_writes_json_and_readable_markdown_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "insights.db"
            initialize_database(database_path)
            result = write_catalog_insights(database_path, root / "reports")

            self.assertTrue(Path(result["json_report"]).is_file())
            markdown = Path(result["markdown_report"]).read_text(encoding="utf-8")
            self.assertIn("# PathForge catalog insights", markdown)
            self.assertIn("## Teen-job coverage", markdown)
            self.assertIn("## Western-state priorities", markdown)
