"""Tests for the U.S.-only showcase catalog boundary."""

import json
import unittest
from pathlib import Path

from job_discovery import _is_us_location
from sync_jobs import filter_catalog_countries


class CatalogCountryTests(unittest.TestCase):
    def test_supported_locations_include_only_explicit_us_availability(self):
        supported = (
            "Denver, CO",
            "Remote - United States",
            "New York, NY; London, United Kingdom",
            "Canada, United States",
        )
        self.assertTrue(all(_is_us_location(value) for value in supported))

    def test_canada_and_other_countries_are_not_inferred_as_us(self):
        unsupported = (
            "Toronto, ON",
            "Vancouver, British Columbia, Canada",
            "Canada - Remote (ON, AB, BC, or NS Only)",
            "London, United Kingdom",
            "Berlin, Germany",
            "Remote - Europe",
            "Worldwide",
            "Location not listed",
        )
        self.assertFalse(any(_is_us_location(value) for value in unsupported))

    def test_sync_filter_keeps_only_us_records(self):
        records = [
            {"location": "Austin, TX", "title": "U.S."},
            {"location": "Montreal, QC", "title": "Canada"},
            {"location": "Paris, France", "title": "France"},
        ]
        filtered = filter_catalog_countries(records, ["US"])
        self.assertEqual(
            [record["title"] for record in filtered],
            ["U.S."],
        )

    def test_provider_country_filter_is_trusted(self):
        records = [{"location": "Remote", "title": "Verified U.S. remote"}]
        filtered = filter_catalog_countries(
            records, ["US"], verified_countries=["US"]
        )
        self.assertEqual(filtered, records)

    def test_source_configuration_is_us_only(self):
        configuration = json.loads(
            (Path(__file__).resolve().parent / "job_sources.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(configuration["catalog"]["countries"], ["US"])


if __name__ == "__main__":
    unittest.main()
