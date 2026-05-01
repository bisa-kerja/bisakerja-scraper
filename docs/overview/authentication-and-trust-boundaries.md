---
title: Scraper Authentication and Trust Boundaries
description: Authentication assumptions, service trust boundaries, source credential handling, and authorization ownership for scraper workflows.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Authentication and Trust Boundaries

The scraper crosses two major trust boundaries: external job platforms into Bisakerja ingestion, and scraper-owned staging into Backend API-consumed normalized data.

## Boundary Matrix

| Boundary | Risk | Owner | Rule |
| --- | --- | --- | --- |
| External source to Scraper API | Untrusted payloads, source drift, blocked requests | Scraper API | Validate and normalize before publishing |
| Scraper API to Local Scraper DB | Raw payloads may include noisy or sensitive headers | Scraper API | Store only sanitized captures in docs/artifacts |
| Local Scraper DB to Main Backend DB | Malformed normalized records can affect product reads | Scraper API | Enforce required fields, identity, and sync checks |
| Main Backend DB to Backend API | User-facing API must remain stable | Backend API | Read normalized records; never expose raw source payloads |
| Backend API to Frontend UI | User auth and ownership | Backend API | Backend owns auth, authorization, and response shaping |

## Authentication Model

| Actor | Authentication expectation |
| --- | --- |
| End user | Authenticated by Backend API only |
| Frontend UI | Sends session/token state to Backend API only |
| Scraper API internal jobs | Use scheduler/worker trust plus internal service credentials if endpoints are exposed |
| Scraper API operators | Use internal service credentials and restricted network/operator permissions |
| External sources | Use source-specific public, semi-public, or configured credentials |
| JobStreet | Requires configured authorization and session-derived request material; never hardcode in docs |
| Glints, Kalibrr, Dealls | Browser-like headers may be required; cookies remain optional/sensitive and must be redacted |

## Authorization Ownership

The Backend API owns authorization for:

- User profile reads and writes.
- Preferences.
- Bookmarks.
- Application tracker.
- User-specific AI result history.
- Any user-facing job response envelope.

The Scraper API owns only ingestion authorization:

- Who can trigger a scraper run.
- Who can force or cancel a run.
- Who can inspect run status and source health.
- Which workers can read raw/staging stores.
- Which sync process can write scraper-owned job tables.

## Source Credential Rules

- Store bearer tokens, cookies, session ids, visitor ids, and dynamic anti-abuse identifiers only in secret/config stores.
- Do not publish raw request captures containing `authorization`, `cookie`, `set-cookie`, `x-seek-ec-sessionid`, `x-seek-ec-visitorid`, device ids, or session ids.
- Document header names and sanitized placeholders only.
- Rotate or refresh source credentials outside documentation.
- Treat public-looking headers as operational config, not product contract.

## Validation Gates

Before source data reaches normalized job tables:

1. Required identity exists: source platform plus external id, slug, or numeric id.
2. Required display fields exist: title, company text or company relation, source URL/apply URL, last seen timestamp.
3. HTML fields are sanitized before display or model use.
4. Salary, location, and posted-date fields may remain nullable instead of being guessed.
5. UI/noise fields are dropped unless explicitly mapped to a canonical field.

## Operational Security Gates

Before scraper artifacts are shared or published:

1. Source request headers are stripped or redacted.
2. Cookies, bearer tokens, session ids, visitor ids, and device ids are absent.
3. Raw HTML is sanitized or represented as escaped text.
4. Generated API references contain schemas only, not real request examples with secrets.
5. Source auth failures are represented as sanitized error categories.

## Related Docs

- [Security Operations](../operations/security.md)
- [Payload Redaction Policy](../standards/payload-redaction-policy.md)
- [API Response Standard](../api-response-standard.md)
