from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.persistence import Base, RawJob, ScrapeRun


def test_persistence_metadata_contains_required_tables_and_constraints() -> None:
    tables = Base.metadata.tables

    assert {"scrape_runs", "raw_jobs", "normalized_jobs", "sync_events"} <= set(tables)
    assert any(
        constraint.name == "raw_jobs_source_external_id_unique"
        for constraint in tables["raw_jobs"].constraints
    )
    assert any(
        constraint.name == "normalized_jobs_source_external_id_unique"
        for constraint in tables["normalized_jobs"].constraints
    )


def test_raw_job_source_identity_is_unique() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = ScrapeRun(
            id="run-1",
            source_platform="dealls",
            stage="scrape",
            status="started",
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                RawJob(
                    id="raw-1",
                    scrape_run_id=run.id,
                    source_platform="dealls",
                    external_id="job-1",
                    raw_payload={"id": "job-1"},
                ),
                RawJob(
                    id="raw-2",
                    scrape_run_id=run.id,
                    source_platform="dealls",
                    external_id="job-1",
                    raw_payload={"id": "job-1"},
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_sqlite_schema_creation_has_expected_indexes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    indexes = {index["name"] for index in inspect(engine).get_indexes("sync_events")}

    assert "sync_events_status_attempted_at_idx" in indexes
    assert "sync_events_source_external_id_idx" in indexes
