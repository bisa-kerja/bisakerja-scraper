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

The repository includes `.env.example` for local development and `.env.production.example` for Compose-based deployment. The deployment workflow writes the GitHub `DEPLOY_ENV_FILE` secret to `.env.production` on the target VPS.

## Groups

| Group | Purpose |
| --- | --- |
| Application | Runtime mode, service identity, HTTP port |
| Database | Local scraper DB and main DB sync target |
| Queue/scheduler | Worker broker, daily windows, concurrency |
| AI enrichment | OpenAI-compatible provider config for skills and requirement structuring |
| Source config | Per-source headers, tokens, build id refresh, rate limits |
| Security | Internal credentials, CORS if exposed, request limits |
| Observability | Logs, request id, health timeout |

## Application Variables

| Variable | Required | Example | Rule |
| --- | --- | --- | --- |
| `APP_NAME` | Yes | `bisakerja-scraper` | Service name in logs/health |
| `APP_ENV` | Yes | `local` | `local`, `test`, `staging`, `production` |
| `PORT` | If HTTP exposed | `8000` | Internal API port |
| `APP_PORT` | If Compose exposes HTTP | `8000` | Host port used by Docker Compose and deploy health checks |
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
- PostgreSQL URLs may use `postgresql://`, `postgresql+asyncpg://`, or `postgresql+psycopg://`.
- Alembic online migration uses a sync PostgreSQL driver path and normalizes async PostgreSQL URLs to a sync `psycopg` dialect for migration execution.
- Deployment preflight validates the configured scraper database with a lightweight query before migrations and prints only password-redacted URLs.

## Queue And Schedule Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `QUEUE_BROKER_URL` | Yes when workers enabled | Redis/Celery/RQ broker URL |
| `SCRAPE_SCHEDULE_CRON` | Yes | Daily scrape schedule |
| `NORMALIZE_SCHEDULE_CRON` | Yes | Daily normalize schedule |
| `ENRICH_SCHEDULE_CRON` | Yes | Daily enrichment schedule |
| `SYNC_SCHEDULE_CRON` | Yes | Daily sync schedule |
| `NOTIFY_HANDOFF_SCHEDULE_CRON` | Yes | Daily notification handoff schedule |
| `WORKER_CONCURRENCY` | Yes | Positive bounded integer |
| `SCRAPER_RUN_LOCK_TTL_SECONDS` | Yes | Prevent overlapping runs |

## HTTP And Retry Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `HTTP_TIMEOUT_SECONDS` | Yes | Positive request timeout |
| `HTTP_MAX_RETRIES` | Yes | Bounded retry count |
| `HTTP_RESPONSE_MAX_BYTES` | Yes | Maximum response body size accepted from external sources |
| `DEFAULT_RATE_LIMIT_PER_MINUTE` | Yes | Default bounded source request rate |
| `SCRAPER_KEYWORDS` | Yes | Comma-separated keyword list |
| `SCRAPER_MAX_ITEMS_PER_KEYWORD` | Yes | Positive integer, maximum `100` |
| `SCRAPER_RECENCY_MODE` | Yes | `latest` |
| `SCRAPER_RECENCY_DAYS` | Yes | Positive integer, maximum `365` |

Keyword rules:

- Split values on commas.
- Trim leading and trailing whitespace.
- Reject empty entries such as `developer,,intern`.
- Keep internal spaces and search operators such as `/`, `+`, and `-`.
- Deduplicate case-insensitively while preserving the first spelling sent to sources.

The scraper fans out scrape work by `source x keyword`. The per-keyword limit applies to every fan-out item, not to the whole run. Job deduplication still uses `sourcePlatform + externalJobId`; the search keyword is audit metadata and must not become part of job identity.

Latest mode requests newest listings first when a source supports it. If a source only supports sorting, the scraper reads newest-first pages and stops locally by limit or recency threshold.

## Backend Sync Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `BACKEND_SYNC_BASE_URL` | Yes when sync is enabled | Backend API or internal sync endpoint base URL |
| `BACKEND_SYNC_SERVICE_TOKEN` | Yes when sync is enabled | Internal service credential from secret storage |
| `BACKEND_SYNC_TIMEOUT_SECONDS` | Yes | Positive sync request timeout |
| `BACKEND_SYNC_BATCH_SIZE` | Yes | Positive batch size |
| `FRESHNESS_STALE_AFTER_HOURS` | Yes | Positive threshold for stale listings |
| `FRESHNESS_EXPIRED_AFTER_HOURS` | Yes | Positive threshold greater than stale threshold |

## AI Provider Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `AI_ENRICHMENT_ENABLED` | Yes | Explicit `true` or `false`; enables OpenAI provider usage for enrichment and AI-assisted normalization in execute mode |
| `OPENAI_API_KEY` | Yes when AI enrichment is enabled | Secret store only |
| `OPENAI_BASE_URL` | Yes when AI enrichment is enabled | Absolute OpenAI-compatible API base URL |
| `OPENAI_MODEL` | Yes when AI enrichment is enabled | Model name supported by the configured provider |
| `OPENAI_TIMEOUT_SECONDS` | Yes | Positive provider request timeout |
| `OPENAI_MAX_RETRIES` | Yes | Bounded retry count |
| `OPENAI_BATCH_SIZE` | Yes | Positive batch size; baseline is `10` jobs |

AI enrichment uses an OpenAI-compatible client boundary. The base URL supports the official OpenAI API and compatible providers that expose the same request shape. Logs must not include API keys. If the base URL contains tenant, account, or deployment-specific identifiers, treat it as sensitive operational metadata and redact it from logs.

Normalize stage in execute mode can also use the same OpenAI-compatible provider for AI-assisted normalization. The prompt contract is standalone and embedded in code, so runtime does not depend on external reference repositories.

Only safe normalized job fields may be sent to the provider: title, clean description, clean requirements, company name, and source platform. Raw source payloads, source request headers, bearer tokens, cookies, session ids, visitor ids, device ids, backend service credentials, and database URLs must never be included in AI requests.

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

## Production Env File Rules

- Keep `.env.production` outside git.
- Use `.env.production.example` only as a shape reference.
- Set `APP_ENV` to the deployment target expected by the workflow.
- Set `PORT` to the container port and `APP_PORT` to the host port when they differ.
- Store the full runtime payload in the GitHub `DEPLOY_ENV_FILE` environment secret for VPS deployment.

## Related Docs

- [Operations Environments](./operations/environments.md)
- [Security](./operations/security.md)
- [Job Sources](./integrations/job-sources.md)
