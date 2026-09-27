#!/bin/bash
# EC2 first-boot script (Amazon Linux 2023). Installs Docker and a systemd service that, on
# EVERY boot, reads the secrets from SSM Parameter Store, pulls the current image from ECR
# and runs the app on port 80. Secrets only ever live in /run (memory), never on disk.
set -euo pipefail

dnf install -y docker
systemctl enable --now docker

cat > /usr/local/bin/carelens-start.sh <<'SCRIPT'
#!/bin/bash
set -euo pipefail
REGION=ap-south-1
P=/carelens
get() { aws ssm get-parameter --region "$REGION" --name "$P/$1" --with-decryption \
          --query Parameter.Value --output text 2>/dev/null || true; }

TAG=$(get IMAGE_TAG)
if [ -z "$TAG" ]; then echo "No image deployed yet (/carelens/IMAGE_TAG missing)."; exit 0; fi
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

umask 077   # the env file below is readable by root only
{
  echo "DB_HOST=$(get DB_HOST)"
  echo "DB_PORT=5432"
  echo "POSTGRES_DB=carelens"
  echo "DB_SSLMODE=verify-full"
  echo "DB_SSLROOTCERT=/srv/app/certs/rds-global-bundle.pem"
  echo "APP_DB_PASSWORD=$(get APP_DB_PASSWORD)"
  echo "ADMIN_API_KEY=$(get ADMIN_API_KEY)"
  echo "NAME_HASH_SALT=$(get NAME_HASH_SALT)"
  echo "ORIGIN_VERIFY_SECRET=$(get ORIGIN_VERIFY_SECRET)"
  echo "TRUST_PROXY_HEADERS=true"
  echo "GROQ_API_KEY=$(get GROQ_API_KEY)"
  echo "LLM_MODEL=$(get LLM_MODEL)"
} > /run/carelens.env

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker pull "$REGISTRY/carelens:$TAG"
docker rm -f carelens 2>/dev/null || true
docker run -d --name carelens --restart unless-stopped -p 80:8000 \
  --env-file /run/carelens.env "$REGISTRY/carelens:$TAG"
docker image prune -f   # keep the small disk from filling up with old images
echo "CareLens $TAG started."
SCRIPT
chmod 700 /usr/local/bin/carelens-start.sh

cat > /etc/systemd/system/carelens.service <<'UNIT'
[Unit]
Description=CareLens app container
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/carelens-start.sh

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now carelens.service
