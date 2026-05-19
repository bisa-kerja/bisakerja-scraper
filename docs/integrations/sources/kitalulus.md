---
title: Kitalulus Source Contract
description: Kitalulus GraphQL source adapter contract, list and detail payload mapping, request requirements, and error behavior.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-06
---

# Kitalulus Source Contract

Kitalulus is a supported GraphQL source based on captured list and detail responses in `raw-response-kitalulus.txt`.

## Endpoint

| Purpose | Method | URL | Operation | Root |
| --- | --- | --- | --- | --- |
| List | `POST` | `https://gql.kitalulus.com/graphql` | `Vacancies` | `data.vacanciesV4.list[]` |
| Detail | `POST` | `https://gql.kitalulus.com/graphql` | `VacancyBySlug` | `data.vacancyBySlug` |

## Request Requirements

| Requirement | Rule |
| --- | --- |
| Headers | Browser-like headers, `accept-language: id`, `origin: https://www.kitalulus.com`, `referer: https://www.kitalulus.com/`, `x-channel: web` |
| Auth | No bearer token or cookie captured for baseline list/detail |
| List variables | `keyword`, `pagination.page`, `pagination.limit`, and filters including `sortBy=updatedAt` |
| Detail variables | `slug` from list record |
| Pagination | Use `hasNextPage`, `page`, and configured limit |
| Enablement | Live execute requires `KITALULUS_ENABLED=true`; dry-run fixture validation remains available when disabled |

Runtime ordering:

- `SCRAPER_RECENCY_MODE=latest`: sends `sortBy=updatedAt`.
- `SCRAPER_RECENCY_MODE=native`: omits `sortBy` and keeps platform default ordering; pagination, keyword, and empty filter buckets still apply.

## Field Mapping

| Source field | Normalized field | Rule |
| --- | --- | --- |
| `id` | `externalJobId` | Required |
| `slug` | `sourceSlug`, source URL component | Preserve |
| `positionName` | `title` | Required |
| `company.name` | `company.name` | Required fallback |
| `company.id`, `company.code` | `company.sourceCompanyId` | Prefer `id` when detail exists |
| `company.slug` | `company.sourceSlug` | Detail only |
| `company.logoUrl` | `company.logoUrl` | Strip or avoid logging signed query values |
| `company.companyIndustry.name` | `company.industry` | Detail only |
| `province.name`, `city.name` | `location.region`, `location.city`, `location.display` | Join safely |
| `typeStr`, `googleType` | `employmentType` | Map Indonesian/source labels to canonical enum |
| `locationSiteStr` | `workType` | Map WFO/WFH/hybrid labels |
| `salaryLowerBound`, `salaryUpperBound` | `salary.min`, `salary.max` | Treat `0` as unknown/null |
| `updatedAt` | `postedAt`/`sourceUpdatedAt` | Prefer numeric timestamp from detail |
| `updatedAtStr` | `presentation.posted_label` | Display-only unless parsed with capture time |
| `description`, `formattedDescription` | `description`, `requirements` | Sanitize HTML; preserve requirement/responsibility split |
| `skillTags[]` | `skills[]` | Deduplicate case-insensitively |
| `benefits[].copy` | Benefit metadata only | Must not become `requirements` |

## Detail Handling

List records are enough for identity, title, company, location, salary, type, and update label. Detail records add rich description, formatted HTML, skills, benefits, company industry, work location, and close/publish fields.

If detail fetch fails, keep the list record with explicit detail coverage metadata (`coverage=missing`, `detailCompleteness=partial`, `attempted=true`) and avoid inventing description or requirements.

## Error Behavior

- Missing `id`, `slug`, `positionName`, or `company.name` quarantines the record.
- GraphQL errors should fail only the affected source run.
- Empty salary bounds or `0` values mean unknown salary.
- `isClosed=true` or `isPublished=false` should map to inactive/expired lifecycle when implemented.
- Signed image URL query strings must not be logged as source credentials.
