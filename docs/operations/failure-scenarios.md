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
| Isolation | Re-run one sanitized normalized job through enrichment worker |
| Owner | Data ingestion owner; model owner if model dependency fails |

Scrape and sync should not be marked failed only because enrichment is degraded unless required fields depend on enrichment.

## Scenario 6: Sync To Main DB Fails

| Area | Detail |
| --- | --- |
| Indicators | Sync latency increases; upsert errors; staging counts do not reach main DB |
| Impact | Backend keeps serving older job data |
| First checks | Main DB connectivity, unique constraints, batch size, transaction errors |
| Isolation | Run one small sync batch from staging rows with known source identities |
| Owner | Data ingestion owner with backend owner review |

## Scenario 7: Jobs Become Stale After Partial Run

| Area | Detail |
| --- | --- |
| Indicators | Stale job count rises after partial source failure |
| Impact | Valid jobs may be incorrectly expired if freshness policy is unsafe |
| First checks | Source run status, `lastSeenAt`, partial-run guard, expiration threshold |
| Isolation | Verify failed source did not execute expiration logic for missing records |
| Owner | Data ingestion owner |

Never expire all jobs from a source after a failed or partial source run.

## Scenario 8: Raw Artifact Safety Failure

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

