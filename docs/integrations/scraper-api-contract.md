---
title: Scraper API Contract
description: Internal contract for scraper ingestion outputs, normalized job records, sync handoff, and Backend API consumption.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper API Contract

The scraper contract is a data handoff contract, not a user-facing API contract. The Backend API owns user-facing REST responses.

## Contract Shape

| Area | Required fields |
| --- | --- |
| Source identity | `sourcePlatform`, `externalJobId`, optional `sourceSlug`, `sourceUrl` |
| Company | `name`, optional logo, industry, website |
| Job | `title`, `description`, `employmentType`, `workType`, `experienceLevel`, `status` |
| Location | `display`, optional city, province, country |
| Salary | nullable min/max, currency, period, sanitized display |
| Freshness | `postedAt`, `sourceUpdatedAt`, `lastSeenAt`, `ingestionRunId` |
| Requirements | sanitized text rows and optional category |
| Skills | skill names with optional confidence/source |

## Write Contract

```text
validated staging rows
  -> resolve source platform
  -> resolve/upsert company
  -> upsert job listing by source identity
  -> replace or upsert requirements/skills
  -> update freshness/status
```

## Consumer Contract

Backend API may rely on:

- Stable source-local identity.
- Safe normalized text.
- Nullable salary/location fields.
- Freshness metadata.
- Existing rows remaining readable after source outages.

Backend API must not rely on:

- Raw source payloads.
- Source-specific UI fields.
- Live scraper availability for request-time search.
- Source credentials or source request metadata.

## Error Behavior

| Error | Contract behavior |
| --- | --- |
| Missing source identity | Reject/quarantine row |
| Missing title or company | Reject or hold from normal visibility |
| Missing salary | Sync with `null` salary |
| Parser drift | Quarantine payload and keep source run partial |
| Enrichment failure | Sync base normalized job when required fields are valid |
| Duplicate source job | Upsert by source identity |

