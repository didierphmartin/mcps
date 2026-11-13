"""HTTP checks before any JSON-RPC handling.

Callers are server-side (the SynergyAI backend, a compiled program): no Origin, or a localhost page. A JSON content
type is required, so a browser cannot send a "simple" cross-site request without a CORS preflight.
"""
from __future__ import annotations

from urllib.parse import urlsplit

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def check(method: str, origin: str | None, content_type: str | None) -> tuple[int, str] | None:
    """(status, message) when the request is refused, else None."""
    if method != "POST":
        return 405, "POST only"
    if origin:
        try:
            host = urlsplit(origin).hostname
        except ValueError:
            host = None
        if not host or host.lower() not in _LOCAL_HOSTS:
            return 403, "origin not allowed"
    if content_type is None or not content_type.strip().lower().startswith("application/json"):
        return 415, "Content-Type must be application/json"
    return None
