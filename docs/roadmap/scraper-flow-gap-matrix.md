---
title: Scraper Flow Gap Matrix
description: Implementation status, ownership, stage contracts, dependencies, and remaining gaps for the scraper flow.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-02
---

# Scraper Flow Gap Matrix

This matrix compares the target scraper flow with the current service implementation. It is an implementation readiness reference for ingestion, normalization, AI enrichment, backend sync, freshness, and notification handoff work.

## Capability Matrix

| Step | Target capability | Current implementation | Status | Owner | Evidence | Remaining gap |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Scheduled daily trigger | APScheduler shell and cron configuration are present | implemented | Data ingestion owner | `src/jobs/scheduler.py`, `docs/environment.md` | Production worker deployment and lock observability remain operational concerns |
| 2 | Run scraper per platform | Source adapters exist for Dealls, Glints, JobStreet, and Kalibrr | implemented | Data ingestion owner | `src/integrations/sources/**` | Keep source contract fixtures fresh |
| 3 | Store raw source data | Raw records persist in local scraper DB with source identity and payload hash | implemented | Data ingestion owner | `src/modules/persistence/models.py`, `src/modules/persistence/repositories.py` | Raw payload retention and purge policy need operational enforcement |
| 4 | Transform to backend-compatible schema | Source mappers produce canonical job records | implemented | Data ingestion owner | `src/integrations/sources/*/mapper.py`, `src/modules/jobs/schemas.py` | Backend final schema resolver still needs end-to-end contract testing |
| 5 | Deduplicate by source identity | Raw and normalized records use source platform plus external id uniqueness | implemented | Data ingestion owner | `src/modules/deduplication/engine.py`, `src/modules/persistence/models.py` | Cross-source merge remains out of scope |
| 6 | Batch AI processing | Batch size configuration is defined for AI enrichment | partial | Data ingestion owner | `src/config/settings.py` | Worker queue, persisted AI audit, and retry staging are separate follow-up work |
| 7 | Extract skills and structure requirements | Pydantic output contract, prompt contract, and OpenAI client boundary exist | partial | Data ingestion owner | `src/modules/enrichment/**`, `src/integrations/ai/**` | Full pipeline wiring and durable enrichment tables remain follow-up work |
| 8 | Insert enriched results to local structured tables | Normalized payload can carry skills and requirements | partial | Data ingestion owner | `src/modules/jobs/schemas.py`, `src/modules/persistence/models.py` | Dedicated staging tables and AI request logs are not implemented yet |
| 9 | Upsert to main Backend DB | Backend sync client and sync event audit exist | partial | Data ingestion owner with backend owner | `src/integrations/backend/client.py`, `src/modules/sync_events/**` | Final backend schema resolver and live contract tests remain follow-up work |
| 10 | Maintain status and freshness | Normalized records track `last_seen_at` and status | partial | Data ingestion owner | `src/modules/freshness/**`, `src/modules/persistence/models.py` | Freshness sweep and partial-run expiration guard need full implementation |
| 11 | Filter users for notification | Scraper does not own user preferences | missing | Backend owner | `backend-references/docs/database.md` | Notification eligibility belongs to Backend API |
| 12 | Match jobs to user preferences | Scraper only prepares job records | missing | Backend owner | `docs/architecture.md` | Recommendation scoring belongs to Backend API or notification worker |
| 13 | Send recommendation email | Scraper only hands off normalized job data | missing | Backend owner | `docs/architecture.md` | Email delivery stays outside scraper core |

## Stage Contracts

| Stage | Input | Output | Dependencies | Failure mode | Recovery rule |
| --- | --- | --- | --- | --- | --- |
| `scrape` | Source config, safe headers, query windows | Redacted raw payloads with source identity | External source availability, source auth/header config | Timeout, `401`, `403`, `429`, schema root missing | Retry with bounded backoff; isolate failed source |
| `normalize` | Raw payload records | Canonical job records with required identity, title, company, source URL, `lastSeenAt` | Source mapper, canonical schema validation | Missing identity, malformed fields, unsafe HTML | Quarantine or skip invalid rows; keep raw capture for replay |
| `enrich` | Safe title, description, requirements text, company, source | Skills, typed requirements, confidence, warnings | AI configuration, OpenAI-compatible provider, prompt/schema contract | Auth error, timeout, rate limit, provider unavailable, invalid structured response | Retry retryable provider failures; allow base job sync when policy permits |
| `sync` | Valid normalized rows and optional enrichment | Backend sync request batches and sync events | Backend sync URL, service token, batch size, backend schema | Rejected payload, backend unavailable, partial batch failure | Do not retry unsafe `4xx`; retry `429`/`5xx`; preserve idempotency by payload hash |
| `notify-handoff` | Synced normalized jobs and freshness metadata | Backend-owned recommendation/email work | Backend user preferences, notification worker | User preference mismatch, delivery failure | Keep notification outside scraper transaction boundary |

## Dependency Order

```text
scrape
  -> normalize
  -> enrich
  -> sync
  -> notify-handoff
```

Rules:

- `normalize` depends on persisted raw identity.
- `enrich` must use sanitized text only and must not receive raw source payloads, source headers, cookies, or service tokens.
- `sync` can proceed without enrichment if the normalized job satisfies the visibility gate.
- `notify-handoff` depends on Backend API ownership of users, preferences, and email delivery.

## Gap Backlog

| Gap | Owner | Reason |
| --- | --- | --- |
| Durable AI request audit | Data ingestion owner | Needed for provider latency, retry, and invalid-response triage |
| Dedicated enrichment staging tables | Data ingestion owner | Needed before retry/quarantine can be replayed safely |
| Queue-backed enrichment worker | Data ingestion owner | Needed to avoid blocking scrape and sync runs on provider latency |
| Freshness sweep with partial-run guard | Data ingestion owner | Needed to avoid expiring healthy jobs after source outages |
| Backend schema resolver sync tests | Data ingestion owner with backend owner | Needed before treating backend sync as complete |
| Recommendation and email worker | Backend owner | Depends on user preferences and email ownership outside scraper |

