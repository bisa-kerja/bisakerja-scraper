from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tests.unit.modules.test_persistence_repositories import canonical_job, raw_input

from modules.notifications import (
    HandoffStatus,
    HandoffSuccess,
    NotificationHandoffRepository,
    RecommendationHandoffWorker,
)
from modules.persistence import Base, JobPersistenceRepository, NotificationHandoffEvent
from modules.sync import SyncEventRepository, SyncSuccess


@pytest.mark.asyncio
async def test_handoff_only_uses_sent_sync_events() -> None:
    with session_scope() as session:
        persistence = JobPersistenceRepository(session)
        synced = persistence.write_job(raw_input("run-1", "synced"), canonical_job("synced"))
        pending = persistence.write_job(raw_input("run-1", "pending"), canonical_job("pending"))
        sync_events = SyncEventRepository(session)
        sent_event = sync_events.prepare_event(synced.normalized_job, scrape_run_id="run-1")
        sync_events.record_success(sent_event, SyncSuccess({"statusCode": 202}))
        sync_events.prepare_event(pending.normalized_job, scrape_run_id="run-1")
        client = RecordingHandoffClient()
        worker = RecommendationHandoffWorker(
            session=session,
            repository=NotificationHandoffRepository(session),
            client=client,
        )

        result = await worker.handoff_synced_jobs(scrape_run_id="run-1")

        events = list(session.scalars(select(NotificationHandoffEvent)).all())
        assert result.sent == 1
        assert len(events) == 1
        assert events[0].external_id == "synced"
        assert events[0].status == HandoffStatus.SENT.value
        assert client.payloads[0]["candidates"][0]["externalJobId"] == "synced"


@pytest.mark.asyncio
async def test_handoff_is_idempotent_by_run_source_job_target() -> None:
    with session_scope() as session:
        persistence = JobPersistenceRepository(session)
        synced = persistence.write_job(raw_input("run-1", "synced"), canonical_job("synced"))
        sync_events = SyncEventRepository(session)
        sent_event = sync_events.prepare_event(synced.normalized_job, scrape_run_id="run-1")
        sync_events.record_success(sent_event, SyncSuccess({"statusCode": 202}))
        repository = NotificationHandoffRepository(session)
        client = RecordingHandoffClient()
        worker = RecommendationHandoffWorker(
            session=session,
            repository=repository,
            client=client,
        )

        first = await worker.handoff_synced_jobs(scrape_run_id="run-1")
        second = await worker.handoff_synced_jobs(scrape_run_id="run-1")

        assert first.sent == 1
        assert second.attempted == 0
        assert len(session.scalars(select(NotificationHandoffEvent)).all()) == 1


class RecordingHandoffClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def send_candidates(self, payload: dict[str, Any]) -> HandoffSuccess:
        self.payloads.append(payload)
        return HandoffSuccess({"statusCode": 202, "statusClass": "2xx"})


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
