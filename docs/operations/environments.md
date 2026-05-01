---
title: Scraper Environments
description: Local, test, staging, and production environment expectations for scraper runtime, data, source credentials, and validation.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Environments

Scraper environments differ by data safety, source credential policy, schedule behavior, and sync target.

## Matrix

| Environment | Purpose | Data rule | Source access | Sync rule |
| --- | --- | --- | --- | --- |
| Local | Developer iteration | Disposable local data | Prefer fixtures; real source only with redacted secrets | Disabled or local-only |
| Test | Automated validation | Isolated fixture data | Fixture/mocked only | Disabled or test DB |
| Staging | Release validation | Non-production production-like data | Controlled real-source config | Staging main DB only |
| Production | Daily ingestion | Production scraper/main DB | Managed secrets and rate limits | Production main DB |

## Local

Rules:

- Use local scraper DB.
- Prefer raw response fixtures for mapper tests.
- Keep sync disabled unless target is disposable.
- Use safe placeholder service tokens.
- Never commit local source cookies or bearer tokens.

## Test

Rules:

- Use deterministic fixtures from sanitized raw captures.
- Do not call external sources.
- Use isolated test database.
- Fail fast when required env values are missing.
- Keep logs quiet unless diagnosing failures.

## Staging

Rules:

- Validate full pipeline before production.
- Use staging DB and staging Backend API-consumable tables.
- Use managed non-production secrets.
- Run with production-like schedule only when source rate limits allow.
- Confirm generated docs and contracts before release.

## Production

Rules:

- Use managed secrets.
- Keep production CORS/internal network rules strict when HTTP endpoints exist.
- Apply source-specific rate limits.
- Monitor run success, parse failures, dedup ratio, stale jobs, and sync latency.
- Do not expire jobs from a source after failed or partial source runs.

## Promotion Checks

Before moving config forward:

- Required env vars exist and are non-empty.
- Source credentials are stored outside docs and repo files.
- DB targets match environment.
- Schedule windows are explicit.
- Log redaction is enabled.
- Health checks pass.

## Related Docs

- [Environment Configuration](../environment.md)
- [Freshness Module](../modules/freshness.md)
- [Security](./security.md)

