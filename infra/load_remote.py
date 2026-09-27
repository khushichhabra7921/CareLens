"""Load the data into RDS from this machine, over TLS, then lock the database down again.

The database is normally unreachable from the internet. For the load only:
  1. make it publicly accessible and allow THIS machine's IP (and nothing else) on 5432;
  2. run scripts/db_setup.py and scripts/load_data.py against it with sslmode=verify-full;
  3. ALWAYS (even if the load fails): remove the IP rule, make it private again, and check
     that a connection from here now fails.

Run:  py -3.12 infra/load_remote.py            (full data in data/raw/csv)
      py -3.12 infra/load_remote.py --fixture  (the small test fixture, as a dry run)
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as c  # noqa: E402
from awscli import AwsError, aws  # noqa: E402
from deploy import find_db, find_sg, get_param  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CA_BUNDLE = REPO / "app" / "certs" / "rds-global-bundle.pem"


def my_ip() -> str:
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as response:
        return response.read().decode().strip()


def set_public(public: bool) -> None:
    aws("rds", "modify-db-instance", "--db-instance-identifier", c.DB_ID, "--apply-immediately",
        "--publicly-accessible" if public else "--no-publicly-accessible")
    # modify returns at once; wait until the change has actually been applied.
    aws("rds", "wait", "db-instance-available", "--db-instance-identifier", c.DB_ID, parse=False)
    for _ in range(60):
        db = find_db()
        if db["PubliclyAccessible"] == public and not db.get("PendingModifiedValues"):
            return
        time.sleep(10)
    raise SystemExit("RDS didn't apply the accessibility change in time.")


def ip_rule(cidr: str) -> dict:
    return {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
            "IpRanges": [{"CidrIp": cidr, "Description": "temporary: data load"}]}


def port_open(host: str) -> bool:
    try:
        with socket.create_connection((host, 5432), timeout=5):
            return True
    except OSError:
        return False


def run_scripts(host: str, csv_dir: Path) -> None:
    env = {**os.environ,
           "DB_HOST": host, "DB_PORT": "5432", "POSTGRES_DB": c.DB_NAME,
           "DB_SSLMODE": "verify-full", "DB_SSLROOTCERT": str(CA_BUNDLE),
           "POSTGRES_USER": c.DB_MASTER_USER,
           "POSTGRES_PASSWORD": get_param("DB_MASTER_PASSWORD", decrypt=True),
           "LOADER_PASSWORD": get_param("LOADER_PASSWORD", decrypt=True),
           "APP_DB_PASSWORD": get_param("APP_DB_PASSWORD", decrypt=True),
           "NAME_HASH_SALT": get_param("NAME_HASH_SALT", decrypt=True)}
    python = sys.executable
    subprocess.run([python, str(REPO / "scripts" / "db_setup.py")], env=env, check=True)
    subprocess.run([python, str(REPO / "scripts" / "load_data.py"), "--csv-dir", str(csv_dir)],
                   env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load data into RDS over TLS.")
    parser.add_argument("--fixture", action="store_true", help="load the small test fixture")
    args = parser.parse_args()
    csv_dir = REPO / ("tests/fixtures/synthea_mini" if args.fixture else "data/raw/csv")

    db = find_db()
    if db["DBInstanceStatus"] != "available":
        raise SystemExit(f"Database is {db['DBInstanceStatus']}; run: py -3.12 infra/ops.py start")
    host, db_sg = db["Endpoint"]["Address"], find_sg(c.DB_SG)
    cidr = f"{my_ip()}/32"
    print(f"Opening {host}:5432 to {cidr} only, for the load...")
    set_public(True)
    try:
        aws("ec2", "authorize-security-group-ingress", "--group-id", db_sg,
            "--ip-permissions", json.dumps([ip_rule(cidr)]))
        run_scripts(host, csv_dir)
    finally:
        print("Locking the database down again...")
        try:
            aws("ec2", "revoke-security-group-ingress", "--group-id", db_sg,
                "--ip-permissions", json.dumps([ip_rule(cidr)]))
        except AwsError as err:
            print(f"  (rule removal: {err})")
        set_public(False)
        print("  Connection from this machine now:",
              "STILL OPEN - check the security group!" if port_open(host) else "unreachable (good)")


if __name__ == "__main__":
    main()
