---
title: Glossary
description: Canonical scraper terminology for source adapters, raw payloads, normalization, enrichment, and sync.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Glossary

| Term | Meaning |
| --- | --- |
| Scraper API | Service that collects, stores, normalizes, enriches, and prepares external job data for sync |
| Source adapter | Per-platform module that fetches and parses one job source |
| Source platform | External provider such as Dealls, Glints, JobStreet, or Kalibrr |
| Raw payload | Original source response stored for replay, debug, and mapper validation |
| Normalized job | Source-agnostic job record shaped for Backend API consumption |
| External job id | Stable id/slug/id-number from a source, mapped to `externalJobId` |
| Dedup key | `sourcePlatform + externalJobId` |
| List endpoint | Source endpoint that returns many jobs |
| Detail endpoint | Source endpoint or payload section that returns full job detail |
| Enrichment | AI or rule-based processing for skills, requirements, and text structuring |
| Staging DB | Local scraper database area used before sync to main Backend API database |
| Sync | Upsert prepared normalized records into the main database shape |
| `lastSeenAt` | Last scraper observation timestamp for a job |
| Stale job | Job not seen recently but still retained for read/history flows |
| HTML field | Source-provided HTML text requiring sanitization |
| UI noise | Source response fields useful for its own UI but not canonical for Bisakerja |
| Redaction | Removal of secrets, cookies, bearer tokens, sessions, and tracking ids from docs/examples |

