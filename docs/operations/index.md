---
title: Operations
description: Operational entry point for scraper pipeline execution, validation, failure triage, and release readiness.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: active
last_reviewed: 2026-05-02
---

# Operations

Operational docs for this repository should cover scraper runtime behavior only.

## Pages

- [Environments](./environments.md)
- [Security](./security.md)
- [Observability](./observability.md)
- [Failure Scenarios](./failure-scenarios.md)
- [Daily Pipeline Runbook](./daily-pipeline-runbook.md)
- [Stage Queue Operations](./queue.md)
- [Testing Strategy](./testing.md)
- [CI Quality Gates](./ci-quality-gates.md)
- [Verification Matrix](./verification-matrix.md)
- [Deployment Overview](./deployment-overview.md)
- [Deployment Operations](./deployment.md)
- [Documentation Sync](./documentation-sync.md)
- [Documentation Release Checklist](./documentation-release-checklist.md)
- [Release Readiness](./release-readiness.md)
- [Production Readiness Gate](./production-readiness-gate.md)

## Baseline Run Order

| Time | Stage | Expected output |
| --- | --- | --- |
| 00:00 | Scrape | Raw payload batches stored per source |
| 02:00 | Normalize | Valid normalized job staging rows |
| 04:00 | Enrich | Skill and requirement enrichment batches |
| 06:00 | Sync | Upsert-ready records in main database shape |
| 08:00 | Notify handoff | Backend notification inputs available |

## Failure Classes

- Source throttling or API drift.
- Missing required fields.
- Invalid HTML or unsafe payload text.
- Dynamic Kalibrr `buildId` drift.
- JobStreet bearer/session expiry.
- Duplicate or unstable external identity.
- Enrichment timeout or invalid AI output.
- Sync latency or main DB write failure.
- Documentation sync metadata, link, or secret-scan failure.
- CI or release readiness failure.
