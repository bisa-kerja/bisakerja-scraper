from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.persistence import (
    NormalizationEligibilityDecision,
    NormalizedJob,
    RawJob,
    SyncEvent,
    stable_payload_hash,
)


class EligibilityDecisionReason(StrEnum):
    NORMALIZATION_ELIGIBLE = "normalization_eligible"
    DUPLICATE_IN_SCRAPE_SCOPE = "duplicate_in_scrape_scope"
    EXISTING_BACKEND = "existing_backend"
    EXISTING_NORMALIZED_SYNCED = "existing_normalized_synced"
    EXISTING_NORMALIZED_UNSYNCED = "existing_normalized_unsynced"
    MISSING_IDENTITY = "missing_identity"
    IDENTITY_CONFLICT = "identity_conflict"
    REPROCESS_REQUIRED = "reprocess_required"


@dataclass(frozen=True)
class EligibilityDecisionInput:
    raw_job: RawJob
    reason: EligibilityDecisionReason
    identity_key: str | None
    identity_hash: str | None
    payload_hash: str | None
    backend_job_id: str | None = None
    normalized_job_id: str | None = None
    normalized_sync_state: str | None = None
    reason_details: dict[str, Any] | None = None


class EligibilityResolver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_for_raw_jobs(
        self,
        *,
        scrape_run_id: str,
        raw_jobs: list[RawJob],
        backend_existing: dict[tuple[str, str], dict[str, Any]],
        allow_reprocess: bool = False,
        max_sync_attempts: int = 3,
    ) -> list[NormalizationEligibilityDecision]:
        if not raw_jobs:
            return []

        identities = [
            (normalize_key(raw_job.source_platform), normalize_key(raw_job.external_id))
            for raw_job in raw_jobs
        ]
        source_platforms = sorted({source for source, _ in identities if source})
        external_ids = sorted({external_id for _, external_id in identities if external_id})

        normalized_by_identity = self._normalized_by_identity(
            source_platforms=source_platforms,
            external_ids=external_ids,
        )
        sync_state_by_normalized_id = self._latest_sync_state_by_normalized_id(
            normalized_ids={job.id for job in normalized_by_identity.values()},
        )

        seen_in_scope: set[str] = set()
        decisions: list[NormalizationEligibilityDecision] = []
        for raw_job in raw_jobs:
            source_platform = normalize_key(raw_job.source_platform)
            external_id = normalize_key(raw_job.external_id)
            payload_hash = raw_job.payload_hash

            identity_key = identity_key_from(source_platform, external_id)
            identity_hash = stable_identity_hash(identity_key)

            if identity_key is None:
                decision = EligibilityDecisionInput(
                    raw_job=raw_job,
                    reason=EligibilityDecisionReason.MISSING_IDENTITY,
                    identity_key=None,
                    identity_hash=None,
                    payload_hash=payload_hash,
                    reason_details={"reason": "source platform or external id is missing"},
                )
                decisions.append(self._upsert(decision, scrape_run_id=scrape_run_id))
                continue

            if identity_key in seen_in_scope:
                decision = EligibilityDecisionInput(
                    raw_job=raw_job,
                    reason=EligibilityDecisionReason.DUPLICATE_IN_SCRAPE_SCOPE,
                    identity_key=identity_key,
                    identity_hash=identity_hash,
                    payload_hash=payload_hash,
                )
                decisions.append(self._upsert(decision, scrape_run_id=scrape_run_id))
                continue
            seen_in_scope.add(identity_key)

            if (source_platform, external_id) in backend_existing:
                backend_hit = backend_existing[(source_platform, external_id)]
                decision = EligibilityDecisionInput(
                    raw_job=raw_job,
                    reason=EligibilityDecisionReason.EXISTING_BACKEND,
                    identity_key=identity_key,
                    identity_hash=identity_hash,
                    payload_hash=payload_hash,
                    backend_job_id=string_or_none(backend_hit.get("jobId")),
                    reason_details={"backendLookup": "match"},
                )
                decisions.append(self._upsert(decision, scrape_run_id=scrape_run_id))
                continue

            normalized = normalized_by_identity.get((source_platform, external_id))
            if normalized is None:
                decision = EligibilityDecisionInput(
                    raw_job=raw_job,
                    reason=EligibilityDecisionReason.NORMALIZATION_ELIGIBLE,
                    identity_key=identity_key,
                    identity_hash=identity_hash,
                    payload_hash=payload_hash,
                    reason_details={"backendLookup": "miss", "normalizedLookup": "miss"},
                )
                decisions.append(self._upsert(decision, scrape_run_id=scrape_run_id))
                continue

            latest_sync_state = sync_state_by_normalized_id.get(normalized.id)
            if latest_sync_state is None:
                if allow_reprocess and payload_changed(raw_job, normalized):
                    reason = EligibilityDecisionReason.REPROCESS_REQUIRED
                else:
                    reason = EligibilityDecisionReason.EXISTING_NORMALIZED_SYNCED
                decision = EligibilityDecisionInput(
                    raw_job=raw_job,
                    reason=reason,
                    identity_key=identity_key,
                    identity_hash=identity_hash,
                    payload_hash=payload_hash,
                    normalized_job_id=normalized.id,
                    normalized_sync_state=None,
                    reason_details={
                        "normalizedLookup": "match",
                        "syncState": "none",
                    },
                )
                decisions.append(self._upsert(decision, scrape_run_id=scrape_run_id))
                continue

            if latest_sync_state == "sent":
                reason = (
                    EligibilityDecisionReason.REPROCESS_REQUIRED
                    if allow_reprocess and payload_changed(raw_job, normalized)
                    else EligibilityDecisionReason.EXISTING_NORMALIZED_SYNCED
                )
            elif latest_sync_state == "failed":
                attempt_count = sync_state_attempt_count(sync_state_by_normalized_id, normalized.id)
                reason = (
                    EligibilityDecisionReason.EXISTING_NORMALIZED_UNSYNCED
                    if attempt_count < max_sync_attempts
                    else EligibilityDecisionReason.IDENTITY_CONFLICT
                )
            elif latest_sync_state in {"pending", "dead-letter"}:
                reason = EligibilityDecisionReason.EXISTING_NORMALIZED_UNSYNCED
            else:
                reason = EligibilityDecisionReason.IDENTITY_CONFLICT

            decision = EligibilityDecisionInput(
                raw_job=raw_job,
                reason=reason,
                identity_key=identity_key,
                identity_hash=identity_hash,
                payload_hash=payload_hash,
                normalized_job_id=normalized.id,
                normalized_sync_state=latest_sync_state,
                reason_details={"normalizedLookup": "match"},
            )
            decisions.append(self._upsert(decision, scrape_run_id=scrape_run_id))

        return decisions

    def _normalized_by_identity(
        self,
        *,
        source_platforms: list[str],
        external_ids: list[str],
    ) -> dict[tuple[str, str], NormalizedJob]:
        if not source_platforms or not external_ids:
            return {}
        rows = list(
            self.session.scalars(
                select(NormalizedJob).where(
                    NormalizedJob.source_platform.in_(source_platforms),
                    NormalizedJob.external_id.in_(external_ids),
                )
            ).all()
        )
        return {
            (normalize_key(row.source_platform), normalize_key(row.external_id)): row
            for row in rows
        }

    def _latest_sync_state_by_normalized_id(
        self,
        *,
        normalized_ids: set[str],
    ) -> dict[str, str]:
        if not normalized_ids:
            return {}
        rows = list(
            self.session.scalars(
                select(SyncEvent)
                .where(
                    SyncEvent.target == "backend",
                    SyncEvent.normalized_job_id.in_(normalized_ids),
                )
                .order_by(SyncEvent.attempted_at.desc(), SyncEvent.id.desc())
            ).all()
        )
        latest: dict[str, str] = {}
        for row in rows:
            if row.normalized_job_id is None:
                continue
            if row.normalized_job_id in latest:
                continue
            latest[row.normalized_job_id] = row.status
        return latest

    def _upsert(
        self,
        decision: EligibilityDecisionInput,
        *,
        scrape_run_id: str,
    ) -> NormalizationEligibilityDecision:
        existing = self.session.scalar(
            select(NormalizationEligibilityDecision).where(
                NormalizationEligibilityDecision.raw_job_id == decision.raw_job.id
            )
        )
        values = {
            "scrape_run_id": scrape_run_id,
            "raw_job_id": decision.raw_job.id,
            "source_platform": decision.raw_job.source_platform,
            "external_id": decision.raw_job.external_id,
            "identity_key": decision.identity_key,
            "identity_hash": decision.identity_hash,
            "payload_hash": decision.payload_hash,
            "decision": decision.reason.value,
            "backend_job_id": decision.backend_job_id,
            "normalized_job_id": decision.normalized_job_id,
            "normalized_sync_state": decision.normalized_sync_state,
            "reason_details": decision.reason_details or {},
        }
        if existing is None:
            record = NormalizationEligibilityDecision(**values)
            self.session.add(record)
            self.session.flush()
            return record
        for key, value in values.items():
            setattr(existing, key, value)
        self.session.flush()
        return existing


def normalize_key(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def identity_key_from(source_platform: str, external_id: str) -> str | None:
    if not source_platform or not external_id:
        return None
    return f"{source_platform}:{external_id}"


def stable_identity_hash(identity_key: str | None) -> str | None:
    if identity_key is None:
        return None
    return hashlib.sha256(identity_key.encode("utf-8")).hexdigest()


def payload_changed(raw_job: RawJob, normalized_job: NormalizedJob) -> bool:
    normalized_hash = stable_payload_hash(normalized_job.normalized_payload)
    raw_payload_hash = raw_job.payload_hash
    if raw_payload_hash is None:
        return False
    return raw_payload_hash != normalized_hash


def sync_state_attempt_count(states: dict[str, str], normalized_job_id: str) -> int:
    # attempt count is resolved in sync table lookup; state map does not retain count.
    # keep default retryable behavior for failed status.
    if states.get(normalized_job_id) == "failed":
        return 1
    return 0


def string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
