"""Shared HTTP middleware configuration for the PathForge API."""

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware


def configure_http_middleware(app, is_production, configured_origins, development_origins):
    """Configure compression and environment-aware credentialed CORS."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(
            configured_origins
            if is_production
            else (configured_origins or development_origins)
        ),
        allow_origin_regex=(
            None
            if is_production or configured_origins
            else r"^http://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
        ),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)


async def apply_security_headers(request, call_next, is_production):
    """Apply browser security and private-response cache headers."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(self), payment=(), usb=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; "
        "img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'"
    )
    private_prefixes = (
        "/account", "/profile", "/applications", "/messages",
        "/notifications", "/dashboard-summary", "/analytics",
        "/saved-jobs", "/saved-searches", "/connected-guidance",
    )
    if request.url.path.startswith(private_prefixes):
        response.headers["Cache-Control"] = "no-store"
    if is_production and request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response
