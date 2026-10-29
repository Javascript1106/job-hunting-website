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
            if source_type not in {"catalog", "usajobs"}
            for entry in entries
        ]
        self.assertEqual(employers.count("CVS Health"), 1)
        self.assertEqual(employers.count("Primark"), 1)

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
        self.assertLessEqual(primark["max_jobs"], primark["detail_scan_limit"])
        self.assertFalse(cvs["confirmed_teen_only"])
        self.assertFalse(primark["confirmed_teen_only"])


if __name__ == "__main__":
    unittest.main()
