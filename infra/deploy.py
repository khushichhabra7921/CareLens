"""Create (or verify) every AWS resource for CareLens. Idempotent: each step looks for its
resource first and only creates what is missing, so it is safe to run again.

Usage (PowerShell, after `aws login --region ap-south-1`):
    py -3.12 infra/deploy.py                # all steps, in order
    py -3.12 infra/deploy.py --step rds     # one step
Steps: budget ecr params network iam rds ec2 cloudfront github scheduler
The budget step always runs first (cost controls before anything else).
"""

import argparse
import json
import secrets
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import budget  # noqa: E402
import config as c  # noqa: E402
from awscli import AwsError, aws, not_found  # noqa: E402

TAG_SPEC = [{"Key": k, "Value": v} for k, v in c.TAGS.items()]
TAG_ARGS = [f"Key={k},Value={v}" for k, v in c.TAGS.items()]


def log(message: str) -> None:
    print(f"  {message}")


@contextmanager
def json_file(obj):
    """Write obj to a temporary JSON file, yield a file:// URL for the CLI, then DELETE it.
    Keeps secrets (e.g. the DB master password) off the command line and off the disk."""
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(obj, f)
        f.close()
        yield f"file://{f.name}"
    finally:
        f.close()
        Path(f.name).unlink(missing_ok=True)


def account_id() -> str:
    return aws("sts", "get-caller-identity")["Account"]


# ------------------------------------------------------------------ ECR

def step_ecr() -> None:
    try:
        aws("ecr", "describe-repositories", "--repository-names", c.ECR_REPO)
        log(f"ECR repository {c.ECR_REPO} exists.")
    except AwsError as err:
        if not not_found(err):
            raise
        aws("ecr", "create-repository", "--repository-name", c.ECR_REPO,
            "--image-scanning-configuration", "scanOnPush=true",
            "--image-tag-mutability", "MUTABLE", "--tags", *TAG_ARGS)
        log(f"Created ECR repository {c.ECR_REPO} (scan on push).")
    policy = {"rules": [{"rulePriority": 1, "description": f"keep the last {c.ECR_KEEP_IMAGES}",
                         "selection": {"tagStatus": "any", "countType": "imageCountMoreThan",
                                       "countNumber": c.ECR_KEEP_IMAGES},
                         "action": {"type": "expire"}}]}
    aws("ecr", "put-lifecycle-policy", "--repository-name", c.ECR_REPO,
        "--lifecycle-policy-text", json.dumps(policy))
    log(f"Lifecycle policy: keep the newest {c.ECR_KEEP_IMAGES} images.")


# ------------------------------------------------------------------ SSM parameters

SECRET_PARAMS = ["DB_MASTER_PASSWORD", "LOADER_PASSWORD", "APP_DB_PASSWORD", "ADMIN_API_KEY",
                 "NAME_HASH_SALT", "ORIGIN_VERIFY_SECRET"]


def get_param(name: str, decrypt: bool = False) -> str | None:
    try:
        args = ["ssm", "get-parameter", "--name", c.PARAM_PREFIX + name]
        if decrypt:
            args.append("--with-decryption")
        return aws(*args)["Parameter"]["Value"]
    except AwsError as err:
        if "ParameterNotFound" in err.stderr:
            return None
        raise


def put_param(name: str, value: str, secure: bool, overwrite: bool = False) -> None:
    request = {"Name": c.PARAM_PREFIX + name, "Value": value, "Tier": "Standard",
               "Type": "SecureString" if secure else "String", "Overwrite": overwrite}
    if not overwrite:
        request["Tags"] = TAG_SPEC   # tags can only be given when creating
    with json_file(request) as url:
        aws("ssm", "put-parameter", "--cli-input-json", url)


def step_params() -> None:
    for name in SECRET_PARAMS:
        if get_param(name) is not None:
            log(f"{c.PARAM_PREFIX}{name} exists (not changed).")
            continue
        # token_urlsafe: letters, digits, - and _ only, valid for RDS passwords too.
        put_param(name, secrets.token_urlsafe(32), secure=True)
        log(f"Created {c.PARAM_PREFIX}{name} (SecureString, random, never printed).")


# ------------------------------------------------------------------ network

def default_vpc() -> tuple[str, list[str]]:
    vpcs = aws("ec2", "describe-vpcs", "--filters", "Name=is-default,Values=true")["Vpcs"]
    if not vpcs:
        raise SystemExit("No default VPC in this region. Create one: aws ec2 create-default-vpc")
    vpc_id = vpcs[0]["VpcId"]
    subnets = aws("ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}",
                  "Name=default-for-az,Values=true")["Subnets"]
    return vpc_id, sorted(s["SubnetId"] for s in subnets)


def find_sg(name: str) -> str | None:
    groups = aws("ec2", "describe-security-groups",
                 "--filters", f"Name=group-name,Values={name}")["SecurityGroups"]
    return groups[0]["GroupId"] if groups else None


def ensure_sg(name: str, description: str, vpc_id: str) -> str:
    existing = find_sg(name)
    if existing:
        log(f"Security group {name} exists ({existing}).")
        return existing
    spec = [{"ResourceType": "security-group",
             "Tags": TAG_SPEC + [{"Key": "Name", "Value": name}]}]
    group_id = aws("ec2", "create-security-group", "--group-name", name,
                   "--description", description, "--vpc-id", vpc_id,
                   "--tag-specifications", json.dumps(spec))["GroupId"]
    log(f"Created security group {name} ({group_id}).")
    return group_id


def add_ingress(group_id: str, permission: dict, label: str) -> None:
    try:
        aws("ec2", "authorize-security-group-ingress", "--group-id", group_id,
            "--ip-permissions", json.dumps([permission]))
        log(f"Allowed {label}.")
    except AwsError as err:
        if "InvalidPermission.Duplicate" not in err.stderr:
            raise
        log(f"Already allowed: {label}.")


def cloudfront_prefix_list() -> str:
    lists = aws("ec2", "describe-managed-prefix-lists", "--filters",
                "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing")
    return lists["PrefixLists"][0]["PrefixListId"]


def step_network() -> None:
    vpc_id, subnets = default_vpc()
    log(f"Default VPC {vpc_id}, {len(subnets)} subnets.")
    app_sg = ensure_sg(c.APP_SG, "CareLens app: HTTP from CloudFront only", vpc_id)
    db_sg = ensure_sg(c.DB_SG, "CareLens database: Postgres from the app only", vpc_id)
    add_ingress(app_sg, {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                         "PrefixListIds": [{"PrefixListId": cloudfront_prefix_list(),
                                            "Description": "CloudFront origin-facing"}]},
                "HTTP 80 from CloudFront's origin-facing IP ranges")
    add_ingress(db_sg, {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
                        "UserIdGroupPairs": [{"GroupId": app_sg,
                                              "Description": "CareLens app"}]},
                "Postgres 5432 from the app security group")
    try:
        aws("rds", "describe-db-subnet-groups", "--db-subnet-group-name", c.DB_SUBNET_GROUP)
        log(f"DB subnet group {c.DB_SUBNET_GROUP} exists.")
    except AwsError as err:
        if not not_found(err):
            raise
        aws("rds", "create-db-subnet-group", "--db-subnet-group-name", c.DB_SUBNET_GROUP,
            "--db-subnet-group-description", "CareLens default-VPC subnets",
            "--subnet-ids", *subnets, "--tags", *TAG_ARGS)
        log(f"Created DB subnet group {c.DB_SUBNET_GROUP}.")


# ------------------------------------------------------------------ IAM for EC2

def ensure_role(name: str, trust: dict, description: str) -> str:
    try:
        return aws("iam", "get-role", "--role-name", name, region="us-east-1")["Role"]["Arn"]
    except AwsError as err:
        if not not_found(err):
            raise
    arn = aws("iam", "create-role", "--role-name", name, "--description", description,
              "--assume-role-policy-document", json.dumps(trust), "--tags", *TAG_ARGS,
              region="us-east-1")["Role"]["Arn"]
    log(f"Created IAM role {name}.")
    return arn


def put_inline_policy(role: str, name: str, policy: dict) -> None:
    aws("iam", "put-role-policy", "--role-name", role, "--policy-name", name,
        "--policy-document", json.dumps(policy), region="us-east-1")


def step_iam() -> None:
    account = account_id()
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    ensure_role(c.EC2_ROLE, trust, "CareLens app server")
    # SSM agent: lets deployments run commands on the instance without SSH or open ports.
    aws("iam", "attach-role-policy", "--role-name", c.EC2_ROLE, "--policy-arn",
        "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore", region="us-east-1")
    put_inline_policy(c.EC2_ROLE, "carelens-app", {"Version": "2012-10-17", "Statement": [
        {"Sid": "PullOurImageOnly", "Effect": "Allow",
         "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability"],
         "Resource": f"arn:aws:ecr:{c.REGION}:{account}:repository/{c.ECR_REPO}"},
        {"Sid": "EcrLogin", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken",
         "Resource": "*"},
        {"Sid": "ReadOurParameters", "Effect": "Allow",
         "Action": ["ssm:GetParameter", "ssm:GetParameters"],
         "Resource": f"arn:aws:ssm:{c.REGION}:{account}:parameter/{c.PROJECT}/*"},
        {"Sid": "DecryptThemViaSsm", "Effect": "Allow", "Action": "kms:Decrypt",
         "Resource": "*",
         "Condition": {"StringEquals": {"kms:ViaService": f"ssm.{c.REGION}.amazonaws.com"}}},
    ]})
    log(f"Role {c.EC2_ROLE}: SSM agent + pull {c.ECR_REPO} + read /{c.PROJECT}/* parameters.")
    try:
        aws("iam", "get-instance-profile", "--instance-profile-name", c.EC2_ROLE,
            region="us-east-1")
        log(f"Instance profile {c.EC2_ROLE} exists.")
    except AwsError as err:
        if not not_found(err):
            raise
        aws("iam", "create-instance-profile", "--instance-profile-name", c.EC2_ROLE,
            "--tags", *TAG_ARGS, region="us-east-1")
        aws("iam", "add-role-to-instance-profile", "--instance-profile-name", c.EC2_ROLE,
            "--role-name", c.EC2_ROLE, region="us-east-1")
        log(f"Created instance profile {c.EC2_ROLE}.")


# ------------------------------------------------------------------ RDS

def find_db() -> dict | None:
    try:
        return aws("rds", "describe-db-instances",
                   "--db-instance-identifier", c.DB_ID)["DBInstances"][0]
    except AwsError as err:
        if not_found(err):
            return None
        raise


def latest_engine_version() -> str:
    versions = aws("rds", "describe-db-engine-versions", "--engine", "postgres",
                   "--engine-version", c.DB_ENGINE_VERSION_MAJOR,
                   "--query", "DBEngineVersions[].EngineVersion")
    return sorted(versions, key=lambda v: [int(p) for p in v.split(".")])[-1]


def step_rds() -> None:
    db = find_db()
    if db:
        log(f"RDS {c.DB_ID} exists (status: {db['DBInstanceStatus']}).")
        return
    password = get_param("DB_MASTER_PASSWORD", decrypt=True)
    if password is None:
        raise SystemExit("Run the params step first.")
    version = latest_engine_version()
    request = {
        "DBInstanceIdentifier": c.DB_ID, "DBInstanceClass": c.DB_CLASS,
        "Engine": "postgres", "EngineVersion": version, "DBName": c.DB_NAME,
        "MasterUsername": c.DB_MASTER_USER, "MasterUserPassword": password,
        "AllocatedStorage": c.DB_STORAGE_GB, "StorageType": "gp3",
        "MultiAZ": False, "PubliclyAccessible": False,
        "VpcSecurityGroupIds": [find_sg(c.DB_SG)], "DBSubnetGroupName": c.DB_SUBNET_GROUP,
        "BackupRetentionPeriod": c.DB_BACKUP_DAYS, "StorageEncrypted": True,
        "EnablePerformanceInsights": False, "MonitoringInterval": 0,
        "AutoMinorVersionUpgrade": True, "DeletionProtection": False,
        "CopyTagsToSnapshot": True, "Tags": TAG_SPEC,
        # No MaxAllocatedStorage: storage autoscaling stays off, so cost can't creep up.
    }
    with json_file(request) as url:
        aws("rds", "create-db-instance", "--cli-input-json", url)
    log(f"Creating RDS {c.DB_ID}: PostgreSQL {version}, {c.DB_CLASS}, {c.DB_STORAGE_GB} GB gp3, "
        "single-AZ, not public. This takes about 10 minutes.")


def wait_db_available() -> dict:
    log("Waiting for the database to be available...")
    aws("rds", "wait", "db-instance-available", "--db-instance-identifier", c.DB_ID,
        parse=False)
    db = find_db()
    put_param("DB_HOST", db["Endpoint"]["Address"], secure=False,
              overwrite=get_param("DB_HOST") is not None)
    log(f"Database available at {db['Endpoint']['Address']} (saved to {c.PARAM_PREFIX}DB_HOST).")
    return db


# ------------------------------------------------------------------ EC2

USER_DATA = Path(__file__).with_name("userdata.sh")


def find_instance() -> dict | None:
    reservations = aws("ec2", "describe-instances", "--filters",
                       f"Name=tag:Name,Values={c.INSTANCE_NAME}",
                       "Name=instance-state-name,Values=pending,running,stopping,stopped"
                       )["Reservations"]
    instances = [i for r in reservations for i in r["Instances"]]
    return instances[0] if instances else None


def step_ec2() -> None:
    instance = find_instance()
    if instance:
        log(f"EC2 {instance['InstanceId']} exists ({instance['State']['Name']}).")
        return
    ami = aws("ssm", "get-parameter", "--name", c.AMI_PARAMETER)["Parameter"]["Value"]
    _, subnets = default_vpc()
    tags = TAG_SPEC + [{"Key": "Name", "Value": c.INSTANCE_NAME}]
    request = {
        "ImageId": ami, "InstanceType": c.INSTANCE_TYPE, "MinCount": 1, "MaxCount": 1,
        "IamInstanceProfile": {"Name": c.EC2_ROLE},
        "NetworkInterfaces": [{"DeviceIndex": 0, "SubnetId": subnets[0],
                               "Groups": [find_sg(c.APP_SG)],
                               "AssociatePublicIpAddress": True}],
        # IMDSv2 only; hop limit 1 so containers can't reach the instance's credentials.
        "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled",
                            "HttpPutResponseHopLimit": 1},
        # "standard" CPU credits: when the burst credits run out it slows down instead of
        # billing extra ("unlimited" mode would charge for sustained CPU).
        "CreditSpecification": {"CpuCredits": "standard"},
        "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {
            "VolumeSize": c.ROOT_VOLUME_GB, "VolumeType": "gp3", "Encrypted": True,
            "DeleteOnTermination": True}}],
        "TagSpecifications": [{"ResourceType": "instance", "Tags": tags},
                              {"ResourceType": "volume", "Tags": tags}],
    }
    for attempt in range(6):   # a brand-new instance profile can take a few seconds to appear
        try:
            # --user-data (not inside the JSON): only this option base64-encodes the script.
            with json_file(request) as url:
                instance = aws("ec2", "run-instances", "--cli-input-json", url,
                               "--user-data", f"file://{USER_DATA}")["Instances"][0]
            break
        except AwsError as err:
            if "Invalid IAM Instance Profile" not in err.stderr or attempt == 5:
                raise
            time.sleep(10)
    log(f"Launched {instance['InstanceId']} ({c.INSTANCE_TYPE}, AMI {ami}).")


def wait_instance_running() -> dict:
    instance = find_instance()
    aws("ec2", "wait", "instance-running", "--instance-ids", instance["InstanceId"], parse=False)
    return find_instance()


# ------------------------------------------------------------------ CloudFront

def managed_policy_id(kind: str, name: str) -> str:
    """kind: 'cache' or 'origin-request'. Looks up an AWS-managed policy by its name."""
    listing = aws("cloudfront", f"list-{kind}-policies", "--type", "managed", region="us-east-1")
    key = "CachePolicyList" if kind == "cache" else "OriginRequestPolicyList"
    config_key = "CachePolicyConfig" if kind == "cache" else "OriginRequestPolicyConfig"
    inner = "CachePolicy" if kind == "cache" else "OriginRequestPolicy"
    for item in listing[key]["Items"]:
        if item[inner][config_key]["Name"] == name:
            return item[inner]["Id"]
    raise SystemExit(f"Managed CloudFront policy {name} not found")


def find_distribution() -> dict | None:
    # With no distributions at all the CLI prints nothing, so default to empty.
    listing = (aws("cloudfront", "list-distributions", region="us-east-1") or {}).get(
        "DistributionList", {})
    for d in listing.get("Items", []):
        if d["Comment"] == c.CLOUDFRONT_COMMENT:
            return d
    return None


def distribution_config(origin_dns: str, reference: str) -> dict:
    return {
        "CallerReference": reference, "Comment": c.CLOUDFRONT_COMMENT, "Enabled": True,
        "PriceClass": "PriceClass_200", "HttpVersion": "http2and3", "IsIPV6Enabled": True,
        "Origins": {"Quantity": 1, "Items": [{
            "Id": "carelens-ec2", "DomainName": origin_dns,
            "CustomOriginConfig": {
                "HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": "http-only",
                "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                "OriginReadTimeout": c.ORIGIN_READ_TIMEOUT_SECONDS, "OriginKeepaliveTimeout": 5},
            # The app rejects requests without this header, so it can't be reached by
            # going around this distribution.
            "CustomHeaders": {"Quantity": 1, "Items": [{
                "HeaderName": "X-Origin-Verify",
                "HeaderValue": get_param("ORIGIN_VERIFY_SECRET", decrypt=True)}]},
            "ConnectionAttempts": 3, "ConnectionTimeout": 10}]},
        "DefaultCacheBehavior": {
            "TargetOriginId": "carelens-ec2", "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST",
                                                          "PATCH", "DELETE"],
                               "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
            "CachePolicyId": managed_policy_id("cache", c.CACHE_POLICY_NAME),
            "OriginRequestPolicyId": managed_policy_id("origin-request",
                                                       c.ORIGIN_REQUEST_POLICY_NAME),
            "Compress": True},
    }


def step_cloudfront() -> None:
    existing = find_distribution()
    if existing:
        log(f"CloudFront distribution exists: https://{existing['DomainName']}")
        return
    instance = find_instance()
    if not instance or instance["State"]["Name"] != "running":
        raise SystemExit("Start the instance first (the origin is its public DNS name).")
    request = {"DistributionConfig": distribution_config(instance["PublicDnsName"],
                                                         f"carelens-{int(time.time())}"),
               "Tags": {"Items": TAG_SPEC}}
    with json_file(request) as url:
        created = aws("cloudfront", "create-distribution-with-tags",
                      "--distribution-config-with-tags", url, region="us-east-1")
    domain = created["Distribution"]["DomainName"]
    put_param("PUBLIC_URL", f"https://{domain}", secure=False,
              overwrite=get_param("PUBLIC_URL") is not None)
    log(f"Created CloudFront distribution: https://{domain} (takes a few minutes to deploy).")


def point_cloudfront_at(origin_dns: str) -> None:
    """After a restart the instance has a new public DNS name: update the origin."""
    d = find_distribution()
    if d is None:
        log("No CloudFront distribution yet; nothing to repoint.")
        return
    current = aws("cloudfront", "get-distribution-config", "--id", d["Id"], region="us-east-1")
    config_, etag = current["DistributionConfig"], current["ETag"]
    origin = config_["Origins"]["Items"][0]
    if origin["DomainName"] == origin_dns:
        log("CloudFront already points at this instance.")
        return
    origin["DomainName"] = origin_dns
    with json_file(config_) as url:
        aws("cloudfront", "update-distribution", "--id", d["Id"], "--if-match", etag,
            "--distribution-config", url, region="us-east-1")
    log(f"CloudFront origin updated to {origin_dns}.")


# ------------------------------------------------------------------ GitHub OIDC deploy role

OIDC_HOST = "token.actions.githubusercontent.com"


def ensure_oidc_provider() -> str:
    providers = aws("iam", "list-open-id-connect-providers",
                    region="us-east-1")["OpenIDConnectProviderList"]
    for p in providers:
        if p["Arn"].endswith(OIDC_HOST):
            log("GitHub OIDC provider exists.")
            return p["Arn"]
    arn = aws("iam", "create-open-id-connect-provider", "--url", f"https://{OIDC_HOST}",
              "--client-id-list", "sts.amazonaws.com", "--tags", *TAG_ARGS,
              region="us-east-1")["OpenIDConnectProviderArn"]
    log("Created the GitHub OIDC provider (GitHub Actions can get short-lived AWS credentials).")
    return arn


def step_github() -> None:
    account = account_id()
    provider = ensure_oidc_provider()
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Federated": provider},
        "Action": "sts:AssumeRoleWithWebIdentity",
        # Only workflows running on the main branch of this one repository.
        "Condition": {"StringEquals": {
            f"{OIDC_HOST}:aud": "sts.amazonaws.com",
            f"{OIDC_HOST}:sub": f"repo:{c.GITHUB_REPO}:ref:refs/heads/{c.GITHUB_BRANCH}"}}}]}
    arn = ensure_role(c.DEPLOY_ROLE, trust, "GitHub Actions deploys CareLens")
    aws("iam", "update-assume-role-policy", "--role-name", c.DEPLOY_ROLE,
        "--policy-document", json.dumps(trust), region="us-east-1")
    repo_arn = f"arn:aws:ecr:{c.REGION}:{account}:repository/{c.ECR_REPO}"
    put_inline_policy(c.DEPLOY_ROLE, "carelens-deploy", {"Version": "2012-10-17", "Statement": [
        {"Sid": "EcrLogin", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken",
         "Resource": "*"},
        {"Sid": "PushOurImageOnly", "Effect": "Allow", "Resource": repo_arn,
         "Action": ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage",
                    "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]},
        {"Sid": "RecordDeployedTag", "Effect": "Allow",
         "Action": ["ssm:PutParameter", "ssm:GetParameter"],
         "Resource": [f"arn:aws:ssm:{c.REGION}:{account}:parameter/{c.PROJECT}/IMAGE_TAG",
                      f"arn:aws:ssm:{c.REGION}:{account}:parameter/{c.PROJECT}/PUBLIC_URL"]},
        {"Sid": "FindTheInstance", "Effect": "Allow", "Action": "ec2:DescribeInstances",
         "Resource": "*"},
        {"Sid": "RestartOnlyOurInstance", "Effect": "Allow", "Action": "ssm:SendCommand",
         "Resource": f"arn:aws:ec2:{c.REGION}:{account}:instance/*",
         "Condition": {"StringEquals": {"ssm:resourceTag/project": c.PROJECT}}},
        {"Sid": "WithTheShellDocument", "Effect": "Allow", "Action": "ssm:SendCommand",
         "Resource": f"arn:aws:ssm:{c.REGION}::document/AWS-RunShellScript"},
        {"Sid": "ReadCommandResults", "Effect": "Allow", "Action": "ssm:GetCommandInvocation",
         "Resource": "*"},
    ]})
    log(f"Deploy role {c.DEPLOY_ROLE}: push {c.ECR_REPO}, set IMAGE_TAG, restart the app. "
        f"Role ARN: {arn}")


# ------------------------------------------------------------------ nightly auto-stop

def step_scheduler() -> None:
    account = account_id()
    instance = find_instance()
    if not instance:
        raise SystemExit("Create the instance first.")
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "scheduler.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": account}}}]}
    role_arn = ensure_role(c.SCHEDULER_ROLE, trust, "Nightly auto-stop for CareLens")
    put_inline_policy(c.SCHEDULER_ROLE, "carelens-stop", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "ec2:StopInstances",
         "Resource": f"arn:aws:ec2:{c.REGION}:{account}:instance/{instance['InstanceId']}"},
        {"Effect": "Allow", "Action": "rds:StopDBInstance",
         "Resource": f"arn:aws:rds:{c.REGION}:{account}:db:{c.DB_ID}"}]})
    targets = {
        "carelens-auto-stop-ec2": ("arn:aws:scheduler:::aws-sdk:ec2:stopInstances",
                                   {"InstanceIds": [instance["InstanceId"]]}),
        "carelens-auto-stop-rds": ("arn:aws:scheduler:::aws-sdk:rds:stopDBInstance",
                                   {"DbInstanceIdentifier": c.DB_ID}),
    }
    time.sleep(10)   # a just-created role can take a few seconds before Scheduler accepts it
    for name, (target_arn, payload) in targets.items():
        request = {"Name": name, "ScheduleExpression": c.AUTO_STOP_SCHEDULE,
                   "ScheduleExpressionTimezone": c.AUTO_STOP_TIMEZONE,
                   "FlexibleTimeWindow": {"Mode": "OFF"}, "State": "ENABLED",
                   "Description": "Cost guard: stop CareLens every night",
                   "Target": {"Arn": target_arn, "RoleArn": role_arn,
                              "Input": json.dumps(payload),
                              "RetryPolicy": {"MaximumRetryAttempts": 0}}}
        exists = True
        try:
            aws("scheduler", "get-schedule", "--name", name)
        except AwsError as err:
            if not not_found(err):
                raise
            exists = False
        with json_file(request) as url:
            aws("scheduler", "update-schedule" if exists else "create-schedule",
                "--cli-input-json", url)
        log(f"{'Updated' if exists else 'Created'} schedule {name}: "
            f"{c.AUTO_STOP_SCHEDULE} {c.AUTO_STOP_TIMEZONE}.")


# ------------------------------------------------------------------ main

STEPS = {"budget": budget.ensure_budget, "ecr": step_ecr, "params": step_params,
         "network": step_network, "iam": step_iam, "rds": step_rds, "ec2": step_ec2,
         "cloudfront": step_cloudfront, "github": step_github, "scheduler": step_scheduler}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify CareLens AWS resources.")
    parser.add_argument("--step", choices=list(STEPS), help="run a single step")
    args = parser.parse_args()
    steps = [args.step] if args.step else list(STEPS)
    for name in steps:
        print(f"[{name}]")
        STEPS[name]()


if __name__ == "__main__":
    main()
