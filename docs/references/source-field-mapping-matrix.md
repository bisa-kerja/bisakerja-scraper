---
title: Source Field Mapping Matrix
description: Cross-source mapping from Dealls, Glints, JobStreet, and Kalibrr raw fields into the normalized scraper job schema.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Source Field Mapping Matrix

This matrix keeps mapper work tied to observed payload fields.

## Canonical Mapping

| Normalized field | Dealls | Glints | JobStreet | Kalibrr |
| --- | --- | --- | --- | --- |
| `sourcePlatform` | constant `dealls` | constant `glints` | constant `jobstreet` | constant `kalibrr` |
| `externalJobId` | `id` | `id` | `id` | `id` |
| `sourceSlug` | `slug` | not captured | URL path when available | `slug` |
| `title` | `role` | `title` | `title` | `name` |
| `company.name` | `company.name` | `company.name` | detail `companyProfile.name`, detail `advertiser.name`, or list `companyName` | `companyName` or `company.name` |
| `company.logoUrl` | `company.logoUrl` | `company.logo` | list `branding.serpLogoUrl`, detail product logo, or company profile logo | `company.logoSmall` |
| `company.industry` | `company.sector` | `company.industry.name` | detail `companyProfile.overview.industry` when available | `company.industry` |
| `location.display` | `city.name`, `country.name` | `location.formattedName` | detail `job.location.label` or list `locations[].label` | `googleLocation.addressComponents` |
| `employmentType` | `employmentTypes[]` | `type` | `workTypes[]` | `tenure` |
| `workType` | `workplaceType` | `workArrangementOption` | `workArrangements.displayText` | `isHybrid`, `isWorkFromHome` |
| `salary.min` | `salaryRange.start` | `salaries[].minAmount` | parsed `salaryLabel` only if reliable | `baseSalary` |
| `salary.max` | `salaryRange.end` | `salaries[].maxAmount` | parsed `salaryLabel` only if reliable | `maximumSalary` |
| `salary.currency` | infer configured source currency if numeric salary exists | `salaries[].CurrencyCode` | parse label only if reliable | `salaryCurrency` |
| `salary.period` | configured/monthly when source semantics confirm | `salaries[].salaryMode` | parse label only if reliable | `salaryInterval` |
| `salary.display` | derived safe label or null | derived safe label or null | `salaryLabel` | derived safe label or null |
| `description` | detail `description` if fetched | not available from captured detail | detail `job.content` clean text or list `teaser` | `description` HTML clean text |
| `requirements` | detail `requirements` if fetched | safe summary from list `minYearsOfExperience`, `maxYearsOfExperience`, `hierarchicalJobCategory.name`, `skills[].skill.name` when available | detail `job.products.bullets` or list `bulletPoints[]` | `qualifications` HTML clean text |
| `skills` | `skills[].name` | `skills[].skill.name` | enrichment or tags only if mapped | enrichment or detail-derived |
| `postedAt` | `publishedAt` | `createdAt` | `listingDate.dateTimeUtc` | `activationDate` or `createdAt` |
| `sourceUpdatedAt` | source update field if present | `updatedAt` | source update field if present | `activationDate` |
| `lastSeenAt` | scrape time | scrape time | scrape time | scrape time |

## Latest Timestamp Fallbacks

| Source | Preferred | Fallback |
| --- | --- | --- |
| Dealls | `publishedAt` | `latestUpdatedAt` |
| Glints | `createdAt` | `updatedAt` |
| JobStreet | `listingDate.dateTimeUtc` | detail `listedAt.dateTimeUtc` |
| Kalibrr | `activationDate` | `createdAt`, then `updatedAt` |

## Transform Rules

- Normalize enum-like fields into backend-compatible values.
- Preserve raw source labels only as safe display metadata.
- Convert empty string salary to `null`.
- Strip or sanitize HTML before model/display use.
- Keep mapper field provenance outside the canonical job object.
- Ignore UI-only fields unless a product contract explicitly adopts them.
- For Glints list-only records, mark `presentation.source_labels.detailCompleteness = partial`.

## Dedup Matrix

| Source | Dedup key |
| --- | --- |
| Dealls | `dealls + id` |
| Glints | `glints + id` |
| JobStreet | `jobstreet + id` |
| Kalibrr | `kalibrr + id` |

Cross-source duplicate detection is not MVP behavior.
