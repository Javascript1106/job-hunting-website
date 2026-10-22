"""Security and parsing tests for public job-link verification."""

import socket
import unittest
from unittest.mock import patch

from verify_job_links import plain_page_text, validate_public_url, verify_listing


class VerifyJobLinksTests(unittest.TestCase):
    @patch("verify_job_links.socket.getaddrinfo")
    def test_accepts_public_https_address(self, getaddrinfo):
        getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        self.assertEqual(validate_public_url("https://example.com/job/1"), "https://example.com/job/1")

    def test_rejects_local_private_and_credential_urls(self):
        with self.assertRaises(ValueError):
            validate_public_url("http://localhost/admin")
        with self.assertRaises(ValueError):
            validate_public_url("file:///etc/passwd")
        with self.assertRaises(ValueError):
            validate_public_url("https://user:secret@example.com/job")
        with patch("verify_job_links.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]):
            with self.assertRaises(ValueError):
                validate_public_url("http://example.test/job")

    def test_blocked_url_never_reaches_network_opener(self):
        job = {"id": 7, "title": "Cashier", "application_url": "http://localhost/private", "source_url": None}
        with patch("verify_job_links.build_opener") as opener:
            result = verify_listing(job)
        self.assertEqual(result["result"], "blocked")
        opener.assert_not_called()

    def test_page_text_removes_scripts_and_decodes_entities(self):
        text = plain_page_text(b"<script>hidden</script><h1>Cashier &amp; Clerk</h1>")
        self.assertEqual(text, "cashier & clerk")


if __name__ == "__main__":
    unittest.main()
