"""Load the data into RDS from this machine through a private SSM tunnel. RDS stays private.

How it works:
  1. AWS Systems Manager opens a port-forwarding session: localhost:15432 on this machine ->
     (HTTPS to SSM) -> the app server in the VPC -> RDS on 5432. No port is opened on the
     internet, RDS is never made public, and it doesn't matter if this machine's IP changes.
  2. scripts/db_setup.py and scripts/load_data.py connect to 127.0.0.1:15432 (hostaddr) but name
     the real RDS endpoint as the host, so TLS verify-full still checks RDS's certificate.
  3. The tunnel is ALWAYS closed afterwards, even if the load fails.

Why not open RDS to this machine's IP? That was the first design; it failed because this
network's public IP changed between creating the firewall rule and connecting (see
docs/DECISIONS.md, M8).

Needs the Session Manager plugin for the AWS CLI. Run:
    py -3.12 infra/load_remote.py            (full data in data/raw/csv)
    py -3.12 infra/load_remote.py --fixture  (the small test fixture, as a dry run)
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as c  # noqa: E402
from awscli import aws, cli_path  # noqa: E402
from deploy import find_db, find_instance, get_param  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CA_BUNDLE = REPO / "app" / "certs" / "rds-global-bundle.pem"
LOCAL_PORT = 15432
PLUGIN_DIR = Path(r"C:\Program Files\Amazon\SessionManagerPlugin\bin")


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def wait_ssm_online(instance_id: str) -> None:
    for _ in range(30):
        info = aws("ssm", "describe-instance-information", "--filters",
                   f"Key=InstanceIds,Values={instance_id}")["InstanceInformationList"]
        if info and info[0]["PingStatus"] == "Online":
            return
        time.sleep(10)
    raise SystemExit("The server's SSM agent isn't online; is the instance running?")


def open_tunnel(instance_id: str, db_host: str) -> tuple[subprocess.Popen, str | None]:
    params = {"host": [db_host], "portNumber": ["5432"], "localPortNumber": [str(LOCAL_PORT)]}
    # The CLI needs session-manager-plugin on PATH; a fresh install only reaches new terminals.
    env = {**os.environ, "PATH": os.environ["PATH"] + os.pathsep + str(PLUGIN_DIR)}
    process = subprocess.Popen(
        [cli_path(), "ssm", "start-session", "--region", c.REGION, "--target", instance_id,
         "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
         "--parameters", json.dumps(params)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    session_id = None
    deadline = time.time() + 60
    while time.time() < deadline:
        line = process.stdout.readline()
        match = re.search(r"SessionId: (\S+)", line or "")
        if match:
            session_id = match[1].rstrip(".")
        if "Waiting for connections" in (line or "") and port_open(LOCAL_PORT):
            return process, session_id
        if process.poll() is not None:
            raise SystemExit(f"The tunnel didn't start: {line.strip()}")
    close_tunnel(process, session_id)
    raise SystemExit("The tunnel didn't start within 60 seconds.")


def close_tunnel(process: subprocess.Popen, session_id: str | None) -> None:
    if session_id:
        try:
            aws("ssm", "terminate-session", "--session-id", session_id)
        except Exception as err:   # still kill the local process below
            print(f"  (terminate-session: {err})")
    # The CLI starts session-manager-plugin as a child: end the whole process tree.
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)


def run_scripts(db_host: str, csv_dir: Path) -> None:
    env = {**os.environ,
           "DB_HOST": db_host,             # used for the TLS certificate name check
           "DB_HOSTADDR": "127.0.0.1",     # ...but actually connect to the tunnel
           "DB_PORT": str(LOCAL_PORT), "POSTGRES_DB": c.DB_NAME,
           "DB_SSLMODE": "verify-full", "DB_SSLROOTCERT": str(CA_BUNDLE),
           "POSTGRES_USER": c.DB_MASTER_USER,
           "POSTGRES_PASSWORD": get_param("DB_MASTER_PASSWORD", decrypt=True),
           "LOADER_PASSWORD": get_param("LOADER_PASSWORD", decrypt=True),
           "APP_DB_PASSWORD": get_param("APP_DB_PASSWORD", decrypt=True),
           "NAME_HASH_SALT": get_param("NAME_HASH_SALT", decrypt=True)}
    for script, extra in (("db_setup.py", []), ("load_data.py", ["--csv-dir", str(csv_dir)])):
        subprocess.run([sys.executable, str(REPO / "scripts" / script), *extra], env=env,
                       check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load data into RDS through an SSM tunnel.")
    parser.add_argument("--fixture", action="store_true", help="load the small test fixture")
    args = parser.parse_args()
    csv_dir = REPO / ("tests/fixtures/synthea_mini" if args.fixture else "data/raw/csv")

    db, instance = find_db(), find_instance()
    if db["DBInstanceStatus"] != "available" or instance["State"]["Name"] != "running":
        raise SystemExit("Start the database and server first: py -3.12 infra/ops.py start")
    if db["PubliclyAccessible"]:
        raise SystemExit("RDS is publicly accessible; it should never be. Stopping.")
    db_host = db["Endpoint"]["Address"]
    wait_ssm_online(instance["InstanceId"])
    print(f"Opening an SSM tunnel: localhost:{LOCAL_PORT} -> {instance['InstanceId']} -> "
          f"{db_host}:5432 (RDS stays private)")
    process, session_id = open_tunnel(instance["InstanceId"], db_host)
    started = time.perf_counter()
    try:
        run_scripts(db_host, csv_dir)
    finally:
        close_tunnel(process, session_id)
        print(f"Tunnel closed. Local port {LOCAL_PORT} open now: {port_open(LOCAL_PORT)} "
              f"(should be False). Took {time.perf_counter() - started:.0f}s.")


if __name__ == "__main__":
    main()
