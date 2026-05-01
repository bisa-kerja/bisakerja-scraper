---
title: Structural Change Policy
description: Rules for changing scraper documentation paths, sections, navigation, and stable sync targets.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Structural Change Policy

Structural changes affect reader paths and central sync assumptions. Treat them as documentation architecture changes.

## Covered Changes

- Moving or renaming any page under `docs/**`.
- Adding or removing a top-level section.
- Changing stable source slugs or service names.
- Changing central sync target mapping.
- Renaming generated reference paths.
- Changing section landing page navigation.

## Stable Paths

| Path group | Stability rule |
| --- | --- |
| `docs/integrations/sources/*.md` | Keep one stable page per source slug |
| `docs/references/*.md` | Keep contract matrices stable after publication |
| `docs/operations/*.md` | Keep runbook paths stable for incident use |
| `docs/standards/*.md` | Keep governance links stable |
| `docs/generated/*` | May refresh content, but path changes require migration note |

## Change Procedure

1. State the reason for the structural change.
2. List affected source and synced paths.
3. Identify readers and sync jobs affected.
4. Update landing pages and related docs.
5. Add redirects or compatibility notes when external links may exist.
6. Run full link and metadata validation.
7. Request structural reviewers.

## Breaking Change Rule

A structural change is breaking when it affects:

- A path referenced by central docs.
- A path used by the sync manifest.
- A source adapter or generated reference canonical route.
- A runbook used during incidents.

Breaking changes require a migration note in the related PR or release checklist.

## Non-Goals

- Do not restructure docs only to match central IA if scraper boundary becomes unclear.
- Do not move service-owned detail into central docs.
- Do not rename source slugs without an adapter and dedup migration plan.

## Related Docs

- [Naming Conventions](./naming-conventions.md)
- [Documentation Sync and Versioning](./documentation-sync-and-versioning.md)
- [Review Process](./review-process.md)

