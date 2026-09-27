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
    """The visitor's IP address, for the rate limit.

    Behind CloudFront every request arrives from a CloudFront server, so with
    TRUST_PROXY_HEADERS we use X-Forwarded-For instead. CloudFront APPENDS the real viewer IP
    to that header, so the last entry is the one CloudFront added; anything before it could
    have been typed by the client and is ignored. Only safe because the app can be reached
    through CloudFront alone (security group + origin secret header)."""
    if request.app.state.settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def origin_verified(request: Request) -> bool:
    """True unless ORIGIN_VERIFY_SECRET is set and the request lacks CloudFront's header."""
    secret = request.app.state.settings.origin_verify_secret
    if secret is None:
        return True
    given = request.headers.get("X-Origin-Verify", "")
    return secrets.compare_digest(given.encode(), secret.get_secret_value().encode())


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
