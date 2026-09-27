"""Every name, size and limit of the AWS deployment, in one place.

Chosen to stay far inside the Free plan's credits (see docs/DEPLOYMENT.md for the costs):
single-AZ micro instances, no NAT gateway, no load balancer, no Elastic IP, stopped by default.
"""

REGION = "ap-south-1"            # Mumbai
PROJECT = "carelens"
TAGS = {"project": PROJECT}      # every resource gets this, so costs can be filtered by it

# --- cost controls (created before anything else)
BUDGET_NAME = "carelens-monthly"
BUDGET_LIMIT_USD = 15
BUDGET_ALERTS_USD = [5, 15]      # email when ACTUAL monthly cost goes above each
BUDGET_EMAIL = "kkhushi1_be24@thapar.edu"

# --- container registry
ECR_REPO = "carelens"
ECR_KEEP_IMAGES = 3

# --- secrets (SSM Parameter Store, standard tier = free)
PARAM_PREFIX = "/carelens/"

# --- database
DB_ID = "carelens-db"
DB_CLASS = "db.t4g.micro"
DB_ENGINE_VERSION_MAJOR = "16"
DB_STORAGE_GB = 20
DB_BACKUP_DAYS = 1               # the minimum that keeps automated backups on
DB_NAME = "carelens"
DB_MASTER_USER = "carelens_admin"
DB_SUBNET_GROUP = "carelens-db-subnets"

# --- app server
INSTANCE_NAME = "carelens-app"
INSTANCE_TYPE = "t4g.micro"      # ARM (Graviton): the image is built for linux/arm64
ROOT_VOLUME_GB = 8
AMI_PARAMETER = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
EC2_ROLE = "carelens-ec2"
APP_SG = "carelens-app-sg"
DB_SG = "carelens-db-sg"

# --- HTTPS front door
CLOUDFRONT_COMMENT = "carelens"
# AWS-managed policies, looked up by name at deploy time: no caching (every request reaches the
# app, which has its own cache); forward all viewer headers (incl. X-API-Key) except Host.
CACHE_POLICY_NAME = "Managed-CachingDisabled"
ORIGIN_REQUEST_POLICY_NAME = "Managed-AllViewerExceptHostHeader"
ORIGIN_READ_TIMEOUT_SECONDS = 60   # an LLM report can take ~40 s (2 attempts x 20 s timeout)

# --- CI/CD
GITHUB_REPO = "khushichhabra7921/CareLens"
GITHUB_BRANCH = "main"
DEPLOY_ROLE = "carelens-github-deploy"

# --- cost guard: stop everything nightly in case a demo was left running (23:30 IST)
AUTO_STOP_SCHEDULE = "cron(30 23 * * ? *)"
AUTO_STOP_TIMEZONE = "Asia/Kolkata"
SCHEDULER_ROLE = "carelens-scheduler"
