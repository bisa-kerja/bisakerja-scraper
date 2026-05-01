---
title: Documentation Sync and Versioning
description: Scraper documentation synchronization, validation, versioning, release snapshot, and reconciliation rules.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Documentation Sync and Versioning

This standard defines how scraper-owned docs under `docs/**` become central service docs while preserving scraper ownership.

## Core Rules

- Scraper repository owns scraper technical docs.
- Central docs owns service landing pages, shared navigation, and cross-service overview.
- Sync output must use stable service alias `scraper-api`.
- Central latest docs live under `docs/services/scraper-api/synced/**`.
- Release snapshots live under `docs/services/scraper-api/versioned/<release>/**`.
- Central service landing page is never overwritten by sync.

## Merge Sync

Merge sync publishes latest docs after validated source changes.

Required flow:

```text
scraper docs change
  -> service validation
    -> sync bundle build
      -> central validation
        -> latest synced docs publish
```

Merge sync is for routine docs updates, mapper contract changes, operational updates, and generated reference refreshes.

## Release Sync

Release sync captures stable docs for a tagged scraper release.

Use release snapshots when:

- Source contract behavior differs by release.
- Sync behavior or normalized schema changes materially.
- Incident review needs historical docs evidence.
- Stakeholder handoff requires stable documentation state.

Release snapshot rules:

- Snapshot target is immutable after publish.
- Release bundle must include release identifier.
- Assets and generated docs must be copied with the same release snapshot.
- Fixes to old release docs require a new corrective release note or clearly labeled patch snapshot.

## Scheduled Reconciliation

Scheduled reconciliation detects drift between scraper source docs and central latest docs.

It should verify:

- Last accepted source SHA.
- Expected doc count.
- Required metadata.
- Link validity.
- Secret scan result.
- Central path mapping.
- Missing or stale generated references.

Reconciliation reports are operational artifacts, not reader-facing docs.

## Metadata Rules

Every sync-eligible page must include:

| Field | Rule |
| --- | --- |
| `title` | Reader-facing title |
| `description` | One-sentence summary |
| `owner` | Accountable service role |
| `reviewers` | Platform docs maintainer plus affected owner |
| `doc_status` | `draft`, `active`, or `deprecated` |
| `last_reviewed` | Meaningful review date |
| `source_repo` | Required in central synced output |
| `source_path` | Required in central synced output |

The source repository may omit `source_repo` and `source_path` in authoring when the sync pipeline adds them deterministically. Central output must retain them.

## Generated References

Generated docs must be clearly labeled and reproducible.

Allowed generated targets:

| Generated content | Source placement | Central placement |
| --- | --- | --- |
| Index placeholder | `docs/generated/index.md` | `synced/generated/index.mdx` |
| OpenAPI or route inventory | `docs/generated/<name>.md` or `.json` | `synced/generated/<name>.mdx` or `.json` |
| Sync readiness report | `docs/generated/sync-readiness.md` | `synced/generated/sync-readiness.mdx` |

Generated docs must not replace hand-authored architecture, operations, security, or integration contract docs.

## Conflict Rules

| Conflict | Required action |
| --- | --- |
| Missing metadata | Reject bundle |
| Broken local link | Reject bundle |
| Path outside service subtree | Reject bundle |
| Central landing page overwrite | Reject bundle |
| Duplicate central target | Reject bundle |
| Raw credential pattern | Reject bundle and escalate if real |
| Service alias mismatch | Reject bundle |
| Generated and hand-authored contract conflict | Block release until owner review |

## Rollback Rules

- Publish sync changes atomically.
- Keep last-known-good central state.
- Revert sync commit or restore last-known-good bundle for bad publishes.
- Do not require scraper team to regenerate an old bundle before central rollback.
- Record rollback reason, affected source SHA, and restored target.

## Versioning Rule

Use latest docs for normal development and support. Use release snapshots only when behavior needs historical evidence. Do not create versioned docs for routine wording changes.

## Related Docs

- [Documentation Sync](../operations/documentation-sync.md)
- [Metadata Standard](./metadata-standard.md)
- [Naming Conventions](./naming-conventions.md)
- [Contribution Guide](./contribution-guide.md)
- [Review Process](./review-process.md)
- [Versioning and Audience Strategy](./versioning-and-audience-strategy.md)
- [Documentation Release Checklist](../operations/documentation-release-checklist.md)
