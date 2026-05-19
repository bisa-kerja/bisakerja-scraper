---
title: Parsing and Normalization Module
description: Raw payload parser, source mapper, HTML sanitizer, canonical schema mapping, failure handling, observability, and tests.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-07
---

# Parsing and Normalization Module

The parsing and normalization module converts source-specific payloads into canonical staging records.

Normalization execution path:

- Source mapper always produces baseline canonical output.
- When OpenAI provider is enabled in execute mode, pipeline also runs AI-assisted normalization using an embedded standalone prompt contract.
- AI failure policy is fail-open by default in pipeline config, so mapper output remains available when provider calls fail.
- Pipeline can be configured fail-closed to quarantine records when AI normalization fails.

## Responsibility

| Area | Rule |
| --- | --- |
| Parser | Reads source payload roots and extracts source fields |
| Mapper | Converts source values into canonical job/company/location/salary fields |
| Sanitizer | Converts display fields into sanitized semantic HTML and strips unsafe markup |
| Validation gate | Blocks or quarantines rows missing required identity/display fields |
| Provenance | Records source field paths used by each mapper |

## Canonical Output

The in-process canonical job object is validated before persistence or sync. The schema separates source identity, canonical fields, and display-only presentation metadata.

Mapper output also carries field provenance beside the canonical object. Provenance records the raw path used for important canonical fields such as title, company, salary, description, and requirements. This metadata is for debugging and contract review; it is not part of the canonical job schema sent to downstream consumers.

Required canonical fields:

- `source.platform`.
- `source.externalJobId`.
- `source.sourceUrl`.
- `source.scrapedAt`.
- `title`.
- `company.name`.
- `lastSeenAt`.

Nullable canonical fields:

- `source.sourceSlug`.
- `source.externalApplyUrl`.
- `company.logoUrl`.
- `company.industry`.
- `location.display`, `location.city`, `location.region`, and `location.country`.
- `salary.minAmount`, `salary.maxAmount`, `salary.currency`, `salary.period`, and `salary.display`.
- `description`.
- `requirements`.
- `postedAt`.

Presentation-only fields:

- Relative posted labels.
- Source salary labels when numeric parsing is not reliable.
- Badges derived from safe source flags.
- Raw source labels used for debugging mapper behavior.

## Field Rules

| Field | Rule |
| --- | --- |
| Salary | Unknown stays `null`; structured ranges and reliable labels normalize into min, max, currency, period, and display label |
| HTML | Sanitize before staging, enrichment, display, or model input |
| Raw HTML | Keep only in raw payload storage; canonical `description` is sanitized semantic display HTML while `requirements` stays plain text |
| Dates | Absolute timestamps normalize to timezone-aware UTC datetimes |
| Relative labels | Keep display-only; do not convert labels such as `3 hari yang lalu` into fake timestamps |
| Tags/skills | Keep only mapped canonical tags or skill names |
| UI/noise | Drop tracking, experiment, source UI state, user-specific flags |

## Salary Normalization

Salary normalization accepts source-provided numeric fields first, then parses reliable source labels when structured fields are absent.

| Input | Output rule |
| --- | --- |
| `null`, empty, or absent salary | Keep canonical salary as `null` |
| Numeric min/max fields | Preserve values and normalize currency/period labels |
| Indonesian range labels such as `Rp 5 - 8 juta per bulan` | Parse min/max, currency, period, and preserve original label |
| Vague labels such as `Competitive salary` | Preserve label only; do not invent numbers |
| Reversed range | Store lower number as min and higher number as max |

Currency normalization keeps ISO-style three-letter codes such as `IDR`, `USD`, and `SGD`. Period normalization uses canonical values for hourly, daily, monthly, yearly, or unknown.

## Posted Date Normalization

Posted date normalization separates canonical time from presentation text.

| Input | Output rule |
| --- | --- |
| ISO datetime with `Z` or offset | Convert to timezone-aware UTC |
| Date-only value | Store UTC midnight for that date |
| Relative label | Preserve as presentation label only |
| Invalid date text | Leave canonical `postedAt` empty |
| Run timestamp | Store as reference metadata for relative-label interpretation, not as `postedAt` |

## Failure Modes

| Failure | Handling |
| --- | --- |
| Missing source identity | Quarantine row |
| Missing title/company/source URL | Hold from visible staging |
| Invalid HTML | Strip unsafe content and attributes; keep allowlisted display HTML only |
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
- [Backend Sync Schema Map](../references/backend-sync-schema-map.md)
- [AI Normalization Prompt Contract](../references/ai-normalization-prompt.md)
- [Data Flow](../overview/data-flow.md)
- [Scraper Database Design](../database.md)
