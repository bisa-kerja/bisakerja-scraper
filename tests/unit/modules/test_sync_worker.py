from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tests.unit.modules.test_persistence_repositories import canonical_job, raw_input

from integrations.backend import BackendSyncClientError, BackendSyncResult
from modules.persistence import Base, JobPersistenceRepository, SyncEvent
from modules.sync import BackendSyncWorker, SyncEventRepository, SyncEventStatus


@pytest.mark.asyncio
async def test_sync_worker_records_4xx_as_non_retryable_failure() -> None:
    with session_scope() as session:
        result = JobPersistenceRepository(session).write_job(
            raw_input("run-1", "job-1"),
            canonical_job("job-1"),
        )
        result.normalized_job.status = "active"
        worker = BackendSyncWorker(
            session=session,
            client=RejectingClient(),
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        event = session.scalar(select(SyncEvent).where(SyncEvent.external_id == "job-1"))
        assert sync_result.failed == 1
        assert event is not None
        assert event.status == SyncEventStatus.DEAD_LETTER.value
        assert event.error_category == "backend_rejected_payload"
        assert event.attempt_count == 1


@pytest.mark.asyncio
async def test_sync_worker_only_sends_eligible_jobs() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        eligible = repository.write_job(raw_input("run-1", "eligible"), canonical_job("eligible"))
        skipped = repository.write_job(raw_input("run-1", "skipped"), canonical_job("skipped"))
        eligible.normalized_job.status = "active"
        skipped.normalized_job.status = "unknown"
        client = RecordingClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
        )

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-1", limit=10)

        assert sync_result.sent == 1
        assert client.external_ids == ["eligible"]


class RejectingClient:
    async def sync_normalized_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        raise BackendSyncClientError("validation failed", status_code=400)


class RecordingClient:
    def __init__(self) -> None:
        self.external_ids: list[str] = []

    async def sync_normalized_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        self.external_ids.extend(job.external_id for job in jobs)
        return BackendSyncResult(
            status_code=202,
            response_summary={"statusCode": 202, "statusClass": "2xx"},
        )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
