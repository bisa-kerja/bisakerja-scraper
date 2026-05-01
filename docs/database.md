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

Cross-source duplicate merge is future scope.

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

