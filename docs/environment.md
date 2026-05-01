---
title: Scraper Environment Configuration
description: Environment variable groups, fail-fast validation, source-specific config, secret handling, and schedule configuration for Bisakerja Scraper.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Environment Configuration

Scraper configuration must fail fast. Required variables must be explicit in every environment file and must not silently fall back to hidden defaults.

Runtime validation lives in `src/config/settings.py` and uses `pydantic-settings`. Environment variables are read directly from the process environment and from optional `.env` files during local development.

## Groups

| Group | Purpose |
| --- | --- |
| Application | Runtime mode, service identity, HTTP port |
| Database | Local scraper DB and main DB sync target |
| Queue/scheduler | Worker broker, daily windows, concurrency |
| Source config | Per-source headers, tokens, build id refresh, rate limits |
| Security | Internal credentials, CORS if exposed, request limits |
| Observability | Logs, request id, health timeout |

## Application Variables

| Variable | Required | Example | Rule |
| --- | --- | --- | --- |
| `APP_NAME` | Yes | `bisakerja-scraper` | Service name in logs/health |
| `APP_ENV` | Yes | `local` | `local`, `test`, `staging`, `production` |
| `PORT` | If HTTP exposed | `8000` | Internal API port |
| `API_PREFIX` | If HTTP exposed | `/api/v1` | Versioned internal API prefix |

## Database Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `SCRAPER_DATABASE_URL` | Yes | Local scraper raw/staging DB |
| `BACKEND_DATABASE_URL` | Yes when sync is enabled | Main DB write target for normalized jobs |
| `BACKEND_SYNC_ENABLED` | Yes | Explicit `true` or `false` |
| `RUN_DATABASE_TESTS` | Yes in test env | Explicit `true` or `false` |

Rules:

- Use separate local/test/staging/production databases.
- Never use production DB for tests.
- Do not fallback from scraper DB to backend DB.

## Queue And Schedule Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `QUEUE_BROKER_URL` | Yes when workers enabled | Redis/Celery/RQ broker URL |
| `SCRAPE_SCHEDULE_CRON` | Yes | Daily scrape schedule |
| `NORMALIZE_SCHEDULE_CRON` | Yes | Daily normalize schedule |
| `ENRICH_SCHEDULE_CRON` | Yes | Daily enrichment schedule |
| `SYNC_SCHEDULE_CRON` | Yes | Daily sync schedule |
| `WORKER_CONCURRENCY` | Yes | Positive bounded integer |
| `SCRAPER_RUN_LOCK_TTL_SECONDS` | Yes | Prevent overlapping runs |

## HTTP And Retry Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `HTTP_TIMEOUT_SECONDS` | Yes | Positive request timeout |
| `HTTP_MAX_RETRIES` | Yes | Bounded retry count |
| `HTTP_RESPONSE_MAX_BYTES` | Yes | Maximum response body size accepted from external sources |
| `DEFAULT_RATE_LIMIT_PER_MINUTE` | Yes | Default bounded source request rate |

## Backend Sync Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `BACKEND_SYNC_BASE_URL` | Yes when sync is enabled | Backend API or internal sync endpoint base URL |
| `BACKEND_SYNC_SERVICE_TOKEN` | Yes when sync is enabled | Internal service credential from secret storage |
| `BACKEND_SYNC_TIMEOUT_SECONDS` | Yes | Positive sync request timeout |
| `BACKEND_SYNC_BATCH_SIZE` | Yes | Positive batch size |

Baseline schedule:

| Stage | Baseline |
| --- | --- |
| Scrape | `01:00` |
| Normalize | `01:30` |
| Enrich | `02:00` |
| Sync | `03:00` |
| Notify handoff | `05:00-06:00` |

## Source Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `DEALLS_BASE_URL` | Yes | Public/semi-public REST base URL |
| `DEALLS_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `GLINTS_GRAPHQL_URL` | Yes | GraphQL endpoint |
| `GLINTS_COUNTRY_CODE` | Yes | Example: `ID` |
| `GLINTS_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `JOBSTREET_GRAPHQL_URL` | Yes | GraphQL endpoint |
| `JOBSTREET_BEARER_TOKEN` | Yes when JobStreet enabled | Secret store only |
| `JOBSTREET_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `KALIBRR_BASE_URL` | Yes | Public web base URL |
| `KALIBRR_BUILD_ID_REFRESH_ENABLED` | Yes | Explicit `true` or `false` |
| `KALIBRR_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |

Header names may be documented. Real header values, bearer tokens, cookies, session ids, visitor ids, and device ids must stay in secret storage only.

## Security Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `SCRAPER_INTERNAL_SERVICE_TOKEN` | Yes if HTTP exposed | Internal callers only |
| `CORS_ORIGINS` | If browser access exists | Never wildcard in production |
| `REQUEST_BODY_LIMIT` | Yes if HTTP exposed | Explicit size |
| `RATE_LIMIT_WINDOW_MS` | Yes if HTTP exposed | Explicit window |
| `RATE_LIMIT_MAX` | Yes if HTTP exposed | Explicit max |

The Frontend UI must not receive or use scraper service credentials.

## Observability Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `LOG_LEVEL` | Yes | Structured logger level |
| `REQUEST_ID_HEADER` | Yes | Usually `x-request-id` |
| `ENABLE_REQUEST_LOGGING` | Yes | Explicit `true`/`false` |
| `HEALTH_CHECK_TIMEOUT_MS` | Yes | Bounded dependency check timeout |

Logs must redact source credentials and raw payload bodies.

## `.env.example` Rules

- Include every required variable.
- Use safe non-empty placeholders for required secrets.
- Never include real bearer tokens, cookies, source sessions, or DB credentials.
- Keep examples aligned with runtime validation.
- Keep optional secret values absent unless the related feature is enabled, or use safe non-empty placeholders.

## Related Docs

- [Operations Environments](./operations/environments.md)
- [Security](./operations/security.md)
- [Job Sources](./integrations/job-sources.md)
