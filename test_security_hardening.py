"""Regression tests for PathForge's browser-facing security defaults."""

import unittest

from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from starlette.requests import Request

import main


def build_request(path="/"):
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("ascii"),
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })


class SecurityHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_security_headers_are_added(self):
        async def call_next(_request):
            return JSONResponse({"ok": True})

        response = await main.add_security_headers(build_request(), call_next)

        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertIn("camera=()", response.headers["permissions-policy"])

    async def test_private_responses_are_not_cached(self):
        async def call_next(_request):
            return JSONResponse({"private": True})

        response = await main.add_security_headers(
            build_request("/account/security-events"), call_next
        )

        self.assertEqual(response.headers["cache-control"], "no-store")


class PublicHealthTests(unittest.TestCase):
    def test_public_email_health_omits_provider_diagnostics(self):
        response = main.get_email_health()

        self.assertEqual(set(response), {"status"})
        self.assertNotIn("last_error_detail", response)


class FrontendServingTests(unittest.TestCase):
    def test_public_pages_and_assets_are_served_from_same_origin(self):
        with TestClient(main.app) as client:
            app = client.get("/app", follow_redirects=False)
            jobs = client.get("/jobs.html")
            script = client.get("/script.js")
            logo = client.get("/assets/branding/pathforge-logo.svg")

        self.assertEqual(app.status_code, 307)
        self.assertEqual(app.headers["location"], "/index.html")
        self.assertEqual(jobs.status_code, 200)
        self.assertIn("Opportunity search", jobs.text)
        self.assertEqual(script.status_code, 200)
        self.assertEqual(logo.status_code, 200)

    def test_private_project_files_are_not_served(self):
        with TestClient(main.app) as client:
            responses = [
                client.get("/.env"),
                client.get("/jobs.db"),
                client.get("/job_sources.json"),
                client.get("/backups/example.db"),
                client.get("/main.py"),
            ]

        self.assertTrue(all(response.status_code == 404 for response in responses))


class DevelopmentCorsTests(unittest.TestCase):
    def test_loopback_frontend_ports_are_allowed_in_development(self):
        with TestClient(main.app) as client:
            response = client.options(
                "/session-status",
                headers={
                    "Origin": "http://127.0.0.1:8765",
                    "Access-Control-Request-Method": "GET",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "http://127.0.0.1:8765",
        )
        self.assertEqual(
            response.headers["access-control-allow-credentials"],
            "true",
        )


if __name__ == "__main__":
    unittest.main()
