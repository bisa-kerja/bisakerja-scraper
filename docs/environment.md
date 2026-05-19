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
| `PORT` | If HTTP exposed | `3003` | Internal API port |
| `APP_PORT` | If Compose exposes HTTP | `3003` | Host port used by Docker Compose and deploy health checks |
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
- `postgres://` aliases are accepted and normalized at runtime.
- Alembic online migration uses a sync PostgreSQL driver path and normalizes async PostgreSQL URLs to a sync `psycopg` dialect for migration execution.
- Deployment preflight validates the configured scraper database with a lightweight query before migrations and prints only password-redacted URLs.
- For Neon-hosted PostgreSQL (`*.neon.tech`), runtime applies Neon-safe normalization:
  - async runtime path uses `postgresql+asyncpg`.
  - sync migration/preflight path uses `postgresql+psycopg`.
  - `sslmode=require` is enforced when not explicitly present.
  - `channel_binding=require` is removed only on async runtime URLs (asyncpg does not use libpq channel binding parameters).

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
| `SCRAPER_MAX_ITEMS_PER_KEYWORD` | Yes | Positive integer, maximum `1000` |
| `SCRAPER_MAX_ITEMS_PER_SOURCE_RUN` | Yes | Positive integer cap per source per run |
| `SCRAPER_MAX_PAGES_PER_KEYWORD` | Yes | Positive integer page cap per keyword |
| `SCRAPER_TARGET_TOTAL_JOBS_PER_RUN` | Yes | Positive integer target cap for one pipeline run |
| `SCRAPER_DETAIL_FETCH_CONCURRENCY` | Yes | Positive integer bounded detail-fetch concurrency |
| `SCRAPER_RECENCY_MODE` | Yes | `latest` or `native`; default examples use `latest` |
| `SCRAPER_RECENCY_DAYS` | Yes | Positive integer, maximum `365` |

Keyword rules:

- Split values on commas.
- Trim leading and trailing whitespace.
- Reject empty entries such as `developer,,intern`.
- Keep internal spaces and search operators such as `/`, `+`, and `-`.
- Deduplicate case-insensitively while preserving the first spelling sent to sources.

The scraper fans out scrape work by `source x keyword`. The per-keyword limit applies to every fan-out item, not to the whole run. Total rows can exceed `100` when multiple sources and keywords run together. Job deduplication still uses `sourcePlatform + externalJobId`; the search keyword is audit metadata and must not become part of job identity.

Latest mode requests newest listings first when a source supports it and locally sorts fetched rows by source timestamp before persistence. Native mode omits the scraper-added latest sort/filter parameters and preserves the platform response order; source keyword and pagination parameters still apply.

## Backend Sync Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `BACKEND_SYNC_BASE_URL` | Yes when sync is enabled | Backend API base URL; scraper appends `/api/v1/internal/scraper/jobs` and `/api/v1/internal/notification-events` |
| `BACKEND_SYNC_SERVICE_TOKEN` | Yes when sync is enabled | Internal service credential from secret storage; must match Backend API `SCRAPER_API_SERVICE_TOKEN` |
| `BACKEND_SYNC_TIMEOUT_SECONDS` | Yes | Positive sync request timeout |
| `BACKEND_SYNC_BATCH_SIZE` | Yes | Positive batch size, maximum `25` for safer backend transaction runtime |
| `FRESHNESS_STALE_AFTER_HOURS` | Yes | Positive threshold for stale listings |
| `FRESHNESS_EXPIRED_AFTER_HOURS` | Yes | Positive threshold greater than stale threshold |

Backend sync can process large candidate sets such as `1000`-`2000` normalized jobs in one stage run. The scraper splits outbound sync calls into repeated `BACKEND_SYNC_BATCH_SIZE` chunks, so no single request exceeds `25` jobs. Notification handoff is also chunked before calling the Backend API candidate endpoint.

## AI Provider Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `AI_ENRICHMENT_ENABLED` | Yes | Explicit `true` or `false`; enables OpenAI provider usage for enrichment and AI-assisted normalization in execute mode |
| `OPENAI_API_KEY` | Yes when AI enrichment is enabled | Secret store only |
| `OPENAI_BASE_URL` | Yes when AI enrichment is enabled | Absolute OpenAI-compatible API base URL |
| `OPENAI_MODEL` | Yes when AI enrichment is enabled | Single model or comma-separated model list (for example `gpt-4o-mini,gpt-4.1-mini`) |
| `OPENAI_TIMEOUT_SECONDS` | Yes | Positive provider request timeout |
| `OPENAI_MAX_RETRIES` | Yes | Bounded retry count |
| `OPENAI_BATCH_SIZE` | Yes | Positive batch size; baseline is `10` jobs |
| `OPENAI_NORMALIZATION_BATCH_SIZE` | Yes | Positive batch size for AI normalization requests; baseline is `5` jobs |
| `OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS` | Yes | Fixed delay in milliseconds between normalization batch requests; baseline is `1000` |
| `AI_OUTPUT_LANGUAGE` | Yes | Output language for AI-generated job text; allowed values are `indonesian` and `english` |

AI enrichment uses an OpenAI-compatible client boundary. The base URL supports the official OpenAI API and compatible providers that expose the same request shape. Logs must not include API keys. If the base URL contains tenant, account, or deployment-specific identifiers, treat it as sensitive operational metadata and redact it from logs.

Model selection rules:

- `OPENAI_MODEL` accepts one model or a comma-separated list.
- Entries are trimmed per item and empty items are rejected.
- Runtime uses deterministic round-robin across the configured order, for example `a,b,c -> a,b,c,a`.
- Retry attempts may move to the next model in the same configured order.
- This rotation spreads request load across configured models, but does not remove organization, project, key, or shared-model-family rate limits.

Normalize stage in execute mode can also use the same OpenAI-compatible provider for AI-assisted normalization. The prompt contract is standalone and embedded in code, so runtime does not depend on external reference repositories.

Normalization requests are executed serially in fixed-size batches. The service always applies `OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS` between batches, regardless of rate-limit response state.

`AI_OUTPUT_LANGUAGE` controls generated or paraphrased human-readable AI output in normalization and enrichment prompts, including `description`, `requirements`, requirement summary guidance, warnings, and generated presentation labels. Technology names, product names, company names, locations, and direct source quotes stay source-faithful. The default example value is `english`; use `indonesian` when downstream job descriptions and requirements must be generated in Bahasa Indonesia.

Only safe normalized job fields may be sent to the enrichment provider: title, clean description, clean requirements, company name, and source platform. AI normalization may send sanitized raw evidence needed for mapping, but must not include source request headers, bearer tokens, cookies, session ids, visitor ids, device ids, backend service credentials, API keys, or database URLs.

Baseline schedule:

| Stage | Baseline |
| --- | --- |
| Scrape | `00:00` |
| Normalize | `02:00` |
| Enrich | `04:00` |
| Sync | `06:00` |
| Notify handoff | `08:00` |

## Source Variables

| Variable | Required | Rule |
| --- | --- | --- |
| `DEALLS_ENABLED` | Yes | Explicit `true` or `false`; live execute source enablement flag |
| `DEALLS_BASE_URL` | Yes | Public/semi-public REST base URL |
| `DEALLS_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `DEALLS_PAGE_SIZE` | Yes | Positive page size for Dealls list pagination (`<= 20`) |
| `GLINTS_ENABLED` | Yes | Explicit `true` or `false`; live execute source enablement flag |
| `GLINTS_GRAPHQL_URL` | Yes | GraphQL endpoint |
| `GLINTS_COUNTRY_CODE` | Yes | Example: `ID` |
| `GLINTS_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `GLINTS_PAGE_SIZE` | Yes | Positive page size for Glints pagination (`<= 30`) |
| `JOBSTREET_ENABLED` | Yes | Explicit `true` or `false`; current live JobStreet enablement flag |
| `JOBSTREET_GRAPHQL_URL` | Yes | GraphQL endpoint |
| `JOBSTREET_BEARER_TOKEN` | Yes when JobStreet enabled | Secret store only |
| `JOBSTREET_COOKIE` | Optional (operationally required when Cloudflare challenge is active) | Cookie header from an operator-managed browser session |
| `JOBSTREET_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `JOBSTREET_PAGE_SIZE` | Yes | Positive page size for JobStreet pagination |
| `KALIBRR_ENABLED` | Yes | Explicit `true` or `false`; live execute source enablement flag |
| `KALIBRR_BASE_URL` | Yes | Public web base URL |
| `KALIBRR_BUILD_ID_REFRESH_ENABLED` | Yes | Explicit `true` or `false` |
| `KALIBRR_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `KALIBRR_PAGE_SIZE` | Yes | Positive page size for Kalibrr pagination planning |
| `KITALULUS_ENABLED` | Yes | Explicit `true` or `false`; live execute source enablement flag |
| `KITALULUS_GRAPHQL_URL` | Yes | GraphQL endpoint |
| `KITALULUS_RATE_LIMIT_PER_MINUTE` | Yes | Bounded source request rate |
| `KITALULUS_PAGE_SIZE` | Yes | Positive page size for Kitalulus pagination |

Source enablement applies to live execute mode. Dry-run fixture validation can still run for supported sources even when the live source flag is disabled. `--source all --execute` runs enabled sources and reports disabled sources in `skippedSources`; `--source <source> --execute` fails with a friendly operator error when that source is disabled.

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
