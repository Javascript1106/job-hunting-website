"""Run a read-only local smoke test of PathForge's showcase-critical surfaces."""

import sqlite3
import time
from pathlib import Path

import main


STATIC_TARGETS = (
    ("home", "index.html", ("homeHeroTitle", "Explore Jobs")),
    ("jobs_page", "jobs.html", ("jobSearchForm", "loadMoreJobsButton")),
    ("resource_center", "learning-center.html", ("resource-topic-nav", "careerAssistant")),
    ("login_page", "login.html", ("loginForm", "loginSubmitButton")),
    ("registration_page", "register.html", ("registerForm", "registerSubmitButton")),
)


def run_showcase_smoke_test():
    """Exercise files, routes, and catalog reads without needing a running server."""
    results = []
    root = Path(__file__).resolve().parent
    for name, relative_path, required_markers in STATIC_TARGETS:
        started = time.perf_counter()
        path = root / relative_path
        try:
            content = path.read_text(encoding="utf-8")
            missing = [marker for marker in required_markers if marker not in content]
            results.append({"name": name, "path": relative_path,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                            "passed": "<html" in content.lower() and "PathForge" in content and not missing,
                            "missing_markers": missing})
        except Exception as error:
            results.append({"name": name, "path": relative_path, "passed": False,
                            "error": f"{type(error).__name__}: {str(error)[:160]}"})
    routes = set(main.app.openapi().get("paths", {}))
    for name, path in (("job_search_route", "/jobs/search"), ("email_health_route", "/health/email")):
        results.append({"name": name, "path": path, "elapsed_ms": 0, "passed": path in routes})
    root_routes = [route for route in main.app.routes if getattr(route, "path", None) == "/"]
    root_redirect = main.home()
    results.append({
        "name": "site_root_route",
        "path": "/",
        "elapsed_ms": 0,
        "passed": (
            len(root_routes) == 1
            and root_redirect.status_code == 307
            and root_redirect.headers.get("location") == "/index.html"
        ),
    })
    started = time.perf_counter()
    try:
        connection = sqlite3.connect(main.DB_NAME, timeout=5)
        connection.execute("SELECT id, title FROM jobs WHERE status = 'active' LIMIT 1").fetchall()
        connection.close()
        results.append({"name": "catalog_read", "path": "jobs database",
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "passed": True})
    except Exception as error:
        results.append({"name": "catalog_read", "path": "jobs database", "passed": False,
                        "error": f"{type(error).__name__}: {str(error)[:160]}"})
    return {
        "status": "success" if all(row["passed"] for row in results) else "attention_required",
        "checks": results,
        "slowest_ms": max((row.get("elapsed_ms", 0) for row in results), default=0),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_showcase_smoke_test(), indent=2))
