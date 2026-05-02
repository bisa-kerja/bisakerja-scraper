from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from modules.persistence import NormalizedJob, SyncEvent, stable_payload_hash


class SyncEventStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead-letter"


@dataclass(frozen=True)
class SyncSuccess:
    response_summary: dict[str, Any]


@dataclass(frozen=True)
class SyncFailure:
    category: str
    message: str
    response_summary: dict[str, Any] | None = None


class SyncEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_resume_candidates(
        self,
        *,
        eligible_statuses: set[str],
        limit: int,
        max_attempts: int,
        target: str = "backend",
    ) -> list[NormalizedJob]:
        jobs = list(
            self.session.scalars(
                select(NormalizedJob)
                .options(
                    selectinload(NormalizedJob.skills_staging),
                    selectinload(NormalizedJob.requirements_staging),
                )
                .where(NormalizedJob.status.in_(eligible_statuses))
                .order_by(NormalizedJob.last_seen_at.desc(), NormalizedJob.id.asc())
            ).all()
        )
        candidates: list[NormalizedJob] = []
        for job in jobs:
            event = self.find_event(job, target=target)
            if event is None or is_retryable_event(event, max_attempts=max_attempts):
                candidates.append(job)
            if len(candidates) >= limit:
                break
        return candidates

    def find_event(self, job: NormalizedJob, *, target: str = "backend") -> SyncEvent | None:
        payload_hash = stable_payload_hash(job.normalized_payload)
        return self.session.scalar(
            select(SyncEvent).where(
                SyncEvent.target == target,
                SyncEvent.normalized_job_id == job.id,
                SyncEvent.payload_hash == payload_hash,
            )
        )

    def prepare_event(
        self,
        job: NormalizedJob,
        *,
        scrape_run_id: str | None,
        target: str = "backend",
    ) -> SyncEvent:
        payload_hash = stable_payload_hash(job.normalized_payload)
        existing = self.find_event(job, target=target)
        if existing is not None:
            existing.scrape_run_id = scrape_run_id
            existing.attempted_at = utc_now()
            self.session.flush()
            return existing

        event = SyncEvent(
            scrape_run_id=scrape_run_id,
            normalized_job_id=job.id,
            source_platform=job.source_platform,
            external_id=job.external_id,
            status=SyncEventStatus.PENDING.value,
            target=target,
            payload_hash=payload_hash,
            attempt_count=0,
            attempted_at=utc_now(),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def attach_chunk_metadata(
        self,
        event: SyncEvent,
        *,
        chunk_id: str,
        chunk_payload_hash: str,
        chunk_size: int,
    ) -> SyncEvent:
        event.metadata_json = {
            **(event.metadata_json or {}),
            "chunkId": chunk_id,
            "chunkPayloadHash": chunk_payload_hash,
            "chunkSize": chunk_size,
        }
        self.session.flush()
        return event

    def record_success(self, event: SyncEvent, result: SyncSuccess) -> SyncEvent:
        event.status = SyncEventStatus.SENT.value
        event.attempt_count += 1
        event.completed_at = utc_now()
        event.error_category = None
        event.error_message = None
        event.response_summary = result.response_summary
        self.session.flush()
        return event

    def record_failure(
        self,
        event: SyncEvent,
        failure: SyncFailure,
        *,
        max_attempts: int,
    ) -> SyncEvent:
        event.attempt_count += 1
        event.status = (
            SyncEventStatus.DEAD_LETTER.value
            if event.attempt_count >= max_attempts
            else SyncEventStatus.FAILED.value
        )
        event.error_category = failure.category
        event.error_message = failure.message
        event.response_summary = failure.response_summary
        event.attempted_at = utc_now()
        event.completed_at = (
            utc_now() if event.status == SyncEventStatus.DEAD_LETTER.value else None
        )
        self.session.flush()
        return event


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_retryable_event(event: SyncEvent, *, max_attempts: int) -> bool:
    if event.status == SyncEventStatus.PENDING.value:
        return True
    return event.status == SyncEventStatus.FAILED.value and event.attempt_count < max_attempts
