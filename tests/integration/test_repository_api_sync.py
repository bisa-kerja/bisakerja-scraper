from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api.app import create_app
from integrations.backend import BackendSyncClient
from modules.persistence import JobPersistenceRepository, NormalizedJob, RawJob, RawJobInput
from tests.integration.helpers import canonical_job, make_settings, migrated_sqlite_engine


def test_repository_upsert_uses_migrated_isolated_database(tmp_path) -> None:
    engine = migrated_sqlite_engine(tmp_path / "repository.sqlite")
    factory = sessionmaker(bind=engine)

    with factory() as session:
        seed_scrape_run(session)
        repository = JobPersistenceRepository(session)
        job = canonical_job("job-1", title="Backend Engineer")
        raw_input = RawJobInput(
            scrape_run_id="run-1",
            source_platform="dealls",
            external_id="job-1",
            source_url="https://dealls.com/jobs/job-1",
            raw_payload={"id": "job-1", "title": "Backend Engineer"},
        )

        first = repository.write_job(raw_input, job)
        second = repository.write_job(raw_input, canonical_job("job-1", title="Senior Engineer"))
        session.commit()

        normalized = session.scalar(
            select(NormalizedJob).where(NormalizedJob.external_id == "job-1")
        )

    assert first.raw_created is True
    assert first.normalized_created is True
    assert second.raw_created is False
    assert second.normalized_created is False
    assert normalized is not None
    assert normalized.title == "Senior Engineer"


def test_api_route_reads_from_migrated_isolated_database(tmp_path) -> None:
    engine = migrated_sqlite_engine(tmp_path / "api.sqlite")
    factory = sessionmaker(bind=engine)

    with factory() as session:
        seed_scrape_run(session)
        repository = JobPersistenceRepository(session)
        repository.write_job(
            RawJobInput(
                scrape_run_id="run-1",
                source_platform="dealls",
                external_id="job-1",
                source_url="https://dealls.com/jobs/job-1",
                raw_payload={"id": "job-1", "title": "Backend Engineer"},
            ),
            canonical_job("job-1"),
        )
        session.commit()

    def app_session_factory() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app(
        settings=make_settings(),
        readiness_check=noop_readiness,
        job_session_factory=app_session_factory,
    )
    client = TestClient(app)

    response = client.get("/api/v1/jobs", headers={"authorization": "Bearer test-service-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"][0]["externalJobId"] == "job-1"
    assert body["meta"]["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_sync_client_integration_uses_internal_contract_without_external_network() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json={"success": True, "message": "Accepted"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BackendSyncClient(
        base_url="https://backend.example",
        service_token="test-service-token",
        timeout_seconds=5,
        max_retries=0,
        client=http_client,
    )

    result = await client.sync_jobs([{"externalJobId": "job-1"}])
    await http_client.aclose()

    assert result.status_code == 202
    assert result.response_summary["message"] == "Accepted"
    assert requests[0].headers["authorization"] == "Bearer test-service-token"
    assert requests[0].url.path == "/api/v1/internal/scraper/jobs"


def seed_scrape_run(session: Session) -> None:
    session.execute(
        RawJob.__table__.metadata.tables["scrape_runs"]
        .insert()
        .values(
            id="run-1",
            source_platform="dealls",
            stage="scrape",
            status="completed",
            raw_records_count=0,
            normalized_records_count=0,
        )
    )
    session.commit()


async def noop_readiness() -> None:
    return None
