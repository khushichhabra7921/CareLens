# Deployment (AWS, Mumbai `ap-south-1`, on-demand)

CareLens runs on the AWS **Free plan**: AWS can never charge the card; the account closes if
the credits run out or the plan period ends (**2027-03-27** for this account). So the goal is to
stay far inside the credits. Every resource is tagged `project=carelens`.

## Architecture

```
browser --HTTPS--> CloudFront (free, stable https://xxxx.cloudfront.net)
                       | HTTP; only CloudFront's IP ranges may connect, and every request
                       | must carry the secret X-Origin-Verify header
                       v
                 EC2 t4g.micro (Amazon Linux 2023, Docker, app as app_readonly)
                       | TLS, sslmode=verify-full against the AWS RDS CA bundle
                       v
                 RDS PostgreSQL 16, db.t4g.micro, single-AZ, NOT publicly accessible
```

Why EC2, not App Runner: App Runner is **no longer open to new customers** (AWS notice, checked
2026-09-27). EC2 in the default VPC also keeps RDS private with no NAT Gateway: the app and the
database talk inside the VPC, and the app reaches Groq and ECR through its public IP.

## Resources and costs

Prices from the AWS Pricing API for `ap-south-1`, on-demand, fetched 2026-09-27. On accounts
created after 15 July 2025 there is no free RDS usage: all of it comes out of credits.

| Resource | Settings | Price | Stopped | Per running hour |
|---|---|---|---|---|
| AWS Budget | $15/month, email at $5 and $15, measured **before** credits | free | $0 | - |
| ECR repository | private, scan on push, keeps the last 3 images | $0.10/GB-month | ~$0.02/month | - |
| SSM parameters | standard tier SecureStrings (`/carelens/*`) | free | $0 | - |
| Security groups | app: 80 from CloudFront only, no SSH; db: 5432 from app only | free | $0 | - |
| RDS db.t4g.micro | PostgreSQL 16, 20 GB gp3, single-AZ, 1-day backups, encrypted | $0.021/h + $0.131/GB-month | $2.62/month | $0.021 |
| EC2 t4g.micro | AL2023 ARM, 8 GB gp3, IMDSv2, standard CPU credits | $0.0056/h + $0.0912/GB-month | $0.73/month | $0.0056 |
| Public IPv4 | on EC2 only while running (released when stopped) | $0.005/h | $0 | $0.005 |
| CloudFront | HTTPS, no caching | always-free 1 TB, 10 M requests | $0 | - |
| GitHub OIDC + IAM roles | deploy role limited to this repo's `main` branch | free | $0 | - |
| EventBridge Scheduler | stops EC2 and RDS nightly at 23:30 IST | free tier | $0 | - |
| **Total** | | | **$3.37/month** | **$0.0316** |

Projection to 2027-03-27 (6 months): idle 6 x $3.37 = $20.22, plus 30 demo hours a month
(180 h x $0.0316 = $5.69), plus setup: **about $26 of the $100 credit**. Three of this plan's
steps (EC2 launch, RDS database, budget) are AWS credit activities worth $20 each.

Forbidden and not used: NAT Gateway, load balancer, Elastic IP, Multi-AZ, Performance
Insights paid tier, storage autoscaling. Also never enable AWS Organizations, Control Tower or
the HIPAA account designation: AWS automatically moves a Free plan account to the Paid plan if
you do.

## Runbook (PowerShell, repo root)

```
aws login --region ap-south-1            # short-lived credentials, no access keys stored
py -3.12 infra/deploy.py                 # create/verify everything (idempotent)
py -3.12 infra/load_remote.py            # one-time data load over TLS (opens and re-closes RDS)
py -3.12 infra/ops.py start              # before a demo (~5 min)
py -3.12 infra/ops.py stop               # after it (nightly auto-stop is the safety net)
py -3.12 infra/ops.py status             # state, credits left, spend this month
py -3.12 scripts/smoke_test.py https://<cloudfront-domain>
py -3.12 infra/teardown.py               # delete everything, including snapshots and images
```

## Security

- RDS is never publicly accessible, except during `load_remote.py`, which opens it to one
  IP (`/32`) and **always** closes it again in a `finally` block, then checks from this machine
  that it is unreachable.
- TLS to RDS is enforced by the server (`rds.force_ssl`) and verified by the client
  (`verify-full` with AWS's CA bundle in the image).
- Secrets live only in SSM Parameter Store (SecureString, KMS-encrypted) and, on the instance,
  in a root-only env file in `/run` (memory). They are never in git, the image or CloudFront logs.
- No SSH: the instance has no key pair and no port 22. Administration goes through SSM.
- IMDSv2 required, hop limit 1: containers can't reach the instance's AWS credentials.
- GitHub Actions uses OIDC: the deploy role can only be assumed by workflows on `main` of
  this repository, and can only push this image, record its tag and restart this instance.
- Known gap: CloudFront to EC2 is plain HTTP inside AWS's network (the instance has no
  certificate of its own). CloudFront VPC origins would remove it; left as a next step.
