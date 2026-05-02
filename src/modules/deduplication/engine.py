from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from shared.text import clean_text


class DedupAction(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    QUARANTINE = "quarantine"


class DedupReason(StrEnum):
    NEW_IDENTITY = "new_identity"
    DUPLICATE_IDENTITY = "duplicate_identity"
    MISSING_IDENTITY = "missing_identity"
    FALLBACK_FINGERPRINT = "fallback_fingerprint"
    SLUG_DRIFT = "slug_drift"
    IDENTITY_COLLISION = "identity_collision"


@dataclass(frozen=True)
class SourceIdentity:
    source_platform: str
    external_id: str | None
    source_slug: str | None
    fingerprint: str | None
    key: str | None
    uses_fallback: bool = False


@dataclass(frozen=True)
class DedupCandidate:
    identity: SourceIdentity
    title: str | None = None
    company_name: str | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class DedupDecision:
    action: DedupAction
    reason: DedupReason
    identity: SourceIdentity
    existing: DedupCandidate | None = None
    dedup_reason: str | None = None


class DedupEngine:
    def __init__(self) -> None:
        self._seen: dict[str, DedupCandidate] = {}

    def evaluate(self, candidate: DedupCandidate) -> DedupDecision:
        key = candidate.identity.key
        if key is None:
            return DedupDecision(
                action=DedupAction.QUARANTINE,
                reason=DedupReason.MISSING_IDENTITY,
                identity=candidate.identity,
                dedup_reason=DedupReason.MISSING_IDENTITY.value,
            )

        existing = self._seen.get(key)
        if existing is None:
            self._seen[key] = candidate
            reason = (
                DedupReason.FALLBACK_FINGERPRINT
                if candidate.identity.uses_fallback
                else DedupReason.NEW_IDENTITY
            )
            return DedupDecision(
                action=DedupAction.INSERT,
                reason=reason,
                identity=candidate.identity,
                dedup_reason=reason.value,
            )

        reason = _duplicate_reason(existing, candidate)
        self._seen[key] = candidate
        return DedupDecision(
            action=DedupAction.UPDATE,
            reason=reason,
            identity=candidate.identity,
            existing=existing,
            dedup_reason=reason.value,
        )


def resolve_source_identity(
    *,
    source_platform: Any,
    external_id: Any = None,
    source_slug: Any = None,
    title: Any = None,
    company_name: Any = None,
    source_url: Any = None,
) -> SourceIdentity:
    platform = _required_text(source_platform)
    external = _optional_text(external_id)
    slug = _optional_text(source_slug)
    if not platform:
        return SourceIdentity(
            source_platform="",
            external_id=external,
            source_slug=slug,
            fingerprint=None,
            key=None,
        )

    if external:
        return SourceIdentity(
            source_platform=platform,
            external_id=external,
            source_slug=slug,
            fingerprint=None,
            key=f"{platform}:{external}",
        )

    fingerprint = make_fallback_fingerprint(
        source_platform=platform,
        source_slug=slug,
        title=title,
        company_name=company_name,
        source_url=source_url,
    )
    return SourceIdentity(
        source_platform=platform,
        external_id=None,
        source_slug=slug,
        fingerprint=fingerprint,
        key=f"{platform}:fingerprint:{fingerprint}" if fingerprint else None,
        uses_fallback=fingerprint is not None,
    )


def make_fallback_fingerprint(
    *,
    source_platform: Any,
    source_slug: Any = None,
    title: Any = None,
    company_name: Any = None,
    source_url: Any = None,
) -> str | None:
    payload = {
        "source_platform": _required_text(source_platform),
        "source_slug": _optional_text(source_slug),
        "title": _optional_text(title),
        "company_name": _optional_text(company_name),
        "source_url": _optional_text(source_url),
    }
    if not payload["source_platform"]:
        return None
    if not any(
        [payload["source_slug"], payload["title"], payload["company_name"], payload["source_url"]]
    ):
        return None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _duplicate_reason(existing: DedupCandidate, incoming: DedupCandidate) -> DedupReason:
    slug_changed = (
        existing.identity.source_slug
        and incoming.identity.source_slug
        and existing.identity.source_slug != incoming.identity.source_slug
    )
    identity_text_changed = _optional_text(existing.title) != _optional_text(
        incoming.title
    ) and _optional_text(existing.company_name) != _optional_text(incoming.company_name)
    if slug_changed and identity_text_changed:
        return DedupReason.IDENTITY_COLLISION
    if slug_changed:
        return DedupReason.SLUG_DRIFT
    return DedupReason.DUPLICATE_IDENTITY


def _required_text(value: Any) -> str:
    text = _optional_text(value)
    return text.lower() if text else ""


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_text(value)
    return None
