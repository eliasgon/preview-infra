# Implementation Notes

> Three repos: **preview-infra** (this one - CDK, resolver, CI/CD),
> **preview-service-a**, **preview-service-b**. Start with
> [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What's built (against the brief)

- ✅ **Baseline infra** - VPC, shared ALB, ECS Fargate cluster, ECR, and a
  long-lived `main` environment, all in CDK (Python).
- ✅ **Two repos**, each a FastAPI + Postgres CRUD app with a Dockerfile
  (identical code, distinguished by `SERVICE_NAME`; they share one DB).
- ✅ **Ephemeral environments** that spin up on a feature-branch push, pairing
  branches into **feature groups** and producing exactly the four required cases
  (A-only, B-only, A+B-combined, A+B-separate). Pure, unit-tested resolver.
- ✅ **End-to-end & isolated** - each env has its own Aurora Serverless v2 cluster
  **with a reader replica**; apps write to the writer and read from the reader.
- ✅ **Teardown** on merge/branch-delete, plus an hourly reaper for orphans.
- ✅ **Verified**: 21 unit tests pass; the local Compose stack runs the full
  system with real streaming replication (`replica-check` ~2 ms lag); and the
  whole thing was **deployed live to AWS** - baseline + `main` (both services
  reachable through the ALB, replica-check confirming the Aurora reader at
  ~300 ms lag) and an ephemeral `checkout-flow` environment alongside it, with a
  record written to the ephemeral env absent from `main` (isolated databases).
- ✅ **CI/CD proven end-to-end**: pushing a `feature/checkout-flow` branch ran
  the service CI (test, build, push to ECR), which dispatched the orchestrator;
  it resolved the feature group and `cdk deploy`d the environment via GitHub
  OIDC into AWS, with no manual step.

## 1. Process, assumptions, key decisions

**Process.** Requirements -> clarifying questions (deploy target, repo layout,
stack) -> build bottom-up, verifying each layer before moving on: (1) the
microservice + tests, (2) duplicate to the second repo, (3) the feature-group
resolver + tests - the intellectual core, (4) the CDK stacks + `cdk synth`,
(5) CI/CD workflows, (6) a local Compose mirror I used to prove the app and
replication actually work, (7) docs. I kept everything runnable at every step.

**Key assumptions.**
- Deploy target is a **sandbox** AWS account (not a shared/company one); a
  take-home shouldn't run live in a real environment.
- "Shared database" = both services share one cluster per env, each owning its
  own table.
- A "feature group" links branches by **branch name** (or an explicit
  `feature-group:` PR label). Same name across repos => same env.
- Reviewers value a provably-correct core + a runnable local demo over a
  long-lived live deployment.

**Key decisions / trade-offs.**
- **Fargate + Aurora Serverless v2** over EKS: far less operational surface, the
  replica comes managed, and it scales to a low floor between tests. Trade-off:
  an idle cluster still has a ~0.5-ACU floor - paid back by aggressive teardown.
- **Shared VPC/ALB/cluster, per-env DB + services**: spin-up is seconds, not the
  minutes a VPC-per-env would cost. Trade-off: envs share a network blast radius
  (acceptable for previews).
- **Host-header routing** over path-rewriting: needs no DNS/cert to demo (just a
  `Host:` header) and scales to many envs on one ALB; production points a
  wildcard record at it.
- **Reconcile loop** (desired vs. deployed) over per-event handlers: idempotent
  and self-healing; push/delete/merge all flow through one path.
- **Resolver as a pure module**: the tricky logic is unit-tested with zero AWS.
- **Two image modes** (`asset` for local/sandbox, `ecr` for CI) so `cdk deploy`
  "just works" from a laptop while CI stays build-free.

## 2. Am I happy with it?

Mostly yes. The part I'm happiest with is that the hard logic - which
environments should exist - is a small, pure, fully-tested function, and the rest
of the system is a thin, idempotent shell around it. The local Compose mirror
(primary + real streaming standby) means the whole thing is demonstrable end to
end without spending a cent. What keeps it from a clean "completely": I'd want it
running long enough in a real account to shake out IAM/quotas, and Aurora
Serverless v2's cold floor isn't the cheapest possible answer for very
short-lived envs.

## 3. What I'd do differently

- **Pause/resume instead of always-on**: stop ephemeral Fargate services (and
  consider Aurora auto-pause / a shared logical-DB-per-env model) when a PR is
  idle, to cut cost further.
- **Real DNS + HTTPS** from the start (wildcard ACM cert + Route 53) so preview
  URLs are clickable, not header-only.
- **Migrations** (Alembic) and a richer seed/anonymized-snapshot strategy instead
  of `create_all` + synthetic seed.
- **A status surface** - a comment back on the PR with the env's URLs and health,
  and per-env dashboards.
- Tighten ALB listener-rule **priority** allocation (currently hash-derived;
  a small allocator would remove any theoretical collision).

## 4. Where I got stuck / how I got unstuck

- **`cdk synth` needed credentials** for a concrete account (the VPC's AZ
  lookup). Unstuck by synthesizing **env-agnostic** for verification (dummy AZs)
  and only binding account/region at deploy time.
- **Async SQLAlchemy** failed at runtime with "greenlet is required" - fixed by
  depending on `sqlalchemy[asyncio]` so greenlet is pulled in.
- **Local streaming replication** in Compose was fiddly (root vs. postgres user,
  `pg_hba` replication entry). Unstuck with a custom standby entrypoint that runs
  `pg_basebackup -R` as the `postgres` user and a primary init script that adds
  the replication role + `pg_hba` line. Verified with `/replica-check`.
- **Prefix-stripping for path routing** was awkward (ALB can't rewrite paths), so
  I switched to **Host-header routing**, which removed the problem entirely and
  happens to model the "header router" idea in the brief.
- The **first live deploy rolled back** on an em-dash in a security-group
  description (EC2 rejects non-ASCII there). Easy fix once I read the failure;
  also a good reminder to keep generated strings plain ASCII.
- On a fresh deploy the **app crash-looped against a still-starting Aurora**
  cluster. The tasks recovered once the DB came up, but I made startup wait it
  out: a bounded connection retry with backoff, plus a longer health-check grace
  period, so a cold cluster no longer trips the deployment circuit breaker.
