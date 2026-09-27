"""Files the deployed app needs must be committed, not just present on this laptop.
(The RDS CA bundle was once silently excluded by a '*.pem' ignore rule, and the image built in
GitHub Actions couldn't verify the database's certificate.)"""

import hashlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLE = "app/certs/rds-global-bundle.pem"
BUNDLE_SHA256 = "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"


def tracked(path: str) -> bool:
    out = subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=REPO,
                         capture_output=True, text=True)
    return out.returncode == 0


def test_rds_ca_bundle_is_committed_and_unchanged():
    assert tracked(BUNDLE), f"{BUNDLE} is not tracked by git (check .gitignore)"
    assert hashlib.sha256((REPO / BUNDLE).read_bytes()).hexdigest() == BUNDLE_SHA256


def test_vendored_chartjs_is_committed():
    assert tracked("app/static/vendor/chart.umd.min.js")
