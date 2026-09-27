"""Smoke tests against a running CareLens site (local or live). Standard library only.

Usage:  py -3.12 scripts/smoke_test.py https://xxxx.cloudfront.net
        py -3.12 scripts/smoke_test.py http://127.0.0.1:8000
Exits 1 if any check fails. Never needs the admin key: report creation is only checked to be
refused without one.

Set SMOKE_ORIGIN_SECRET to send CloudFront's X-Origin-Verify header, to test the AWS server
directly through an SSM tunnel (bypassing CloudFront). Never pass it on the command line.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

EXPECTED_ANALYSES = 8


def fetch(url: str, method: str = "GET", body: dict | None = None, redirect: bool = True):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if os.environ.get("SMOKE_ORIGIN_SECRET"):
        headers["X-Origin-Verify"] = os.environ["SMOKE_ORIGIN_SECRET"]
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener() if redirect else urllib.request.build_opener(
        NoRedirect())
    try:
        with opener.open(request, timeout=30) as r:
            # r.headers looks names up case-insensitively (HTTP header names are).
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main() -> int:
    base = sys.argv[1].rstrip("/")
    checks = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  (' + detail + ')' if detail else ''}")

    started = time.perf_counter()
    status, _, body = fetch(f"{base}/health")
    check("/health is 200 and the database is ok", status == 200 and '"ok"' in body,
          f"{status} {body[:80]}")
    check("first response time", True, f"{time.perf_counter() - started:.1f}s")

    status, _, body = fetch(f"{base}/api/analyses")
    ids = [a["id"] for a in json.loads(body)["analyses"]] if status == 200 else []
    check(f"/api/analyses lists {EXPECTED_ANALYSES} analyses", len(ids) == EXPECTED_ANALYSES,
          f"{status}, {len(ids)} found")

    for analysis_id in ids:
        status, _, body = fetch(f"{base}/api/analyses/{analysis_id}")
        small = []
        if status == 200:
            for table in json.loads(body)["tables"]:
                for row in table["rows"]:
                    small += [f"{k}={v}" for k, v in row.items()
                              if type(v) is int and 1 <= v <= 10
                              and k not in ("period", "cost_rank")]
        check(f"/api/analyses/{analysis_id} is 200 and shows no count from 1 to 10",
              status == 200 and not small, f"{status}{', ' + small[0] if small else ''}")

    status, _, _ = fetch(f"{base}/api/reports", "POST", {"analysis_id": "care-gaps"})
    check("POST /api/reports without the admin key is refused (401)", status == 401, str(status))

    status, headers, body = fetch(f"{base}/")
    csp = headers.get("Content-Security-Policy", "")
    check("dashboard loads with the disclaimer banner",
          status == 200 and "Synthetic data. Not clinical advice." in body, str(status))
    check("dashboard has a same-origin-only Content-Security-Policy", "script-src 'self'" in csp)

    if base.startswith("https://"):
        status, headers, _ = fetch("http://" + base[len("https://"):] + "/health",
                                   redirect=False)
        check("plain HTTP is redirected to HTTPS", status in (301, 302, 307, 308)
              and headers.get("Location", "").startswith("https://"), str(status))

    print(f"\n{sum(checks)}/{len(checks)} checks passed.")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
