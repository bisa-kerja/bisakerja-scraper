---
title: Metadata Standard
description: Required frontmatter metadata for scraper-owned documentation pages.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Metadata Standard

Every maintained scraper document must include frontmatter.

## Required Fields

| Field | Required | Rule |
| --- | --- | --- |
| `title` | Yes | Reader-facing page title |
| `description` | Yes | One-sentence page summary |
| `owner` | Yes | Prefer role owner, usually `data-ingestion-owner` |
| `reviewers` | Yes | Include affected owner roles |
| `doc_status` | Yes | `draft`, `active`, or `deprecated` |
| `last_reviewed` | Yes | Date of last meaningful review |
| `source_repo` | Only synced docs | Original repository id |
| `source_path` | Only synced docs | Original path in source repository |

## Default Scraper Frontmatter

```md
---
title: Page Title
description: One-sentence summary.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---
```

## Status Rules

| Status | Meaning |
| --- | --- |
| `draft` | Documented from references, not yet implementation-verified |
| `active` | Matches implemented scraper behavior and reviewed contracts |
| `deprecated` | Replaced or no longer valid |

## Scraper-Specific Reviewers

| Content | Required reviewers |
| --- | --- |
| Source adapter contract | `data-ingestion-owner`, `backend-owner` |
| Normalized schema contract | `data-ingestion-owner`, `backend-owner` |
| Operations/runbook | `data-ingestion-owner`, `platform-docs-maintainer` |
| Credential or redaction policy | `data-ingestion-owner`, `engineering-lead` |

