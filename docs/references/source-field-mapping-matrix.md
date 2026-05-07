---
title: Source Field Mapping Matrix
description: Cross-source mapping from Dealls, Glints, JobStreet, Kalibrr, and Kitalulus raw fields into the normalized scraper job schema.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-07
---

# Source Field Mapping Matrix

This matrix keeps mapper work tied to observed payload fields.

## Canonical Mapping

| Normalized field | Dealls | Glints | JobStreet | Kalibrr | Kitalulus |
| --- | --- | --- | --- | --- | --- |
| `sourcePlatform` | constant `dealls` | constant `glints` | constant `jobstreet` | constant `kalibrr` | constant `kitalulus` |
| `externalJobId` | `id` | `id` | `id` | `id` | `id` |
| `sourceSlug` | `slug` | not captured | URL path when available | `slug` | `slug` |
| `title` | `role` | `title` | `title` | `name` | `positionName` |
| `company.name` | `company.name` | `company.name` | detail `companyProfile.name`, detail `advertiser.name`, or list `companyName` | `companyName` or `company.name` | `company.name` |
| `company.logoUrl` | `company.logoUrl` | `company.logo` | list `branding.serpLogoUrl`, detail product logo, or company profile logo | `company.logoSmall` | `company.logoUrl` |
| `company.industry` | `company.sector` | `company.industry.name` | detail `companyProfile.overview.industry` when available | `company.industry` | detail `company.companyIndustry.name` |
| `location.display` | `city.name`, `country.name` | `location.formattedName` | detail `job.location.label` or list `locations[].label` | `googleLocation.addressComponents` | `province.name`, `city.name` |
| `employmentType` | `employmentTypes[]` | `type` | `workTypes[]` | `tenure` | `typeStr`, `googleType` |
| `workType` | `workplaceType` | `workArrangementOption` | `workArrangements.displayText` | `isHybrid`, `isWorkFromHome` | `locationSiteStr` |
| `salary.min` | `salaryRange.start` | `salaries[].minAmount` | parsed `salaryLabel` only if reliable | `baseSalary` | `salaryLowerBound`; `0` means unknown |
| `salary.max` | `salaryRange.end` | `salaries[].maxAmount` | parsed `salaryLabel` only if reliable | `maximumSalary` | `salaryUpperBound`; `0` means unknown |
| `salary.currency` | infer configured source currency if numeric salary exists | `salaries[].CurrencyCode` | parse label only if reliable | `salaryCurrency` | infer `IDR` only when numeric salary exists |
| `salary.period` | configured/monthly when source semantics confirm | `salaries[].salaryMode` | parse label only if reliable | `salaryInterval` | monthly when source semantics confirm |
| `salary.display` | derived safe label or null | derived safe label or null | `salaryLabel` | derived safe label or null | derived safe label or null |
| `description` | detail `description` if fetched | factual source-limited summary from list evidence when detail unavailable | detail `job.content` sanitized display HTML or list `teaser` | `description` sanitized display HTML | detail `formattedDescription` sanitized display HTML or `description` clean text |
| `requirements` | detail `requirements` if fetched | safe summary from list `minYearsOfExperience`, `maxYearsOfExperience`, `hierarchicalJobCategory.name`, `skills[].skill.name` when available | detail `job.products.bullets` or list `bulletPoints[]` | `qualifications` HTML clean text | detail `formattedDescription`/`description`; exclude `benefits[]` |
| `skills` | `skills[].name` | `skills[].skill.name` | enrichment or tags only if mapped | enrichment or detail-derived | detail `skillTags[]` |
| `postedAt` | `publishedAt` | `createdAt` | `listingDate.dateTimeUtc` | `activationDate` or `createdAt` | detail `updatedAt` as best available source timestamp |
| `sourceUpdatedAt` | source update field if present | `updatedAt` | source update field if present | `activationDate` | detail `updatedAt` |
| `lastSeenAt` | scrape time | scrape time | scrape time | scrape time | scrape time |

## Latest Timestamp Fallbacks

| Source | Preferred | Fallback |
| --- | --- | --- |
| Dealls | `publishedAt` | `latestUpdatedAt` |
| Glints | `createdAt` | `updatedAt` |
| JobStreet | `listingDate.dateTimeUtc` | detail `listedAt.dateTimeUtc` |
| Kalibrr | `activationDate` | `createdAt`, then `updatedAt` |
| Kitalulus | detail `updatedAt` | `updatedAtStr` as display-only label |

## Transform Rules

- Normalize enum-like fields into backend-compatible values.
- Preserve raw source labels only as safe display metadata.
- Convert empty string salary to `null`.
- Sanitize description display HTML into allowlisted semantic tags (`p`, `ul`, `ol`, `li`, `strong`, `em`, `br`) without attributes.
- Keep downstream `requirements` extraction input as plain text evidence (not rich HTML).
- Keep mapper field provenance outside the canonical job object.
- Ignore UI-only fields unless a product contract explicitly adopts them.
- For Glints records, set `detailCoverage=unavailable` and `detailCompleteness=partial`.
- For Dealls/JobStreet detail failures, keep list record with `detailCoverage=missing`, explicit `missingReason`, and `attempted=true`.
- For Kalibrr records, set `detailCoverage=embedded` and `detailCompleteness=complete`.
- For Kitalulus records, set `detailCoverage=available` when `VacancyBySlug` succeeds; benefits are not requirements.

## Detail Capability Matrix

| Source | Detail capability | Metadata rule |
| --- | --- | --- |
| Dealls | external detail endpoint by slug | `detailCoverage=available` when fetched, otherwise `missing` + reason |
| Glints | public detail unavailable | `detailCoverage=unavailable`, `detailCompleteness=partial`, `attempted=false` |
| JobStreet | GraphQL `jobDetails` by id | `detailCoverage=available` when fetched, otherwise `missing` + reason |
| Kalibrr | embedded detail in list payload | `detailCoverage=embedded`, `detailCompleteness=complete` |
| Kitalulus | GraphQL `VacancyBySlug` by slug | `detailCoverage=available` when fetched, otherwise `missing` + reason |

## Dedup Matrix

| Source | Dedup key |
| --- | --- |
| Dealls | `dealls + id` |
| Glints | `glints + id` |
| JobStreet | `jobstreet + id` |
| Kalibrr | `kalibrr + id` |
| Kitalulus | `kitalulus + id` |

Cross-source duplicate detection is not MVP behavior.
