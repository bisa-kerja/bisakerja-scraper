---
title: Scraper Deployment Operations
description: Runtime topology, deploy flow, rollback, hotfix, post-deploy checks, and recovery rules for scraper service operations.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: active
last_reviewed: 2026-05-02
---

# Scraper Deployment Operations

This page defines deployment expectations for the scraper service. Exact hosting can evolve, but runtime behavior must keep scraper DB, source credentials, normalized output, and Backend API handoff safe.

## Runtime Topology

| Component | Responsibility |
| --- | --- |
| Scraper app | Source adapters, internal endpoints, run orchestration |
| Scheduler | Daily pipeline trigger |
| Worker | Batch normalization, enrichment, sync, and retries |
| Local scraper DB | Raw captures, staging rows, run state, quarantine records |
| Main backend DB | Final Backend API-consumable job data |
| Secret store | Source credentials, service credentials, DB URLs |
| Logs/metrics backend | Structured run and stage evidence |

Baseline daily flow:

```text
01:00 scrape
  -> 01:30 normalize
  -> 02:00 enrich
  -> 03:00 sync
  -> 05:00-06:00 notify handoff
```

## Artifact Assumptions

- Runtime dependencies are pinned once implementation exists.
- Build/start commands are deterministic.
- Source credentials are provided by environment or secret manager only.
- Raw fixture files are sanitized before packaging or publishing.
- Scheduler and worker version match the scraper app version.
- Production deploy never points at local or test DB values.

## Container Runtime

The service image is built from the repository `Dockerfile`. The runtime image uses the official Python slim base, installs locked dependencies with `uv`, runs as a non-root `scraper` user, exposes the configured HTTP port, and defines a Docker healthcheck against `/health/live`.

Build the image:

```bash
docker build -t bisakerja-scraper:local .
```

Run the API with an explicit env file:

```bash
docker run --rm --env-file .env -p 8000:8000 bisakerja-scraper:local
```

Run the published image through Compose:

```bash
APP_IMAGE=ghcr.io/bisa-kerja/bisakerja-scraper:develop docker compose --env-file .env.production up -d
```

Run smoke checks before deploying an image:

```bash
PYTHONPATH=src uv run python -m cli.smoke config --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke health --env-file .env.example
PYTHONPATH=src uv run python -m cli.smoke dry-run --source dealls
```

Container rules:

- Provide all secrets through environment variables or a secret manager, never through image build arguments.
- Keep `.env`, raw capture files, local caches, and reference-only directories out of the image build context.
- Do not run the runtime process as root.
- Use `/health/live` for process health and `/health/ready` for database readiness.
- Run migrations before starting a deployment that depends on schema changes.

## GitHub Deployment Workflow

The active deployment workflow lives at `.github/workflows/deploy.yml`. It deploys `develop` automatically to the staging environment and supports manual dispatch for `develop` or `main`.

Workflow behavior:

| Stage | Expected result |
| --- | --- |
| Build image | Docker image is built from committed source and `uv.lock` |
| Publish image | GHCR receives branch tag and immutable SHA tag |
| Validate secrets | Deployment stops before SSH if required secrets are missing |
| Write env file | VPS receives `.env.production` from GitHub environment secret |
| Sync checkout | Remote repository is reset to the deploy branch only when clean |
| Pull image | Compose pulls the selected GHCR image |
| Migrate | `alembic upgrade head` runs before app startup |
| Start app | Compose starts the `app` service and waits for health |
| Verify | `/health/live` and `/health/ready` pass on localhost |
| Diagnose failure | Compose status and recent app logs are collected |

Required GitHub environment secrets:

| Secret | Purpose |
| --- | --- |
| `DEPLOY_VPS_HOST` | VPS host |
| `DEPLOY_VPS_PORT` | SSH port |
| `DEPLOY_VPS_USERNAME` | SSH user |
| `DEPLOY_VPS_KEY` | Private SSH key |
| `DEPLOY_REMOTE_PATH` | Existing remote repository path |
| `DEPLOY_ENV_FILE` | Full runtime env payload written to `.env.production` |
| `GHCR_READ_PACKAGES_TOKEN` | Token used by the VPS to pull GHCR image |
| `GH_USERNAME` | GHCR username for remote login |

Remote prerequisites:

- `DEPLOY_REMOTE_PATH` is a clean git checkout of this repository.
- The deploy user can run `docker compose`.
- `git`, `docker`, Docker Compose, and `curl` are installed.
- Runtime `APP_ENV` matches the workflow target, currently `staging`.
- Runtime `PORT` is the container port and optional `APP_PORT` is the host port.

## Normal Deploy Runbook

| Step | Expected result |
| --- | --- |
| 1. Validate config | Required env is present and source credentials are not empty |
| 2. Run tests | Unit, source contract, docs check, and changed integration tests pass |
| 3. Build artifact | App, scheduler, and worker artifact is reproducible |
| 4. Pause overlapping runs | No active production run is interrupted silently |
| 5. Apply DB migration if any | Local scraper DB schema is compatible |
| 6. Start app and workers | Liveness and worker heartbeat are healthy |
| 7. Run smoke checks | Fixture-backed pipeline and source health pass |
| 8. Resume scheduler | Next scheduled run is enabled |
| 9. Watch first run | Counts, failures, and sync latency are reviewed |

## Rollback Runbook

| Change type | Rollback direction |
| --- | --- |
| Code only | Redeploy previous artifact and rerun smoke checks |
| Config issue | Restore previous environment values and restart |
| Source adapter change | Disable affected source or redeploy previous adapter |
| Additive DB migration | Redeploy previous compatible artifact; clean up later |
| Destructive DB migration | Restore backup or execute documented forward fix |
| Mapper regression | Stop affected source sync, keep raw rows, deploy mapper fix, replay |

Rollback must not delete raw captures or staging rows needed for replay.

## Hotfix Runbook

Use hotfix only when production freshness or sync is materially degraded.

1. Identify affected source, stage, and `runId`.
2. Reproduce with sanitized fixture or limited source run.
3. Patch smallest affected adapter, mapper, sync, or config surface.
4. Run focused unit/contract test plus redaction check.
5. Deploy hotfix artifact.
6. Replay affected stage from raw/staging data when safe.
7. Record incident note and update docs if behavior changed.

## Post-Deploy Checks

| Check | Expected result |
| --- | --- |
| App liveness | `/health/live` responds without requiring database connectivity |
| App readiness | `/health/ready` confirms the scraper database accepts a lightweight query |
| Scheduler state | Next run time is visible |
| Source health | Each source reports safe status without exposing credentials |
| Fixture pipeline | One sanitized fixture batch normalizes successfully |
| DB connectivity | Local scraper DB and sync target are reachable |
| Log redaction | No token/cookie/session strings appear |
| First production run | Counts are plausible and failures are isolated |
| Freshness | `lastSeenAt` and stale counts match policy |

## Recovery Rules

- Prefer replay from raw/staging data over re-scraping when source rate limits are a risk.
- Do not expire unseen jobs for a source after failed or partial source runs.
- Keep failed records quarantined with safe reason codes.
- Re-run enrichment separately when scrape and normalization are healthy.
- Re-run sync from staging when main DB handoff failed.
- Rotate exposed source credentials if logs or artifacts leaked real values.

## Scheduler Runtime

The scraper registers separate daily jobs for scrape, normalize, enrich, and sync. Each job uses the configured cron value, a stable scheduler id, coalescing for missed executions, and a single concurrent instance. Manual triggers share the same guard so operators cannot start a second stage while another stage is still active.

## Related Docs

- [Deployment Overview](./deployment-overview.md)
- [Testing Strategy](./testing.md)
- [Observability](./observability.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Environment Configuration](../environment.md)
