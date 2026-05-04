---
title: Backend Sync Schema Map
description: Canonical mapping from source payloads into backend sync payloads aligned with Prisma job ingestion models and relation constraints.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Backend Sync Schema Map

This reference locks the scraper sync payload contract before data is sent to Backend API.

## Source To Backend Model Map

| Source field family | Canonical field | Backend sync payload | Prisma target model |
| --- | --- | --- | --- |
| Source identity | `source.platform` | `sourcePlatform.slug`, `sourcePlatform.name` | `SourcePlatform.slug`, `SourcePlatform.name` |
| Source identity | `source.external_job_id` | `jobListing.externalJobId` | `JobListing.externalJobId` |
| Source URLs | `source.source_url`, `source.external_apply_url` | `jobListing.sourceUrl`, `jobListing.externalApplyUrl` | `JobListing.sourceUrl`, `JobListing.externalApplyUrl` |
| Company | `company.name`, `company.*` | `company.name`, `company.sourceCompanyId`, `company.sourceSlug`, `company.logoUrl`, `company.websiteUrl`, `company.industry` | `Company` |
| Job core | `title`, `description`, `requirements`, `category` | `jobListing.title`, `jobListing.description`, `jobListing.requirementSummary`, `jobListing.category` | `JobListing` |
| Work and contract | `work_type`, `employment_types`, `experience_level` | `jobListing.workType`, `jobListing.employmentType`, `jobListing.experienceLevel` | `JobListing` enums |
| Location | `location.display`, `location.region`, `location.city` | `jobListing.locationDisplay`, `jobListing.province`, `jobListing.city` | `JobListing` |
| Salary | `salary.*` | `jobListing.salaryMin`, `jobListing.salaryMax`, `jobListing.salaryCurrency`, `jobListing.salaryPeriod`, `jobListing.salaryDisplay` | `JobListing` + `SalaryPeriod` |
| Freshness | `posted_at`, `source.source_updated_at`, `last_seen_at`, scrape run id | `jobListing.sourcePostedAt`, `jobListing.sourceUpdatedAt`, `jobListing.lastSeenAt`, `ingestionRun.sourceRunId` | `JobListing`, `IngestionRun` |
| Status | `status` | `jobListing.status` | `JobListingStatus` |
| Requirements staging | structured rows | `requirements[]` | `JobRequirement` |
| Skills staging | structured rows | `skills[]` | `Skill`, `JobSkill` |

## Enum Mapping Rules

| Canonical/source intent | Backend sync enum |
| --- | --- |
| `remote`, `hybrid`, `onsite` | `REMOTE`, `HYBRID`, `ONSITE` |
| `full_time`, `part_time`, `internship`, `contract`, `freelance` | `FULL_TIME`, `PART_TIME`, `INTERNSHIP`, `CONTRACT`, `FREELANCE` |
| `entry_level`, `junior`, `mid_level`, `senior`, `lead` | `ENTRY_LEVEL`, `JUNIOR`, `MID_LEVEL`, `SENIOR`, `LEAD` |
| Salary label contains monthly markers (`month`, `monthly`, `bulan`) | `MONTHLY` |
| Salary label contains yearly markers (`year`, `yearly`, `tahun`) | `YEARLY` |
| `active`, `stale`, `expired`, `inactive`, `unknown` | `ACTIVE`, `STALE`, `EXPIRED`, `CLOSED`, `ACTIVE` |
| Requirement type | `SKILL`, `EXPERIENCE`, `EDUCATION`, `RESPONSIBILITY`, `OTHER` |

## Required Defaults Before Sync

- `jobListing.salaryCurrency` defaults to `IDR` when salary currency is missing.
- `jobListing.salaryPeriod` is inferred from salary display text when explicit period is absent.
- `jobListing.status` defaults to `ACTIVE` for unknown canonical status.
- `jobListing.lastSeenAt` is always filled from normalized row freshness timestamp.
- `jobListing.sourcePostedAt` and `jobListing.sourceUpdatedAt` remain `null` when source timestamps are unavailable.
- `jobListing.externalApplyUrl` falls back to `sourceUrl` when source apply URL is unavailable.

## Validation Gates

Payload is rejected before sync when any of the following occurs:

- Missing required source relation values:
  - empty `sourcePlatform.slug`
  - empty `company.name`
- Missing required listing identity:
  - empty `jobListing.externalJobId`
  - empty `jobListing.sourceUrl`
  - empty `jobListing.externalApplyUrl`
- Enum mismatch:
  - unsupported requirement type
  - invalid enum in strict payload models
- Type mismatch:
  - non-numeric salary fields in numeric slots
  - invalid timestamp format
- Invalid salary range:
  - `salaryMin > salaryMax`
- Orphan staging relation:
  - `JobSkill.normalized_job_id != normalized_job.id`
  - `JobRequirement.normalized_job_id != normalized_job.id`

Validation failures are classified as non-retryable contract failures for the sync worker.

## Idempotency Keys

- Local normalized uniqueness: `normalized_jobs(source_platform, external_id)`.
- Sync event idempotency: `sync_events(target, normalized_job_id, payload_hash)`.
- Downstream unique job identity in Prisma: `job_listings(sourcePlatformId, externalJobId)`.

## Related Files

- `src/integrations/backend/payloads.py`
- `src/modules/sync/worker.py`
- `tests/contract/test_backend_payloads.py`
- `tests/contract/test_backend_schema_lock.py`
- `backend-references/prisma/schema.prisma`
