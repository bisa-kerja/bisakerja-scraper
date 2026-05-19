"""Deduplication module."""

from modules.deduplication.engine import (
    DedupAction,
    DedupCandidate,
    DedupDecision,
    DedupEngine,
    DedupReason,
    SourceIdentity,
    make_fallback_fingerprint,
    resolve_source_identity,
)

__all__ = [
    "DedupAction",
    "DedupCandidate",
    "DedupDecision",
    "DedupEngine",
    "DedupReason",
    "SourceIdentity",
    "make_fallback_fingerprint",
    "resolve_source_identity",
]
