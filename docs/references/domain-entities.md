---
title: Scraper Domain Entities
description: Domain entity reference for scraper raw capture, staging, normalized job catalog, enrichment, freshness, and sync ownership.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Domain Entities

This reference defines scraper-owned entities and their relationship to Backend API consumers.

## Entity Groups

| Group | Entities | Owner |
| --- | --- | --- |
| Raw capture | `ScrapedJobRaw`, raw page metadata | Scraper API |
| Staging | `StagingJob`, `StagingCompany`, `StagingRequirement`, `StagingSkill` | Scraper API |
| Normalized catalog | `SourcePlatform`, `Company`, `JobListing`, `JobRequirement`, `JobSkill` | Scraper API writes, Backend API reads |
| Operations | `IngestionRun`, retry/quarantine records | Scraper API |
| User workflows | `User`, `Bookmark`, `ApplicationRecord`, preferences, AI snapshots | Backend API |

## Core Relationships

```text
IngestionRun
  -> ScrapedJobRaw
      -> StagingJob
          -> StagingCompany
          -> StagingRequirement
          -> StagingSkill
              -> JobListing
                  -> Company
                  -> JobRequirement
                  -> JobSkill
```

Backend-owned relationships:

```text
User
  -> Bookmark -> JobListing
  -> ApplicationRecord -> JobListing
  -> AI result snapshots -> JobListing
```

The scraper does not own those user links.

## Entity Definitions

| Entity | Definition | Required fields |
| --- | --- | --- |
| `SourcePlatform` | External job source catalog | `slug`, `name`, `status` |
| `ScrapedJobRaw` | Captured source payload or item used for replay | `sourcePlatform`, `rawPayload`, `scrapedAt`, `ingestionRunId` |
| `StagingJob` | Validated candidate before main DB sync | `sourcePlatform`, `externalJobId`, `title`, `companyName`, `lastSeenAt` |
| `Company` | Normalized company display record | `name`; optional logo/industry/website |
| `JobListing` | Normalized job record consumed by Backend API | `sourcePlatformId`, `externalJobId`, `title`, `companyId`, `status`, `lastSeenAt` |
| `JobRequirement` | Sanitized job requirement row | `jobListingId`, `text`, optional `type` |
| `JobSkill` | Job-to-skill relation or source/extracted skill | `jobListingId`, `skillId` or skill text |
| `IngestionRun` | Operational run state | `sourcePlatform`, `stage`, `status`, timestamps, counts |

## Canonical Job Schema

The canonical job schema is the service-internal validation contract between source mappers, persistence, enrichment, and sync.

| Object | Required fields | Nullable fields |
| --- | --- | --- |
| Source metadata | `platform`, `externalJobId`, `sourceUrl`, `scrapedAt` | `sourceSlug`, `externalApplyUrl`, `rawPayloadHash`, `sourceUpdatedAt` |
| Company | `name` | `logoUrl`, `industry`, `sourceCompanyId`, `sourceSlug` |
| Location | none | `display`, `city`, `region`, `country`, `isRemote` |
| Salary | none | `minAmount`, `maxAmount`, `currency`, `period`, `display` |
| Job | `source`, `title`, `company`, `lastSeenAt` | `salary`, `description`, `requirements`, `postedAt` |

Canonical enums normalize source-specific labels into stable values for status, work type, employment type, source platform, and salary period. Unknown source labels should not create new enum values without contract review; preserve them in presentation metadata instead.

## Persistence Mapping

| Domain entity | Local table |
| --- | --- |
| `IngestionRun` | `scrape_runs` |
| `ScrapedJobRaw` | `raw_jobs` |
| Canonical job candidate | `normalized_jobs` |
| Sync handoff attempt | `sync_events` |

The local table names are implementation details for the scraper service. API consumers should use documented response contracts and must not depend on table shape.

## Source Identity

| Source | Entity identity rule |
| --- | --- |
| Dealls | `SourcePlatform(dealls) + id`; keep `slug` |
| Glints | `SourcePlatform(glints) + id` |
| JobStreet | `SourcePlatform(jobstreet) + id` |
| Kalibrr | `SourcePlatform(kalibrr) + id`; keep `slug` |

## Status Semantics

| Status | Meaning |
| --- | --- |
| `ACTIVE` | Seen in latest successful relevant run |
| `STALE` | Not seen recently but still useful/readable |
| `EXPIRED` | No longer available or past freshness threshold |
| `QUARANTINED` | Held from sync/visibility due to mapper or validation failure |

## Ownership Rule

Scraper-owned entities provide the job catalog. Backend-owned entities provide user-specific state. Any change that mixes those responsibilities needs an explicit design review.
