"""Delete EVERY CareLens resource in AWS, then list anything still tagged project=carelens.

Order matters (things that depend on others go first): schedules -> CloudFront -> EC2 ->
RDS (no final snapshot, automated backups deleted) -> any leftover snapshots -> subnet group
-> security groups -> IAM roles/instance profile/OIDC provider -> parameters -> ECR (with
images) -> budget (last, so cost alerts keep working until everything else is gone).

Run:  py -3.12 infra/teardown.py            (asks you to type the project name first)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as c  # noqa: E402
from awscli import AwsError, aws, not_found  # noqa: E402
from deploy import (  # noqa: E402
    OIDC_HOST,
    find_db,
    find_distribution,
    find_instance,
    find_sg,
    json_file,
)


def attempt(label: str, *args, region: str = c.REGION) -> None:
    """Run a delete; 'already gone' counts as success."""
    try:
        aws(*args, region=region)
        print(f"  deleted: {label}")
    except AwsError as err:
        if not_found(err):
            print(f"  already gone: {label}")
        else:
            raise


def delete_cloudfront() -> None:
    d = find_distribution()
    if not d:
        print("  already gone: CloudFront distribution")
        return
    current = aws("cloudfront", "get-distribution-config", "--id", d["Id"], region="us-east-1")
    cfg, etag = current["DistributionConfig"], current["ETag"]
    if cfg["Enabled"]:
        cfg["Enabled"] = False   # a distribution must be disabled (and deployed) before deletion
        with json_file(cfg) as url:
            aws("cloudfront", "update-distribution", "--id", d["Id"], "--if-match", etag,
                "--distribution-config", url, region="us-east-1")
        print("  disabling CloudFront (takes a few minutes)...")
    aws("cloudfront", "wait", "distribution-deployed", "--id", d["Id"], region="us-east-1",
        parse=False)
    etag = aws("cloudfront", "get-distribution", "--id", d["Id"], region="us-east-1")["ETag"]
    attempt("CloudFront distribution", "cloudfront", "delete-distribution", "--id", d["Id"],
            "--if-match", etag, region="us-east-1")


def delete_role(name: str) -> None:
    try:
        for policy in aws("iam", "list-role-policies", "--role-name", name,
                          region="us-east-1")["PolicyNames"]:
            aws("iam", "delete-role-policy", "--role-name", name, "--policy-name", policy,
                region="us-east-1")
        for policy in aws("iam", "list-attached-role-policies", "--role-name", name,
                          region="us-east-1")["AttachedPolicies"]:
            aws("iam", "detach-role-policy", "--role-name", name,
                "--policy-arn", policy["PolicyArn"], region="us-east-1")
        for profile in aws("iam", "list-instance-profiles-for-role", "--role-name", name,
                           region="us-east-1")["InstanceProfiles"]:
            aws("iam", "remove-role-from-instance-profile", "--role-name", name,
                "--instance-profile-name", profile["InstanceProfileName"], region="us-east-1")
            attempt(f"instance profile {profile['InstanceProfileName']}", "iam",
                    "delete-instance-profile", "--instance-profile-name",
                    profile["InstanceProfileName"], region="us-east-1")
    except AwsError as err:
        if not not_found(err):
            raise
    attempt(f"IAM role {name}", "iam", "delete-role", "--role-name", name, region="us-east-1")


def main() -> None:
    answer = input(f"This deletes ALL CareLens AWS resources and data. Type '{c.PROJECT}' "
                   "to continue: ")
    if answer.strip() != c.PROJECT:
        raise SystemExit("Cancelled.")

    print("[schedules]")
    for name in ("carelens-auto-stop-ec2", "carelens-auto-stop-rds"):
        attempt(f"schedule {name}", "scheduler", "delete-schedule", "--name", name)

    print("[cloudfront]")
    delete_cloudfront()

    print("[ec2]")
    instance = find_instance()
    if instance:
        aws("ec2", "terminate-instances", "--instance-ids", instance["InstanceId"])
        aws("ec2", "wait", "instance-terminated", "--instance-ids", instance["InstanceId"],
            parse=False)
        print(f"  deleted: instance {instance['InstanceId']} (its disk is deleted with it)")
    else:
        print("  already gone: instance")

    print("[rds]")
    if find_db():
        attempt("database", "rds", "delete-db-instance", "--db-instance-identifier", c.DB_ID,
                "--skip-final-snapshot", "--delete-automated-backups")
        aws("rds", "wait", "db-instance-deleted", "--db-instance-identifier", c.DB_ID,
            parse=False)
    else:
        print("  already gone: database")
    for snap in aws("rds", "describe-db-snapshots", "--db-instance-identifier",
                    c.DB_ID)["DBSnapshots"]:
        if snap["SnapshotType"] == "manual":
            attempt(f"snapshot {snap['DBSnapshotIdentifier']}", "rds", "delete-db-snapshot",
                    "--db-snapshot-identifier", snap["DBSnapshotIdentifier"])
    attempt("DB subnet group", "rds", "delete-db-subnet-group",
            "--db-subnet-group-name", c.DB_SUBNET_GROUP)

    print("[security groups]")
    for name in (c.DB_SG, c.APP_SG):   # db first: it references the app group
        group = find_sg(name)
        if group:
            for _ in range(12):   # network interfaces can take a moment to disappear
                try:
                    aws("ec2", "delete-security-group", "--group-id", group)
                    print(f"  deleted: security group {name}")
                    break
                except AwsError as err:
                    if "DependencyViolation" not in err.stderr:
                        raise
                    time.sleep(10)
        else:
            print(f"  already gone: security group {name}")

    print("[iam]")
    for role in (c.EC2_ROLE, c.DEPLOY_ROLE, c.SCHEDULER_ROLE):
        delete_role(role)
    attempt(f"instance profile {c.EC2_ROLE}", "iam", "delete-instance-profile",
            "--instance-profile-name", c.EC2_ROLE, region="us-east-1")
    for p in aws("iam", "list-open-id-connect-providers",
                 region="us-east-1")["OpenIDConnectProviderList"]:
        if p["Arn"].endswith(OIDC_HOST):
            attempt("GitHub OIDC provider", "iam", "delete-open-id-connect-provider",
                    "--open-id-connect-provider-arn", p["Arn"], region="us-east-1")

    print("[parameters]")
    names = [p["Name"] for p in aws("ssm", "get-parameters-by-path", "--path",
                                    c.PARAM_PREFIX.rstrip("/"), "--recursive")["Parameters"]]
    if names:
        attempt(f"{len(names)} parameters", "ssm", "delete-parameters", "--names", *names)

    print("[ecr]")
    attempt(f"repository {c.ECR_REPO} and its images", "ecr", "delete-repository",
            "--repository-name", c.ECR_REPO, "--force")

    print("[budget]")
    account = aws("sts", "get-caller-identity")["Account"]
    attempt(f"budget {c.BUDGET_NAME}", "budgets", "delete-budget", "--account-id", account,
            "--budget-name", c.BUDGET_NAME, region="us-east-1")

    print("[check]")
    left = []
    for region in (c.REGION, "us-east-1"):
        left += aws("resourcegroupstaggingapi", "get-resources", "--tag-filters",
                    f"Key=project,Values={c.PROJECT}", region=region)["ResourceTagMappingList"]
    # The tagging index can lag a few minutes behind deletions.
    print("  Nothing tagged project=carelens is left." if not left else
          "  Still listed (may just be the index lagging; re-run in a few minutes):\n    "
          + "\n    ".join(r["ResourceARN"] for r in left))


if __name__ == "__main__":
    main()
