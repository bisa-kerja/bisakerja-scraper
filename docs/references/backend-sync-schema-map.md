---
title: Backend Sync Schema Map
description: Canonical mapping from source payloads into backend sync payloads aligned with Prisma job ingestion models and relation constraints.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-07
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

Display field contract:

- `jobListing.description` and `jobListing.requirementSummary` must use sanitized semantic HTML.
- Allowed tags: `<p>`, `<ul>`, `<ol>`, `<li>`, `<strong>`, `<em>`, `<br>`.
- Attributes and non-allowlisted tags are not allowed.
- `requirements[]` rows remain plain text atomic values.

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

## Requirement Row Quality

Backend sync sends multiple `requirements[]` rows when source evidence contains multiple qualifications or duties. Rows are split from bullet-like or sentence-like text, deduplicated, and classified deterministically before falling back to `OTHER`.

Classification rules:

| Evidence | Requirement type |
| --- | --- |
| Tools, technologies, explicit skill tags, domain competencies | `SKILL` |
| Years of experience, seniority, fresh graduate eligibility | `EXPERIENCE` |
| Degree, diploma, major, education-level text | `EDUCATION` |
| Duties and ownership statements | `RESPONSIBILITY` |
| Useful but unclassified requirement evidence | `OTHER` |

Benefit and compensation text is filtered before sync and must not create requirement rows. Filtered examples include THR, tunjangan, benefit, fasilitas, bonus, cuti, BPJS, and gaji pokok.

Low-signal marketing text must not create requirement rows. Examples include career-opportunity taglines, company slogans, and benefit-only snippets. When no usable source evidence remains, sync emits one safe generic requirement statement so every synced job still keeps minimum requirement coverage.

Skill rows must be evidence-based. Backend sync may derive technical skills from normalized skills, requirements, or descriptions. For sparse records with clear role intent but missing skill tags, one conservative fallback skill is allowed to keep minimum coverage.

## Required Defaults Before Sync

- `jobListing.salaryCurrency` defaults to `IDR` when salary currency is missing.
- `jobListing.salaryPeriod` is inferred from salary display text and defaults to `MONTHLY` when absent.
- `jobListing.salaryDisplay` is rebuilt from numeric salary values when `salaryMin` or `salaryMax` exists, so display text stays deterministic and consistent.
- `jobListing.salaryDisplay` defaults to `Not specified` when salary evidence is missing or effectively zero-only placeholders.
- `jobListing.status` defaults to `ACTIVE` for unknown canonical status.
- `jobListing.lastSeenAt` is always filled from normalized row freshness timestamp aligned to the latest raw scrape timestamp.
- `jobListing.sourcePostedAt` and `jobListing.sourceUpdatedAt` remain `null` when source timestamps are unavailable.
- `jobListing.externalApplyUrl` falls back to `sourceUrl` when source apply URL is unavailable.
- `jobListing.workType` defaults to `ONSITE` when source evidence is missing.
- `jobListing.employmentType` defaults to `FULL_TIME` when source evidence is missing.
- `jobListing.experienceLevel` uses deterministic inference and falls back to `ENTRY_LEVEL`.
- `jobListing.province` and `jobListing.city` are resolved from source evidence and open-world location parsing; no static city whitelist is used.
- Placeholder text (`-`, `N/A`, empty string) is rejected for `description`, `requirementSummary`, and display fields.
- `jobListing.requirementSummary` must not start with fixed label prefixes such as `Kualifikasi utama:` or `Requirements:`.

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
- Unsafe display HTML:
  - non-allowlisted tags in `description` or `requirementSummary`
  - HTML attributes, script/style content, event handlers, or inline `javascript:` URL payloads
- Invalid salary range:
  - `salaryMin > salaryMax`
- Backend limit mismatch:
  - sync batch contains more than `100` jobs
  - job or relation text exceeds Backend API internal schema limits
  - `requirements[]` or `skills[]` contains more than `100` rows for one job
- Orphan staging relation:
  - `JobSkill.normalized_job_id != normalized_job.id`
  - `JobRequirement.normalized_job_id != normalized_job.id`

Validation failures are classified as non-retryable contract failures for the sync worker.

Backend data-quality checks compare source enablement settings with rows already present in the backend database. A disabled source with backend jobs is reported as a failure because existing rows can remain visible even when the source is no longer selected for new live runs.

Sync candidate selection is scoped to the corresponding scrape run when stage run-ids are suffixed (`-sync`, `-notify`, and related stage variants). This prevents cross-run mixing while keeping full-run stage chaining consistent.

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
