"""Run a read-only local smoke test of PathForge's showcase-critical surfaces."""

import sqlite3
import time
from pathlib import Path

import main


STATIC_TARGETS = (("home", "index.html"), ("jobs_page", "jobs.html"), ("login_page", "login.html"))


def run_showcase_smoke_test():
    """Exercise files, routes, and catalog reads without needing a running server."""
    results = []
    root = Path(__file__).resolve().parent
    for name, relative_path in STATIC_TARGETS:
        started = time.perf_counter()
        path = root / relative_path
        try:
            content = path.read_text(encoding="utf-8")
            results.append({"name": name, "path": relative_path,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                            "passed": "<html" in content.lower() and "PathForge" in content})
        except Exception as error:
            results.append({"name": name, "path": relative_path, "passed": False,
                            "error": f"{type(error).__name__}: {str(error)[:160]}"})
    routes = set(main.app.openapi().get("paths", {}))
    for name, path in (("job_search_route", "/jobs/search"), ("email_health_route", "/health/email")):
        results.append({"name": name, "path": path, "elapsed_ms": 0, "passed": path in routes})
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
