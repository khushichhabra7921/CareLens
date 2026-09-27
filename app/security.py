"""Admin API key check, per-IP rate limit, and browser security headers."""

import secrets
import threading
import time
from collections import deque

from fastapi import HTTPException, Request


def check_api_key(request: Request) -> None:
    """Raise 401 unless the X-API-Key header matches ADMIN_API_KEY."""
    expected = request.app.state.settings.admin_api_key.get_secret_value()
    given = request.headers.get("X-API-Key", "")
    # compare_digest takes the same time whether the first or last character differs,
    # so an attacker can't guess the key one character at a time by timing responses.
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")


class RateLimiter:
    """Sliding window: at most `limit` requests per `window` seconds per key (client IP).

    In memory, so it resets on restart and isn't shared between processes; enough for one
    small server. Behind a proxy or load balancer every request would share the proxy's IP;
    see docs/DECISIONS.md (M5)."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record one request for `key`, or raise 429 if it is over the limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()  # forget requests older than the window
            if len(hits) >= self.limit:
                retry_after = int(hits[0] + self.window - now) + 1
                raise HTTPException(status_code=429, detail="Too many report requests.",
                                    headers={"Retry-After": str(retry_after)})
            hits.append(now)
            if len(self._hits) > 10_000:  # don't let a flood of IPs grow memory forever
                self._hits = {k: v for k, v in self._hits.items() if v}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Sent with every response. The Content-Security-Policy only allows scripts, styles and
# data from this same site: even if an attacker got text into the page, the browser
# would refuse to run injected inline scripts.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
DASHBOARD_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                 "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
