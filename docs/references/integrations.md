---
title: Integration References
description: Index of scraper integration contracts, source adapters, raw payload contracts, and field mapping references.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Integration References

Use these references when changing source adapters, mappers, or sync behavior.

## Source Contracts

| Source | Contract | Key facts |
| --- | --- | --- |
| Dealls | [Dealls Source Contract](../integrations/sources/dealls.md) | REST, list rich, nullable salary |
| Glints | [Glints Source Contract](../integrations/sources/glints.md) | Unofficial GraphQL, list-first |
| JobStreet | [JobStreet Source Contract](../integrations/sources/jobstreet.md) | GraphQL with bearer auth |
| Kalibrr | [Kalibrr Source Contract](../integrations/sources/kalibrr.md) | Next.js data, dynamic `buildId`, HTML detail fields |

## Shared Contracts

- [Job Sources](../integrations/job-sources.md)
- [Scraper API Contract](../integrations/scraper-api-contract.md)
- [Raw Payload Contract](./raw-payload-contract.md)
- [Source Field Mapping Matrix](./source-field-mapping-matrix.md)
- [Payload Redaction Policy](../standards/payload-redaction-policy.md)

## Contract Rule

Source-specific differences stop at the adapter and normalizer boundary. Backend API consumers receive normalized job records only.

