---
title: Scraper Deployment Overview
description: Operational overview of scraper runtime environments, deploy modes, validation gates, and recovery ownership.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Deployment Overview

Scraper deployment should protect the daily job pipeline first: source fetch, normalization, enrichment, sync, and freshness handoff.

## Environment Roles

| Environment | Purpose | Deploy rule |
| --- | --- | --- |
| Local | Developer iteration | Fixture-first; real source only with redacted local secrets |
| Test | Automated verification | No live source calls; isolated DB and sanitized fixtures |
| Staging | Production-like validation | Managed non-production secrets and staging sync target |
| Production | Daily ingestion | Managed secrets, monitored schedule, controlled source limits |

## Deploy Modes

| Mode | Trigger | Expected outcome |
| --- | --- | --- |
| Normal deploy | Planned release | New artifact runs next schedule safely |
| Hotfix deploy | Active incident or high freshness risk | Minimal fix restores affected source/stage |
| Rollback | Bad artifact or config | Previous known-good behavior restored |
| Replay | Failed stage after fix | Raw/staging data reprocessed without unnecessary source calls |

## High-Level Flow

```text
change
  -> validate docs, contracts, tests
    -> build artifact
      -> deploy app/scheduler/worker
        -> smoke check
          -> watch first run
            -> record result
```

## Gate Order

| Gate | Blocks deploy when |
| --- | --- |
| Config | Required env missing or points to wrong DB |
| Tests | Source contract, mapper, sync, or docs checks fail |
| Security | Redaction scan finds source credential material |
| Runtime | App, scheduler, or worker cannot start |
| Smoke | Fixture pipeline or DB connectivity fails |
| Observability | Logs lack `runId` or stage evidence |

## Operational Ownership

| Area | Primary owner |
| --- | --- |
| Scraper app and source adapters | Data ingestion owner |
| Backend DB sync contract | Data ingestion owner and backend owner |
| Deployment platform | Platform engineering or assigned operator |
| Docs sync and quality | Platform docs maintainer |
| Credential incident | Engineering lead with data ingestion owner |

## Recovery Decision Frame

| Symptom | Prefer |
| --- | --- |
| Source API temporarily fails | Retry later or mark source partial |
| Mapper bug | Fix mapper and replay raw rows |
| Enrichment fails | Re-run enrichment worker; do not re-scrape |
| Sync fails | Re-run sync from staging |
| Bad deploy | Roll back artifact, then replay missed stages |
| Credential leak | Stop unsafe publishing, rotate credential, regenerate artifacts |

## Related Docs

- [Deployment Operations](./deployment.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Verification Matrix](./verification-matrix.md)
- [Documentation Sync](./documentation-sync.md)

