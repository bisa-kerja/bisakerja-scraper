---
title: Scraper Failure Scenarios
description: Common scraper ingestion, normalization, enrichment, sync, and freshness failures with indicators, impact, and first checks.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Failure Scenarios

Use this page when job data is missing, stale, malformed, or blocked before Backend API consumption.

## Triage Flow

1. Find the affected `runId`.
2. Identify the first failing stage.
3. Check per-source status before checking downstream stages.
4. Compare fetched, normalized, enriched, and synced counts.
5. Confirm no raw credentials or raw payload bodies are needed for diagnosis.

## Scenario 1: Daily Run Did Not Start

| Area | Detail |
| --- | --- |
| Indicators | No run record near `01:00`; no source logs; freshness age increases |
| Impact | All sources stale; backend may keep serving old jobs |
| First checks | Scheduler process, cron/Celery Beat config, runtime env, recent deploy |
| Isolation | Start a dry-run or one-source run in staging/local with same config |
| Owner | Data ingestion owner |

## Scenario 2: Source Fetch Fails

| Area | Detail |
| --- | --- |
| Indicators | Fetch success rate drops; status class `401`, `403`, `429`, `5xx`, or timeout |
| Impact | One source partial or missing; later stages may still run for other sources |
| First checks | Source-specific auth/header config, rate limits, timeout, network path |
| Isolation | Retry affected source only with redacted headers and bounded page limit |
| Owner | Data ingestion owner |

Source-specific notes:

| Source | First source check |
| --- | --- |
| Dealls | REST list endpoint status and pagination |
| Glints | GraphQL operation shape and list response root |
| JobStreet | Bearer/session validity and GraphQL response errors |
| Kalibrr | Current Next.js `buildId` and `_next/data` path |

Rate-limit and backoff notes:

- `429`, timeout, `408`, and transient `5xx` responses may retry with capped exponential backoff.
- Per-source limiter state is isolated; a blocked source should not delay healthy sources.
- A run-local circuit breaker may stop additional requests for a repeatedly failing source.
- Circuit breaker activity should mark the source degraded or partial, not completed.
- Operators should compare current failure count, retry count, and last successful source run before replay.

## Scenario 3: Payload Schema Drift

| Area | Detail |
| --- | --- |
| Indicators | Parse failure rate rises; mapper cannot find identity or payload root |
| Impact | Affected records quarantined; normalized count drops |
| First checks | Raw payload root, required identity fields, nullability changes |
| Isolation | Run mapper against latest sanitized fixture for the affected source |
| Owner | Data ingestion owner with backend owner review if normalized schema changes |

Do not update the normalized contract from one broken payload. Confirm whether the source changed permanently.

## Scenario 4: Dedup Ratio Spike

| Area | Detail |
| --- | --- |
| Indicators | Dedup ratio changes sharply; identity collision logs; repeated external ids |
| Impact | Jobs may be skipped, overwritten incorrectly, or counted twice |
| First checks | `sourcePlatform + externalJobId`, slug fallback, source pagination overlap |
| Isolation | Compare raw identities from current and previous successful runs |
| Owner | Data ingestion owner |

## Scenario 5: Enrichment Degraded

| Area | Detail |
| --- | --- |
| Indicators | Enrichment failure rate rises; AI batch timeout; invalid model response |
| Impact | Jobs may sync without enriched skills/requirements if policy allows |
| First checks | Batch size, queue depth, model timeout, invalid output category |
| Isolation | Re-run one sanitized normalized job through enrichment worker and inspect the matching AI request log |
| Owner | Data ingestion owner; model owner if model dependency fails |

Scrape and sync should not be marked failed only because enrichment is degraded unless required fields depend on enrichment.

AI provider error classes:

| Error | Meaning | Retry |
| --- | --- | --- |
| `OPENAI_AUTH_ERROR` | API key rejected or provider authentication failed | No |
| `OPENAI_TIMEOUT` | Provider request exceeded timeout | Yes |
| `OPENAI_RATE_LIMIT` | Provider returned rate limit response | Yes |
| `OPENAI_PROVIDER_UNAVAILABLE` | Provider connection failed or returned retryable server error | Yes |
| `OPENAI_INVALID_RESPONSE` | Refusal, malformed structured output, unsupported fact, or non-schema response | No |

Invalid enrichment output must not be written into normalized job data. Re-run only with safe normalized job text, never with raw source payloads or credentials.

AI request audit rows store provider/model metadata, safe base host alias, latency, status, retry count, request hash, and response summary. They must not store API keys, raw prompts, raw source payloads, request headers, cookies, bearer tokens, or full provider responses.

## Scenario 6: Stage Queue Job Dead-Letters

| Area | Detail |
| --- | --- |
| Indicators | `stage_jobs.status = dead-letter`, queue depth grows, downstream stage counts stop increasing |
| Impact | One stage chain may stop while other source or stage work continues |
| First checks | `job_type`, `correlation_id`, `attempt_count`, `max_attempts`, `error_category`, related run id |
| Isolation | Replay only the failed job type with the same safe payload after the underlying issue is fixed |
| Owner | Data ingestion owner |

Queue recovery rules:

- Do not mutate raw payloads or credentials to replay a job.
- Confirm the handler is idempotent before manual replay.
- Preserve the original correlation id when enqueueing replacement work.
- Dead-letter rows require operator review before replay.

## Scenario 7: Sync To Main DB Fails

| Area | Detail |
| --- | --- |
| Indicators | Sync latency increases; rejected payloads, retryable backend responses, dead-letter sync events, or staging counts not reaching main DB |
| Impact | Backend keeps serving older job data |
| First checks | Backend service availability, service credential validity, response summary, payload hash, attempt count, batch size, unique constraints |
| Isolation | Run one small sync batch from staging rows with known source identities and compare the sync event status before and after the attempt |
| Owner | Data ingestion owner with backend owner review |

Sync triage rules:

- `4xx` responses usually indicate payload or credential problems and should not be retried blindly.
- `429` and `5xx` responses may be retried within the configured limit.
- Sync runs are chunked; a failed chunk should not mark later chunks failed.
- Repeating the same payload should reuse the same sync event.
- Resume should process only pending events and retryable failed events.
- `dead-letter` rows require operator review before replay.
- Response summaries must not contain service tokens, cookies, raw headers, or raw source payloads.

## Scenario 8: Notification Handoff Fails

| Area | Detail |
| --- | --- |
| Indicators | Handoff events stay `failed` or `dead-letter`; recommendation candidate count is lower than sent sync count |
| Impact | Backend-owned recommendation email flow has fewer or no new candidates |
| First checks | Sent sync event count, backend notification endpoint health, response summary, handoff attempt count |
| Isolation | Retry a small set of failed handoff events after Backend API confirms the notification endpoint is healthy |
| Owner | Data ingestion owner with backend owner review |

Handoff triage rules:

- Handoff only starts from `sent` sync events.
- Scraper must not read backend user preference tables to compensate for a backend failure.
- Repeating the same run/source/job target should reuse the same handoff event.
- Dead-letter handoff rows require operator review before replay.

## Scenario 9: Jobs Become Stale After Partial Run

| Area | Detail |
| --- | --- |
| Indicators | Stale job count rises after partial source failure |
| Impact | Valid jobs may be incorrectly expired if freshness policy is unsafe |
| First checks | Source run status, `lastSeenAt`, partial-run guard, expiration threshold |
| Isolation | Verify failed source did not execute expiration logic for missing records |
| Owner | Data ingestion owner |

Never expire all jobs from a source after a failed or partial source run.

## Scenario 10: Raw Artifact Safety Failure

| Area | Detail |
| --- | --- |
| Indicators | Header, cookie, token, session id, or tracking id appears in logs/docs/fixtures |
| Impact | Credential exposure risk; docs or fixture release must stop |
| First checks | Redaction policy, artifact generation, log serializer, fixture source |
| Isolation | Remove unsafe artifact, rotate exposed credential if real, regenerate sanitized fixture |
| Owner | Data ingestion owner with engineering lead review |

## Related Docs

- [Observability](./observability.md)
- [Payload Redaction Policy](../standards/payload-redaction-policy.md)
- [Raw Payload Contract](../references/raw-payload-contract.md)
- [Freshness Module](../modules/freshness.md)
- [Daily Pipeline Runbook](./daily-pipeline-runbook.md)
