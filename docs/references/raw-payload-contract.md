---
title: Raw Payload Contract
description: Frozen raw payload evidence, source coverage, required fields, nullability, and redaction requirements for scraper mappers.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-04
---

# Raw Payload Contract

Raw payload contracts are based on captured source list/detail responses. They define mapper inputs, not public API output.

## Source Payload Roots

| Source | Payload root | List records | Detail records |
| --- | --- | --- | --- |
| Dealls | `data.docs[]`; detail `data.result` | Yes | Yes, by slug |
| Glints | `data.searchJobsV3.jobsInPage[]` | Yes | Not captured |
| JobStreet | `data.jobSearchV6.data[]`; detail `data.jobDetails.job` | Yes | Yes, by job id |
| Kalibrr | `pageProps.jobs[]` | Yes | Included in each job object |

## Required Raw Identity

| Source | Required raw identity | Secondary |
| --- | --- | --- |
| Dealls | `id` | `slug` |
| Glints | `id` | none captured as canonical |
| JobStreet | `id` | source URL path when available |
| Kalibrr | `id` | `slug` |

Rows without required raw identity must be quarantined.

## Nullability Rules

| Field class | Raw reality | Normalized behavior |
| --- | --- | --- |
| Salary | Dealls `salaryRange`, Kalibrr salary fields, and JobStreet `salaryLabel` can be null/empty | Preserve unknown as `null` |
| Company metadata | Logo, rank, industry, website can be absent | Keep company name fallback; optional metadata nullable |
| Location | City/province can be partial | Preserve display; normalize best-effort |
| Description | Glints list may lack full detail; JobStreet and Kalibrr detail can contain HTML | Missing detail allowed; HTML sanitized before display, enrichment, or model input |
| Requirement summary | Glints list exposes bounded experience, category, and skill hints | `requirements` may be `null` or summary from explicit list fields only; no inferred detail text |
| Dates | JobStreet includes timestamp plus relative label; other sources expose source timestamps | Prefer timestamp; labels are display-only |
| Skills | Present in Dealls/Glints; may be absent elsewhere | Optional; enrichment can fill later |

## Raw-to-Normalized Gate

A mapper must produce:

- Source identity.
- Title.
- Company fallback.
- Source/apply URL or derivable source URL.
- Last seen timestamp.
- Safe normalized text for any HTML/text fields.
- Detail coverage metadata when a source has no captured detail endpoint or a detail fetch misses.
- Detail completeness metadata for list-only records, especially Glints partial records.

Mappers should not fail the whole run for optional salary, logo, category, or skill gaps.

## Redaction

Raw captures used in docs, fixtures, logs, or examples must remove:

- `authorization`.
- `cookie` and `set-cookie`.
- Session ids and visitor ids.
- Device ids.
- Tracking ids.
- User-specific flags where they imply a real account state.

Use placeholders such as `<redacted>` only when the field name itself is relevant.

## Raw Row Metadata

Raw rows store safe scrape metadata beside the source payload:

- `keyword`
- `requestedLimit`
- `recencyMode`
- `recencyDays`
- `sourceTimestamp`

This metadata supports audit and replay. It is not part of deduplication identity.
