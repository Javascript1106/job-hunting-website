"""Reliability and safety tests for shared external job-source requests."""

import unittest
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from job_sources import common


class JobSourceCommonTests(unittest.TestCase):
    def test_fetch_json_retries_rate_limit_and_honors_retry_after(self):
        limited = HTTPError(
            "https://api.example.com/jobs",
            429,
            "Too Many Requests",
            {"Retry-After": "2"},
            None,
        )
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"jobs": []}'
        with patch("job_sources.common.urlopen", side_effect=[limited, response]), patch(
            "job_sources.common.time.sleep"
        ) as sleep:
            result = common.fetch_json("https://api.example.com/jobs")
        self.assertEqual(result, {"jobs": []})
        sleep.assert_called_once_with(2.0)

    def test_fetch_json_rejects_oversized_response(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b"x" * (common.MAX_JSON_BYTES + 1)
        with patch("job_sources.common.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "safe size limit"):
                common.fetch_json("https://api.example.com/jobs")


if __name__ == "__main__":
    unittest.main()
