from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from modules.jobs.schemas import (
    CanonicalJobSchema,
    CompanySchema,
    LocationSchema,
    SourceMetadataSchema,
    SourcePlatform,
)
from modules.persistence import Base, JobPersistenceRepository, RawJob, RawJobInput


def test_write_job_is_idempotent_for_raw_and_normalized_records() -> None:
    with session_scope() as session:
        repository = JobPersistenceRepository(session)
        job = canonical_job("job-1", title="Backend Engineer")

        first = repository.write_job(raw_input("run-1", "job-1"), job)
        second = repository.write_job(raw_input("run-1", "job-1"), job)

        assert first.raw_created is True
        assert first.normalized_created is True
        assert second.raw_created is False
        assert second.normalized_created is False
        assert len(session.scalars(select(RawJob)).all()) == 1


def test_write_job_rolls_back_raw_insert_when_normalized_write_fails() -> None:
    with session_scope() as session:
        repository = FailingNormalizedRepository(session)

        with pytest.raises(RuntimeError):
            repository.write_job(raw_input("run-1", "job-1"), canonical_job("job-1"))

        assert session.scalars(select(RawJob)).all() == []


class FailingNormalizedRepository(JobPersistenceRepository):
    def upsert_normalized_job(self, *_args, **_kwargs):  # noqa: ANN201
        raise RuntimeError("forced normalized write failure")


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def raw_input(run_id: str, external_id: str) -> RawJobInput:
    return RawJobInput(
        scrape_run_id=run_id,
        source_platform="dealls",
        external_id=external_id,
        source_url=f"https://dealls.com/jobs/{external_id}",
        raw_payload={"id": external_id, "title": "Backend Engineer"},
        scraped_at=datetime.now(UTC),
    )


def canonical_job(external_id: str, *, title: str = "Backend Engineer") -> CanonicalJobSchema:
    now = datetime.now(UTC)
    return CanonicalJobSchema(
        source=SourceMetadataSchema(
            platform=SourcePlatform.DEALLS,
            external_job_id=external_id,
            source_url=f"https://dealls.com/jobs/{external_id}",
            scraped_at=now,
        ),
        title=title,
        company=CompanySchema(name="Bisakerja"),
        location=LocationSchema(display="Jakarta"),
        last_seen_at=now,
    )
