---
title: Scraper Database Design
description: Scraper data ownership, local raw/staging stores, normalized job sync targets, identity constraints, retention, and quality rules.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Database Design

The scraper uses a local operational store for raw and staging data, then syncs normalized job records into Backend API-consumable tables. Backend-owned user state remains outside scraper ownership.

## Ownership Boundaries

| Data area | Primary writer | Primary reader | Rule |
| --- | --- | --- | --- |
| Raw source captures | Scraper API | Scraper operators/mappers | Internal only; redact before sharing |
| Staging jobs | Scraper API | Scraper normalizer/enrichment/sync | Retryable and replayable |
| Ingestion runs | Scraper API | Scraper operations, optional backend freshness checks | Track run state and counts |
| Source platforms | Scraper API | Backend API | Stable source catalog |
| Companies | Scraper API | Backend API | Normalized display company data |
| Job listings | Scraper API | Backend API | Normalized product job catalog |
| Job requirements/skills | Scraper API | Backend API and AI context assembly | Safe normalized text/relations |
| Users/auth/preferences/bookmarks/tracker | Backend API | Backend API | Scraper must not write |

## Local Scraper Entities

| Entity | Purpose | Key fields |
| --- | --- | --- |
| `ScrapedJobRaw` | Redacted raw payload per source record or page | `id`, `sourcePlatform`, `externalJobId`, `rawPayload`, `scrapedAt`, `ingestionRunId` |
| `StagingJob` | Canonical candidate before main DB sync | `sourcePlatform`, `externalJobId`, `title`, `companyName`, `status`, `lastSeenAt` |
| `StagingCompany` | Company candidate extracted from source | `sourcePlatform`, `externalCompanyId`, `name`, `logoUrl`, `industry` |
| `StagingRequirement` | Sanitized requirement rows | `stagingJobId`, `type`, `text`, `source` |
| `StagingSkill` | Extracted or source-provided skills | `stagingJobId`, `name`, `confidence`, `source` |
| `IngestionRun` | Run state and observability | `sourcePlatform`, `stage`, `status`, counts, timestamps, sanitized error |

## Local Operational Tables

The scraper keeps a minimal local operational schema for replay, normalization, and sync tracing.

| Table | Purpose | Important fields |
| --- | --- | --- |
| `scrape_runs` | One scrape, normalization, enrichment, or sync execution summary | `source_platform`, `stage`, `status`, counts, timestamps, sanitized error fields |
| `raw_jobs` | One captured source job payload after request metadata has been sanitized | `scrape_run_id`, `source_platform`, `external_id`, `raw_payload`, `scraped_at` |
| `normalized_jobs` | Canonical job candidate ready for sync | `source_platform`, `external_id`, `title`, `company_name`, `source_url`, `status`, `last_seen_at` |
| `ai_request_logs` | Sanitized AI provider audit trail for enrichment attempts | `provider`, `model`, `base_url_alias`, `latency_ms`, `status`, `retry_count`, `request_hash`, `response_summary` |
| `job_skills_staging` | Enriched or source-provided job skills before Backend API sync | `normalized_job_id`, `source`, `normalized_value`, `confidence`, `ai_request_log_id` |
| `job_requirements_staging` | Structured requirement rows before Backend API sync | `normalized_job_id`, `source`, `requirement_type`, `normalized_value`, `confidence`, `ai_request_log_id` |
| `stage_jobs` | Local DB-backed queue for decoupled pipeline stages | `job_type`, `status`, `payload_json`, `correlation_id`, `attempt_count`, `max_attempts`, timestamps |
| `sync_events` | Backend handoff attempt and result metadata | `scrape_run_id`, `normalized_job_id`, `source_platform`, `external_id`, `status`, `target`, `payload_hash`, `attempt_count`, `response_summary`, timestamps |
| `normalization_quarantine` | Mapper or canonical validation failures held from sync | `raw_job_id`, `source_platform`, `external_id`, `error_category`, `source_field_path`, `retryable`, timestamps |

Identity constraints:

- `raw_jobs(source_platform, external_id)` is unique.
- `normalized_jobs(source_platform, external_id)` is unique.
- `sync_events(target, normalized_job_id, payload_hash)` is unique for idempotent retry.
- `sync_events` keeps source identity indexed for retry and audit lookup.
- `job_skills_staging(normalized_job_id, normalized_value)` is unique.
- `job_requirements_staging(normalized_job_id, requirement_type, normalized_value)` is unique.
- `stage_jobs(status, available_at)` is indexed for worker claim order.
- `normalization_quarantine(status, source_platform)` is indexed for operator inspection.

Schema changes are managed with Alembic migrations. Migrations must support upgrade and downgrade in isolated test databases before release.

## Main DB Sync Targets

| Entity | Owner | Sync behavior |
| --- | --- | --- |
| `SourcePlatform` | Scraper-owned catalog, Backend reads | Seed/upsert stable slugs: `dealls`, `glints`, `jobstreet`, `kalibrr` |
| `Company` | Scraper writes, Backend reads | Upsert by source identity or normalized name fallback |
| `JobListing` | Scraper writes, Backend reads | Upsert by `sourcePlatformId + externalJobId` |
| `JobRequirement` | Scraper writes, Backend reads | Replace/upsert per job after sanitization |
| `JobSkill` | Scraper writes, Backend reads | Upsert relation to normalized `Skill` when taxonomy exists |
| `IngestionRun` | Scraper writes, Backend optionally reads | Keep freshness/debug metadata |

## Identity And Constraints

Primary dedup key:

```text
(sourcePlatformId, externalJobId)
```

Recommended constraints:

| Constraint | Purpose |
| --- | --- |
| Unique `source_platforms.slug` | Stable source catalog |
| Unique `job_listings(sourcePlatformId, externalJobId)` | Source-local dedup |
| Required `job_listings.title` | Search/detail display minimum |
| Required company fallback | Prevent ownerless visible jobs |
| Indexed `lastSeenAt` and `status` | Freshness queries |
| Indexed `postedAt` | Sorting |

## Sync Event Audit Model

Sync event rows make downstream handoff replayable and auditable without storing secrets or raw source payloads.

| Status | Meaning |
| --- | --- |
| `pending` | Payload is staged for downstream handoff |
| `sent` | Downstream accepted the payload with a `2xx` response |
| `failed` | Attempt failed but remains retryable |
| `dead-letter` | Retry limit is exhausted and operator triage is required |

Audit fields:

| Field | Rule |
| --- | --- |
| `payload_hash` | Stable hash of the normalized payload sent downstream |
| `attempt_count` | Incremented once per recorded send attempt |
| `response_summary` | Safe status code, status class, message, or stable error code |
| `error_category` | Sanitized failure class such as `backend_5xx` or `validation_error` |
| `error_message` | Short safe message without secrets, raw headers, or raw payload bodies |

Cross-source duplicate merge is future scope.

## AI Enrichment Audit Model

AI request logs are operational audit records, not prompt archives.

| Field | Rule |
| --- | --- |
| `provider` | Stable provider label such as `openai-compatible` |
| `model` | Model name used for the request |
| `base_url_alias` | Safe host only; never store full URL with path, query, or credentials |
| `latency_ms` | End-to-end request latency for the enrichment attempt |
| `status` | `success` or `failed` |
| `retry_count` | Number of worker-level retries before final result |
| `request_hash` | Stable hash of the safe normalized enrichment input |
| `response_summary` | Counts, confidence, status code, or stable error category only |
| `error_message` | Short sanitized message without prompt, raw payload, headers, or secrets |

The scraper must not store API keys, raw prompts, raw source payloads, request headers, cookies, bearer tokens, or full AI provider responses in this table.

## Enrichment Staging

Skill and requirement staging rows keep enrichment output separate from the larger normalized job payload.

| Table | Idempotency key | Valid values |
| --- | --- | --- |
| `job_skills_staging` | `normalized_job_id + normalized_value` | Non-empty normalized skill text |
| `job_requirements_staging` | `normalized_job_id + requirement_type + normalized_value` | `SKILL`, `EXPERIENCE`, `EDUCATION`, `OTHER` |

Each row stores its source and optional `ai_request_log_id` so operators can trace which enrichment attempt produced or last updated the value. Re-running enrichment updates the existing row instead of creating duplicates.

## Normalization Quarantine

Malformed raw records are quarantined when a source mapper cannot produce a valid canonical job. Quarantine rows store the source, raw job link when available, external identity when known, error category, safe message, source field path, retryability, and payload hash.

Quarantined records are not eligible for Backend API sync. A later successful normalization of the same raw job resolves open quarantine rows for that raw job, while historical rows remain available for audit.

Common quarantine categories:

| Category | Meaning |
| --- | --- |
| `NORMALIZE_ERROR` | Mapper output failed canonical validation or required fields were missing |
| `PARSE_ERROR` | Source payload shape could not be parsed |
| `VALIDATION_ERROR` | Canonical field type or enum did not satisfy the internal schema |

## Local Stage Queue

The first queue backend is the local scraper database. This keeps recovery deterministic and avoids a required Redis dependency for routine local and CI verification.

| Status | Meaning |
| --- | --- |
| `pending` | Ready when `available_at` is reached |
| `running` | Claimed by a worker |
| `completed` | Handler finished successfully |
| `failed` | Attempt failed but retries remain |
| `dead-letter` | Retry budget is exhausted and operator review is required |

Supported job types:

- `scrape-source`
- `normalize-raw`
- `enrich-batch`
- `sync-batch`
- `notify-handoff`

Every queued job carries a `correlation_id`. Stage handlers must preserve it when enqueueing downstream work.

## Retention

| Data | Retention rule |
| --- | --- |
| Raw captures | Keep long enough for mapper replay/debug; redact before docs/fixtures |
| Staging rows | Keep until synced or quarantined resolution |
| Ingestion runs | Keep summary metrics for trend/failure analysis |
| Normalized active jobs | Keep while active or recently seen |
| Stale/expired jobs | Keep when referenced by bookmarks/application records |

## Quality Rules

- Unknown salary remains `null`, never `0`.
- Missing optional logo/category/skill does not block sync.
- Missing identity/title/company/source URL blocks visibility or quarantines row.
- HTML descriptions and qualifications are sanitized before display/model use.
- UI/noise fields are not persisted into canonical tables unless explicitly adopted.
- Backend API reads normalized records only.
