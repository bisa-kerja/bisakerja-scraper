from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tests.unit.modules.test_persistence_repositories import canonical_job, raw_input

from integrations.backend import BackendSyncClientError, BackendSyncResult, BackendSyncServerError
from modules.persistence import Base, JobPersistenceRepository, SyncEvent
from modules.sync import (
    BackendSyncWorker,
    SyncEventRepository,
    SyncEventStatus,
    SyncFailure,
    SyncSuccess,
)


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


@pytest.mark.asyncio
async def test_sync_worker_isolates_failed_chunk_and_continues() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        for external_id in ("job-1", "job-2", "job-3"):
            result = repository.write_job(
                raw_input("run-1", external_id),
                canonical_job(external_id),
            )
            result.normalized_job.status = "active"
        client = FailsFirstChunkClient()
        worker = BackendSyncWorker(
            session=session,
            client=client,
            events=SyncEventRepository(session),
            max_attempts=3,
        )

        sync_result = await worker.sync_eligible_jobs(
            scrape_run_id="run-1",
            limit=10,
            batch_size=2,
        )

        events = list(session.scalars(select(SyncEvent).order_by(SyncEvent.external_id)).all())
        assert sync_result.chunks_attempted == 2
        assert sync_result.chunks_failed == 1
        assert sync_result.sent == 1
        assert sync_result.failed == 2
        assert client.calls == [["job-3", "job-2"], ["job-1"]]
        assert [event.status for event in events] == [
            SyncEventStatus.SENT.value,
            SyncEventStatus.FAILED.value,
            SyncEventStatus.FAILED.value,
        ]
        assert all(event.metadata_json["chunkPayloadHash"] for event in events)


@pytest.mark.asyncio
async def test_sync_worker_resume_skips_sent_and_dead_letter_events() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        sent = repository.write_job(raw_input("run-1", "sent"), canonical_job("sent"))
        retryable = repository.write_job(raw_input("run-1", "retry"), canonical_job("retry"))
        dead = repository.write_job(raw_input("run-1", "dead"), canonical_job("dead"))
        for result in (sent, retryable, dead):
            result.normalized_job.status = "active"
        events = SyncEventRepository(session)
        sent_event = events.prepare_event(sent.normalized_job, scrape_run_id="run-1")
        events.record_success(sent_event, SyncSuccess({"statusCode": 202}))
        retry_event = events.prepare_event(retryable.normalized_job, scrape_run_id="run-1")
        events.record_failure(
            retry_event,
            SyncFailure(category="backend_5xx", message="retry"),
            max_attempts=3,
        )
        dead_event = events.prepare_event(dead.normalized_job, scrape_run_id="run-1")
        events.record_failure(
            dead_event,
            SyncFailure(category="backend_5xx", message="dead"),
            max_attempts=1,
        )
        client = RecordingClient()
        worker = BackendSyncWorker(session=session, client=client, events=events)

        sync_result = await worker.sync_eligible_jobs(scrape_run_id="run-2", limit=10)

        assert sync_result.attempted == 1
        assert sync_result.sent == 1
        assert client.external_ids == ["retry"]
        assert (
            retry_event.id
            == session.scalar(select(SyncEvent).where(SyncEvent.external_id == "retry")).id
        )


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


class FailsFirstChunkClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def sync_normalized_jobs(self, jobs: list[Any]) -> BackendSyncResult:
        external_ids = [job.external_id for job in jobs]
        self.calls.append(external_ids)
        if len(self.calls) == 1:
            raise BackendSyncServerError("backend unavailable", status_code=503)
        return BackendSyncResult(
            status_code=202,
            response_summary={"statusCode": 202, "statusClass": "2xx"},
        )


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
