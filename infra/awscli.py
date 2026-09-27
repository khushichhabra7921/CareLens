"""Tiny wrapper around the AWS CLI, so the infra scripts use the same `aws login` session
you use in the terminal (short-lived credentials, no access keys stored anywhere)."""

import json
import shutil
import subprocess
from pathlib import Path

DEFAULT_CLI = Path(r"C:\Program Files\Amazon\AWSCLIV2\aws.exe")


class AwsError(Exception):
    def __init__(self, args, stderr):
        super().__init__(f"aws {' '.join(args[:3])} ... failed: {stderr.strip()[:500]}")
        self.stderr = stderr


def cli_path() -> str:
    found = shutil.which("aws")
    if found:
        return found
    if DEFAULT_CLI.exists():
        return str(DEFAULT_CLI)
    raise SystemExit("AWS CLI not found. Install it, then run: aws login --region ap-south-1")


def aws(*args, region: str = "ap-south-1", parse: bool = True):
    """Run one AWS CLI command and return its JSON output (or None if it printed nothing)."""
    # Always pass a region: `aws login` doesn't save a default one. Budgets, CloudFront and
    # IAM are global services and are called with region="us-east-1".
    cmd = [cli_path(), *map(str, args), "--output", "json", "--no-cli-pager", "--region", region]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise AwsError(list(map(str, args)), result.stderr)
    if not parse or not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def not_found(err: AwsError) -> bool:
    """True if the error just means 'that resource doesn't exist'."""
    markers = ("NotFound", "NoSuchEntity", "does not exist", "NoSuch", "not found",
               "InvalidGroup.NotFound", "DBInstanceNotFound", "RepositoryNotFoundException",
               "ParameterNotFound", "ResourceNotFoundException")
    return any(m in err.stderr for m in markers)
