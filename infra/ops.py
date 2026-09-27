"""Day-to-day commands for the on-demand deployment.

    py -3.12 infra/ops.py start    # start RDS + EC2, repoint CloudFront, wait until healthy
    py -3.12 infra/ops.py stop     # stop both (idle cost is only storage)
    py -3.12 infra/ops.py status   # what's running, credits left, spend this month

Running costs about $0.032/hour (RDS + EC2 + public IPv4). A nightly schedule stops
everything at 23:30 IST in case you forget.
"""

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as c  # noqa: E402
from awscli import AwsError, aws  # noqa: E402
from deploy import (  # noqa: E402
    account_id,
    find_db,
    find_distribution,
    find_instance,
    get_param,
    point_cloudfront_at,
    wait_instance_running,
)

HOURLY_USD = 0.021 + 0.0056 + 0.005   # RDS db.t4g.micro + EC2 t4g.micro + public IPv4


def start() -> None:
    db, instance = find_db(), find_instance()
    if db["DBInstanceStatus"] == "stopped":
        aws("rds", "start-db-instance", "--db-instance-identifier", c.DB_ID)
        print("Starting the database (a few minutes)...")
    if instance["State"]["Name"] == "stopped":
        aws("ec2", "start-instances", "--instance-ids", instance["InstanceId"])
        print("Starting the app server...")
    instance = wait_instance_running()
    point_cloudfront_at(instance["PublicDnsName"])
    aws("rds", "wait", "db-instance-available", "--db-instance-identifier", c.DB_ID,
        parse=False)
    # The app container starts at boot, so restart it now that the database is up.
    aws("ssm", "send-command", "--instance-ids", instance["InstanceId"],
        "--document-name", "AWS-RunShellScript",
        "--parameters", '{"commands":["systemctl restart carelens"]}')
    url = get_param("PUBLIC_URL")
    print(f"Waiting for {url}/health ...")
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=10) as response:
                if response.status == 200:
                    print(f"Up: {url}  (costs ~${HOURLY_USD:.3f}/hour; auto-stops at 23:30 IST)")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(10)
    print("Not healthy after 10 minutes. Check: py -3.12 infra/ops.py status")


def stop() -> None:
    instance, db = find_instance(), find_db()
    if instance and instance["State"]["Name"] in ("running", "pending"):
        aws("ec2", "stop-instances", "--instance-ids", instance["InstanceId"])
        print("Stopping the app server.")
    if db and db["DBInstanceStatus"] == "available":
        aws("rds", "stop-db-instance", "--db-instance-identifier", c.DB_ID)
        print("Stopping the database. (AWS restarts a stopped RDS after 7 days; the nightly "
              "schedule stops it again.)")
    print("Idle cost is storage only: about $3.37/month.")


def status() -> None:
    instance, db, dist = find_instance(), find_db(), find_distribution()
    print(f"App server : {instance['State']['Name'] if instance else 'not created'}")
    print(f"Database   : {db['DBInstanceStatus'] if db else 'not created'}")
    print(f"URL        : {'https://' + dist['DomainName'] if dist else 'not created'}")
    print(f"Image      : {get_param('IMAGE_TAG') or 'none deployed yet'}")
    plan = aws("freetier", "get-account-plan-state", region="us-east-1")
    print(f"Plan       : {plan['accountPlanType']}, "
          f"${plan['accountPlanRemainingCredits']['amount']:.2f} credits left, "
          f"expires {plan['accountPlanExpirationDate'][:10]}")
    try:
        spend = aws("budgets", "describe-budget", "--account-id", account_id(),
                    "--budget-name", c.BUDGET_NAME, region="us-east-1")["Budget"]
        actual = spend.get("CalculatedSpend", {}).get("ActualSpend", {})
        print(f"This month : ${float(actual.get('Amount', 0)):.2f} of the "
              f"${c.BUDGET_LIMIT_USD} budget (before credits; updates ~3x a day)")
    except AwsError as err:
        print(f"This month : unavailable ({err})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["start", "stop", "status"])
    {"start": start, "stop": stop, "status": status}[parser.parse_args().command]()
