"""Configuration contracts for priority major-employer catalog sources."""

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


class MajorEmployerSourceTests(unittest.TestCase):
    def test_validated_major_employers_are_configured_once(self):
        configuration = json.loads(
            (PROJECT_ROOT / "job_sources.json").read_text(encoding="utf-8")
        )
        employers = [
            entry["employer"]
            for source_type, entries in configuration.items()
            if source_type not in {"catalog", "usajobs", "careeronestop"}
            for entry in entries
        ]
        self.assertEqual(employers.count("CVS Health"), 1)
        self.assertEqual(employers.count("Primark"), 1)
        self.assertEqual(employers.count("Five Below"), 1)
        self.assertEqual(employers.count("KnitWell Group"), 1)
        self.assertEqual(employers.count("Whataburger"), 1)

    def test_new_major_employers_use_bounded_official_feeds(self):
        configuration = json.loads(
            (PROJECT_ROOT / "job_sources.json").read_text(encoding="utf-8")
        )
        cvs = next(
            entry for entry in configuration["workday"]
            if entry["employer"] == "CVS Health"
        )
        primark = next(
            entry for entry in configuration["smartrecruiters"]
            if entry["employer"] == "Primark"
        )
        self.assertEqual(cvs["country_codes"], ["US"])
        self.assertLessEqual(cvs["max_jobs"], cvs["detail_scan_limit"])
        self.assertLessEqual(cvs["detail_workers"], 6)
        self.assertLessEqual(primark["max_jobs"], primark["detail_scan_limit"])
        self.assertFalse(cvs["confirmed_teen_only"])
        self.assertFalse(primark["confirmed_teen_only"])

    def test_new_teen_employers_are_us_only_and_bounded(self):
        configuration = json.loads(
            (PROJECT_ROOT / "job_sources.json").read_text(encoding="utf-8")
        )
        entries = {
            entry["employer"]: entry
            for entry in configuration["workday"]
        }
        for employer in ("Five Below", "KnitWell Group", "Whataburger"):
            with self.subTest(employer=employer):
                source = entries[employer]
                self.assertEqual(source["country_codes"], ["US"])
                self.assertLessEqual(source["max_jobs"], source["detail_scan_limit"])
                self.assertLessEqual(source["detail_workers"], 16)
                self.assertTrue(source["title_patterns"])
                self.assertTrue(source["search_queries"])

    def test_careeronestop_is_us_only_and_bounded(self):
        configuration = json.loads(
            (PROJECT_ROOT / "job_sources.json").read_text(encoding="utf-8")
        )["careeronestop"]
        self.assertEqual(configuration["country_codes"], ["US"])
        self.assertEqual(len(configuration["locations"]), 51)
        self.assertLessEqual(configuration["page_size"], 100)
        self.assertLessEqual(configuration["pages_per_location"], 5)
        self.assertLessEqual(configuration["max_jobs"], 5000)


if __name__ == "__main__":
    unittest.main()
