---
title: Parsing and Normalization Module
description: Raw payload parser, source mapper, HTML sanitizer, canonical schema mapping, failure handling, observability, and tests.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Parsing and Normalization Module

The parsing and normalization module converts source-specific payloads into canonical staging records.

## Responsibility

| Area | Rule |
| --- | --- |
| Parser | Reads source payload roots and extracts source fields |
| Mapper | Converts source values into canonical job/company/location/salary fields |
| Sanitizer | Converts HTML description and qualifications into safe content |
| Validation gate | Blocks or quarantines rows missing required identity/display fields |

## Canonical Output

Minimum output:

- `sourcePlatform`.
- `externalJobId`.
- `sourceSlug` when available.
- `sourceUrl` or `externalApplyUrl`.
- `title`.
- `company.name`.
- `location.display` when present.
- Nullable salary fields.
- Sanitized description and requirements when present.
- `postedAt` when timestamp exists.
- `lastSeenAt`.

## Field Rules

| Field | Rule |
| --- | --- |
| Salary | Unknown stays `null`; never infer exact number from vague label |
| HTML | Sanitize before staging, enrichment, display, or model input |
| Relative labels | Keep display-only unless timestamp parser is documented |
| Tags/skills | Keep only mapped canonical tags or skill names |
| UI/noise | Drop tracking, experiment, source UI state, user-specific flags |

## Failure Modes

| Failure | Handling |
| --- | --- |
| Missing source identity | Quarantine row |
| Missing title/company/source URL | Hold from visible staging |
| Invalid HTML | Strip unsafe content; keep sanitized text |
| Unknown enum | Store raw display text only if canonical mapping is absent |
| Source shape drift | Mark mapper failure and attach sanitized field path |

## Observability

Track:

- Parsed rows.
- Accepted rows.
- Quarantined rows by reason.
- Sanitization count.
- Enum fallback count.
- Mapper version.

## Tests

| Test | Purpose |
| --- | --- |
| Raw fixture per source | Confirms mapper reads captured payload roots |
| Null salary | Confirms unknown salary remains `null` |
| HTML sanitizer | Confirms unsafe markup does not survive |
| Required field gate | Confirms missing identity/title/company blocks visibility |
| Noise drop | Confirms UI/session/tracking fields are not persisted |

## Related Docs

- [Source Field Mapping Matrix](../references/source-field-mapping-matrix.md)
- [Data Flow](../overview/data-flow.md)
- [Scraper Database Design](../database.md)

