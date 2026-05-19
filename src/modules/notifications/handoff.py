from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from modules.persistence import (
    NormalizedJob,
    NotificationHandoffEvent,
    SyncEvent,
    stable_payload_hash,
)

DEFAULT_HANDOFF_TARGET = "backend-notifications"
SYNC_SENT_STATUS = "sent"
DEFAULT_HANDOFF_BATCH_SIZE = 1000


class HandoffStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead-letter"


@dataclass(frozen=True)
class HandoffSuccess:
    response_summary: dict[str, Any]


@dataclass(frozen=True)
class HandoffFailure:
    category: str
    message: str
    response_summary: dict[str, Any] | None = None


@dataclass(frozen=True)
class HandoffWorkerResult:
    attempted: int
    sent: int
    failed: int
    chunks_attempted: int = 0
    chunks_failed: int = 0


class HandoffClient(Protocol):
    async def send_candidates(self, payload: dict[str, Any]) -> HandoffSuccess:
        """Send recommendation candidates to backend-owned notification handling."""


class NotificationHandoffRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_synced_jobs_for_run(
        self,
        *,
        scrape_run_id: str,
        target: str = "backend",
    ) -> list[SyncEvent]:
        return list(
            self.session.scalars(
                select(SyncEvent)
                .options(selectinload(SyncEvent.normalized_job))
                .where(
                    SyncEvent.scrape_run_id == scrape_run_id,
                    SyncEvent.target == target,
                    SyncEvent.status == SYNC_SENT_STATUS,
                    SyncEvent.normalized_job_id.is_not(None),
                )
                .order_by(SyncEvent.source_platform.asc(), SyncEvent.external_id.asc())
            ).all()
        )

    def prepare_event(
        self,
        sync_event: SyncEvent,
        *,
        target: str = DEFAULT_HANDOFF_TARGET,
    ) -> NotificationHandoffEvent:
        if sync_event.scrape_run_id is None or sync_event.normalized_job_id is None:
            raise ValueError("handoff requires synced run and normalized job")
        job = require_job(sync_event.normalized_job)
        payload = candidate_payload_from(sync_event, job)
        payload_hash = stable_payload_hash(payload)
        existing = self.session.scalar(
            select(NotificationHandoffEvent).where(
                NotificationHandoffEvent.scrape_run_id == sync_event.scrape_run_id,
                NotificationHandoffEvent.source_platform == sync_event.source_platform,
                NotificationHandoffEvent.external_id == sync_event.external_id,
                NotificationHandoffEvent.target == target,
            )
        )
        if existing is not None:
            existing.sync_event_id = sync_event.id
            existing.normalized_job_id = job.id
            existing.payload_hash = payload_hash
            existing.payload_json = payload
            existing.attempted_at = utc_now()
            self.session.flush()
            return existing

        event = NotificationHandoffEvent(
            scrape_run_id=sync_event.scrape_run_id,
            normalized_job_id=job.id,
            sync_event_id=sync_event.id,
            source_platform=sync_event.source_platform,
            external_id=sync_event.external_id,
            target=target,
            status=HandoffStatus.PENDING.value,
            payload_hash=payload_hash,
            attempt_count=0,
            attempted_at=utc_now(),
            payload_json=payload,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def record_success(
        self,
        event: NotificationHandoffEvent,
        result: HandoffSuccess,
    ) -> NotificationHandoffEvent:
        event.status = HandoffStatus.SENT.value
        event.attempt_count += 1
        event.completed_at = utc_now()
        event.error_category = None
        event.error_message = None
        event.response_summary = result.response_summary
        self.session.flush()
        return event

    def record_failure(
        self,
        event: NotificationHandoffEvent,
        failure: HandoffFailure,
        *,
        max_attempts: int,
    ) -> NotificationHandoffEvent:
        event.attempt_count += 1
        event.status = (
            HandoffStatus.DEAD_LETTER.value
            if event.attempt_count >= max_attempts
            else HandoffStatus.FAILED.value
        )
        event.error_category = failure.category
        event.error_message = failure.message
        event.response_summary = failure.response_summary
        event.attempted_at = utc_now()
        event.completed_at = utc_now() if event.status == HandoffStatus.DEAD_LETTER.value else None
        self.session.flush()
        return event


class RecommendationHandoffWorker:
    def __init__(
        self,
        *,
        session: Session,
        repository: NotificationHandoffRepository,
        client: HandoffClient,
        max_attempts: int = 3,
        batch_size: int = DEFAULT_HANDOFF_BATCH_SIZE,
    ) -> None:
        self.session = session
        self.repository = repository
        self.client = client
        self.max_attempts = max_attempts
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.batch_size = batch_size

    async def handoff_synced_jobs(self, *, scrape_run_id: str) -> HandoffWorkerResult:
        sync_events = self.repository.list_synced_jobs_for_run(scrape_run_id=scrape_run_id)
        handoff_events = [self.repository.prepare_event(sync_event) for sync_event in sync_events]
        retryable_events = [
            event for event in handoff_events if is_retryable_handoff(event, self.max_attempts)
        ]
        if not retryable_events:
            return HandoffWorkerResult(attempted=0, sent=0, failed=0)

        sent = 0
        failed = 0
        chunks_attempted = 0
        chunks_failed = 0
        for chunk_events in chunks(retryable_events, self.batch_size):
            chunks_attempted += 1
            payload = {
                "runId": scrape_run_id,
                "candidates": [event.payload_json for event in chunk_events],
            }
            try:
                result = await self.client.send_candidates(payload)
            except Exception as exc:
                response_summary = getattr(exc, "response_summary", None)
                failure = HandoffFailure(
                    category=exc.__class__.__name__,
                    message=str(exc),
                    response_summary=(
                        response_summary if isinstance(response_summary, dict) else None
                    ),
                )
                for event in chunk_events:
                    self.repository.record_failure(event, failure, max_attempts=self.max_attempts)
                    failed += 1
                chunks_failed += 1
                continue

            for event in chunk_events:
                self.repository.record_success(event, result)
                sent += 1
        self.session.flush()
        return HandoffWorkerResult(
            attempted=len(retryable_events),
            sent=sent,
            failed=failed,
            chunks_attempted=chunks_attempted,
            chunks_failed=chunks_failed,
        )


def chunks(
    values: list[NotificationHandoffEvent],
    size: int,
) -> Iterable[list[NotificationHandoffEvent]]:
    if size <= 0:
        raise ValueError("chunk size must be greater than zero")
    for index in range(0, len(values), size):
        yield values[index : index + size]


def candidate_payload_from(sync_event: SyncEvent, job: NormalizedJob) -> dict[str, Any]:
    payload = job.normalized_payload
    location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    salary = payload.get("salary") if isinstance(payload.get("salary"), dict) else None
    return {
        "eventId": f"{sync_event.scrape_run_id}:{job.source_platform}:{job.external_id}",
        "syncEventId": sync_event.id,
        "sourcePlatform": job.source_platform,
        "externalJobId": job.external_id,
        "title": job.title,
        "companyName": job.company_name,
        "sourceUrl": job.source_url,
        "location": location,
        "salary": salary,
        "status": job.status,
        "lastSeenAt": job.last_seen_at.isoformat(),
    }


def require_job(job: NormalizedJob | None) -> NormalizedJob:
    if job is None:
        raise ValueError("sync event missing normalized job")
    return job


def is_retryable_handoff(event: NotificationHandoffEvent, max_attempts: int) -> bool:
    if event.status == HandoffStatus.PENDING.value:
        return True
    return event.status == HandoffStatus.FAILED.value and event.attempt_count < max_attempts


def utc_now() -> datetime:
    return datetime.now(UTC)
