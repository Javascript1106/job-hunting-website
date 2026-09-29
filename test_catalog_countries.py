"""Tests for the U.S. and Canada catalog boundary."""

import unittest

from job_discovery import is_us_or_canada_location
from sync_jobs import filter_catalog_countries


class CatalogCountryTests(unittest.TestCase):
    def test_supported_locations_include_us_and_canada(self):
        supported = (
            "Denver, CO",
            "Toronto, ON",
            "Remote - United States",
            "Vancouver, British Columbia, Canada",
            "New York, NY; London, United Kingdom",
        )
        self.assertTrue(all(is_us_or_canada_location(value) for value in supported))

    def test_worldwide_and_other_countries_are_not_inferred_as_supported(self):
        unsupported = (
            "London, United Kingdom",
            "Berlin, Germany",
            "Remote - Europe",
            "Worldwide",
            "Location not listed",
        )
        self.assertFalse(any(is_us_or_canada_location(value) for value in unsupported))

    def test_sync_filter_keeps_only_configured_countries(self):
        records = [
            {"location": "Austin, TX", "title": "U.S."},
            {"location": "Montreal, QC", "title": "Canada"},
            {"location": "Paris, France", "title": "France"},
        ]
        filtered = filter_catalog_countries(records, ["US", "CA"])
        self.assertEqual(
            [record["title"] for record in filtered],
            ["U.S.", "Canada"],
        )

    def test_provider_country_filter_is_trusted(self):
        records = [{"location": "Remote", "title": "Verified U.S. remote"}]
        filtered = filter_catalog_countries(
            records, ["US", "CA"], verified_countries=["US"]
        )
        self.assertEqual(filtered, records)


if __name__ == "__main__":
    unittest.main()
