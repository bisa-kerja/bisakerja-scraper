---
title: Scraper Documentation Sync
description: Source-to-target mapping, sync bundle manifest, validation, conflict handling, rollback, and reconciliation for scraper docs.
owner: data-ingestion-owner
reviewers:
  - platform-docs-maintainer
  - backend-owner
doc_status: draft
last_reviewed: 2026-05-01
---

# Scraper Documentation Sync

Scraper docs are service-owned. They may be synchronized into central Bisakerja docs without moving ownership away from this repository.

## Sync Scope

| Source | Value |
| --- | --- |
| Stable service alias | `scraper-api` |
| Source repository | `bisakerja-scraper` until repo slug is finalized |
| Source docs root | `docs/**` |
| Latest central target | `docs/services/scraper-api/synced/**` |
| Release snapshot target | `docs/services/scraper-api/versioned/<release>/**` |
| Central landing page | `docs/services/scraper-api/index.mdx` |

Central landing pages are central-owned and must not be overwritten by scraper sync.

## Sync Modes

| Mode | Trigger | Target | Purpose |
| --- | --- | --- | --- |
| Merge sync | Merge to scraper default branch | `synced/**` | Keep latest scraper docs fresh |
| Release sync | Scraper release tag or release event | `versioned/<release>/**` | Preserve release-specific docs |
| Scheduled reconciliation | Central docs scheduled job | Report or refresh `synced/**` | Detect drift and retry failed sync |

## Path Mapping

Mapping must keep relative structure under `docs/**`.

| Source path | Latest central path |
| --- | --- |
| `docs/architecture.md` | `docs/services/scraper-api/synced/architecture.mdx` |
| `docs/operations/observability.md` | `docs/services/scraper-api/synced/operations/observability.mdx` |
| `docs/integrations/sources/glints.md` | `docs/services/scraper-api/synced/integrations/sources/glints.mdx` |
| `docs/references/raw-payload-contract.md` | `docs/services/scraper-api/synced/references/raw-payload-contract.mdx` |
| `docs/generated/index.md` | `docs/services/scraper-api/synced/generated/index.mdx` |

Rules:

- Convert `.md` to `.mdx` in central publish output.
- Rewrite local relative `.md` links to `.mdx` links during central publish.
- Keep `docs/**` relative directories.
- Reject any path that resolves outside the scraper service subtree.
- Do not publish to central overview, shared standards, or service landing pages.
- Do not copy root raw response captures into central docs.

## Sync Bundle

Expected bundle:

```text
sync-bundle/
  manifest.json
  docs/
  assets/
```

Minimum `manifest.json`:

```json
{
  "service": "scraper-api",
  "source_repo": "bisakerja-scraper",
  "source_ref": "main",
  "source_sha": "0000000000000000000000000000000000000000",
  "generated_at": "2026-05-01T00:00:00Z",
  "sync_mode": "merge",
  "doc_count": 0,
  "asset_count": 0
}
```

Manifest rules:

- `service` must equal `scraper-api`.
- `sync_mode` must be `merge`, `release`, or `scheduled-reconcile`.
- `source_sha` must identify the exact source revision.
- `doc_count` and `asset_count` must match bundle contents.
- Release bundles must identify release through `source_ref` or extra release metadata.

## Validation Checks

Service-side validation must check:

- Required frontmatter exists.
- Local docs links resolve.
- JSON code blocks parse.
- Paths stay inside `docs/**`.
- No raw credential, cookie, bearer, session, visitor, or device values appear.
- Raw response files are not included unless explicitly sanitized and approved as fixtures.
- Generated docs are clearly labeled.

Central validation must check:

- Service alias is recognized.
- Target paths stay inside `docs/services/scraper-api/synced/**` or `versioned/<release>/**`.
- No central landing page is overwritten.
- No duplicate target paths exist.
- Metadata remains intact after `.md` to `.mdx` conversion.
- Whole-site build and broken-link checks pass.

## Conflict Handling

| Conflict | Behavior |
| --- | --- |
| Bundle targets central landing page | Reject sync |
| Path escapes scraper service subtree | Reject sync |
| Duplicate target path | Reject sync |
| Missing required frontmatter | Reject sync |
| Service alias differs from manifest | Reject sync |
| Secret pattern detected | Reject sync and rotate if real credential leaked |
| Generated docs disagree with hand-authored contract | Block release or require owner review |

## Rollback

Documentation sync must behave like controlled publish:

- Apply accepted sync as one atomic central change.
- Keep last-known-good central state.
- If validation fails before publish, keep central docs unchanged.
- If bad sync is published, revert sync commit or restore last-known-good bundle.
- Rollback must preserve central service landing page.

## Related Docs

- [Documentation Sync and Versioning](../standards/documentation-sync-and-versioning.md)
- [Deployment Overview](./deployment-overview.md)
- [Verification Matrix](./verification-matrix.md)
- [Metadata Standard](../standards/metadata-standard.md)

