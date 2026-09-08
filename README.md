# Ephemeral Preview Platform

Self-service AWS preview environment platform that provisions isolated, end-to-end environments per feature group and automatically tears them down when branches are merged or deleted.

AWS CDK app + feature-group resolver + CI/CD that gives every feature group its
own **ephemeral, end-to-end preview environment**, so feature groups can be
tested **in parallel** instead of fighting over one shared dev environment.

This is the hub repo. The two microservices it deploys live in
[`preview-service-a`](../preview-service-a) and
[`preview-service-b`](../preview-service-b).

👉 **Design & rationale:** [`ARCHITECTURE.md`](ARCHITECTURE.md) -
**Submission write-up:** [`SUBMISSION.md`](SUBMISSION.md)

## TL;DR

- A feature branch is pushed -> one isolated environment spins up (the *other*
  service runs `main`). Branches that share a feature group get **one combined**
  environment; unrelated branches get **separate** ones.
- Each environment = its **own Aurora Serverless v2 cluster (writer + reader
  replica)** + both Fargate services, behind a shared ALB (Host-header routed).
- Merge/delete the branch -> the environment tears down. An hourly reaper sweeps
  orphans.

## Layout

```
preview-infra/
├── app.py                       # CDK entrypoint
├── cdk.json
├── preview_infra/
│   ├── config.py                # context -> typed config
│   ├── baseline_stack.py        # VPC, ALB, ECS cluster, ECR, main env
│   ├── ephemeral_env_stack.py   # one ephemeral env
│   └── constructs/
│       ├── database.py          # Aurora Serverless v2 (writer + reader)
│       ├── service.py           # one Fargate service + TG + ALB rule
│       └── environment.py       # Aurora + both services for one env
├── resolver/                    # PURE feature-group logic (unit-tested)
│   ├── feature_groups.py
│   ├── github.py                # discover open branches
│   └── cli.py                   # used by the orchestrator
├── tests/test_feature_groups.py
├── local/docker-compose.yml     # primary + streaming replica + both services
└── .github/workflows/           # orchestrate, reaper, baseline deploy
```

## Prerequisites

- Python managed by [`uv`](https://docs.astral.sh/uv/) - Node.js (for the CDK CLI
  via `npx`) - Docker (for image builds / local stack).

```bash
uv sync          # installs aws-cdk-lib + dev tools into .venv
```

## Run the resolver (no AWS needed)

```bash
# All four cases are unit-tested:
uv run pytest -q

# See the env matrix for any scenario:
uv run python -m resolver.cli --branches \
  '[{"repo":"a","name":"feature/checkout-flow"},{"repo":"b","name":"feature/search"}]'
```

## Run the whole system locally (no AWS needed)

A faithful mirror - Postgres **primary + streaming replica** + both services:

```bash
docker compose -f local/docker-compose.yml up --build
# Service A -> http://localhost:8001   Service B -> http://localhost:8002

curl localhost:8001/info | jq           # identity (service, env, replica?)
curl -X POST localhost:8001/records -H 'content-type: application/json' \
     -d '{"name":"demo","value":"hello"}'
curl localhost:8001/replica-check | jq  # writes to primary, reads from replica
```

## Deploy to AWS (sandbox)

> Use a **sandbox** account, not a shared one. Costs are dominated by one NAT
> gateway and each Aurora cluster's 0.5-ACU floor; teardown reclaims them.

```bash
export AWS_PROFILE=sandbox
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=ca-central-1

# One-time per account/region:
npx cdk bootstrap

# 1) Baseline + the `main` environment (builds images from sibling repos):
npx cdk deploy PreviewBaseline

# 2) An ephemeral environment for a feature group (A on a branch, B on main):
npx cdk deploy PreviewEnv-checkout-flow \
  --context slug=checkout-flow \
  --context a_branch=feature/checkout-flow \
  --context b_branch=main \
  --exclusively

# Exercise it (host-header routed; grab <alb-dns> from the stack outputs):
curl -H 'Host: checkout-flow-a.preview.local' http://<alb-dns>/info
curl -H 'Host: checkout-flow-a.preview.local' http://<alb-dns>/replica-check

# Tear it down:
npx cdk destroy PreviewEnv-checkout-flow --context slug=checkout-flow
```

Useful context flags: `--context cpu_arch=X86_64`, `--context nat_gateways=0`
(cheaper sandbox), `--context db_max_acu=4`, `--context image_mode=ecr`.

## Wire up the automated CI/CD

Once the three repos are on GitHub:

**On each service repo** set
- variables: `AWS_REGION`, `ECR_REPO` (`preview-service-a` / `-b`), `INFRA_REPO`
  (`<owner>/preview-infra`)
- secrets: `AWS_DEPLOY_ROLE_ARN` (OIDC), `INFRA_DISPATCH_TOKEN` (PAT that can
  dispatch to `preview-infra`)

**On `preview-infra`** set
- variables: `AWS_REGION`, `AWS_ACCOUNT_ID`, `SERVICE_A_REPO`, `SERVICE_B_REPO`
- secrets: `AWS_DEPLOY_ROLE_ARN`, optional `REPOS_READ_TOKEN` (only if the service
  repos are private)

Then: push a feature branch -> `ci.yml` builds+pushes the image and dispatches
`preview-sync` -> `orchestrate-preview.yml` resolves the desired environments and
reconciles (`cdk deploy` the new ones, delete orphans). Delete/merge the branch ->
`teardown.yml` dispatches and the environment is reaped.
