from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.persistence import StageJob


class StageJobType(StrEnum):
    SCRAPE_SOURCE = "scrape-source"
    NORMALIZE_RAW = "normalize-raw"
    ENRICH_BATCH = "enrich-batch"
    SYNC_BATCH = "sync-batch"
    NOTIFY_HANDOFF = "notify-handoff"


class StageJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead-letter"


@dataclass(frozen=True)
class QueueJobInput:
    job_type: StageJobType
    correlation_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    scrape_run_id: str | None = None
    normalized_job_id: str | None = None
    max_attempts: int = 3
    available_at: datetime | None = None


@dataclass(frozen=True)
class QueueFailure:
    category: str
    message: str
    retry_delay_seconds: int = 0


class StageJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, item: QueueJobInput) -> StageJob:
        if item.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job = StageJob(
            scrape_run_id=item.scrape_run_id,
            normalized_job_id=item.normalized_job_id,
            job_type=item.job_type.value,
            status=StageJobStatus.PENDING.value,
            payload_json=item.payload,
            correlation_id=item.correlation_id,
            attempt_count=0,
            max_attempts=item.max_attempts,
            available_at=item.available_at or utc_now(),
        )
        self.session.add(job)
        self.session.flush()
        return job

    def claim_next(
        self,
        *,
        job_type: StageJobType,
        now: datetime | None = None,
    ) -> StageJob | None:
        current_time = now or utc_now()
        job = self.session.scalar(
            select(StageJob)
            .where(
                StageJob.job_type == job_type.value,
                StageJob.status.in_([StageJobStatus.PENDING.value, StageJobStatus.FAILED.value]),
                StageJob.available_at <= current_time,
                StageJob.attempt_count < StageJob.max_attempts,
            )
            .order_by(StageJob.available_at.asc(), StageJob.created_at.asc())
            .limit(1)
        )
        if job is None:
            return None
        job.status = StageJobStatus.RUNNING.value
        job.locked_at = current_time
        job.error_category = None
        job.error_message = None
        self.session.flush()
        return job

    def complete(self, job: StageJob) -> StageJob:
        job.status = StageJobStatus.COMPLETED.value
        job.completed_at = utc_now()
        job.error_category = None
        job.error_message = None
        self.session.flush()
        return job

    def fail(self, job: StageJob, failure: QueueFailure) -> StageJob:
        job.attempt_count += 1
        job.error_category = failure.category
        job.error_message = failure.message[:500]
        job.locked_at = None
        if job.attempt_count >= job.max_attempts:
            job.status = StageJobStatus.DEAD_LETTER.value
            job.completed_at = utc_now()
        else:
            job.status = StageJobStatus.FAILED.value
            job.available_at = utc_now() + timedelta(seconds=failure.retry_delay_seconds)
        self.session.flush()
        return job


def utc_now() -> datetime:
    return datetime.now(UTC)
