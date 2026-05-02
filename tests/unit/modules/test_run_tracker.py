from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from modules.persistence import Base
from modules.runs import RunCounts, RunErrorSummary, RunStage, RunStateTracker
from modules.runs.tracker import RunSummary


def test_run_tracker_marks_completed_with_counts() -> None:
    with session_scope() as session:
        tracker = RunStateTracker(session)
        run = tracker.start_run(source_platform="all", stage=RunStage.PIPELINE, run_id="run-1")
        summary = RunSummary(counts=RunCounts(fetched=2, parsed=2, normalized=2, persisted=2))

        tracker.complete_run(run, summary)

        assert run.status == "completed"
        assert run.finished_at is not None
        assert run.raw_records_count == 2
        assert run.normalized_records_count == 2
        assert run.metadata_json["summary"]["counts"]["persisted"] == 2


def test_run_tracker_marks_partial_with_first_error_summary() -> None:
    with session_scope() as session:
        tracker = RunStateTracker(session)
        run = tracker.start_run(source_platform="all", stage=RunStage.PIPELINE, run_id="run-1")
        summary = RunSummary(
            counts=RunCounts(fetched=2, parsed=1, normalized=1, persisted=1, skipped=1),
            errors=[
                RunErrorSummary(
                    source_platform="glints",
                    category="FETCH_ERROR",
                    message="source unavailable",
                    retryable=True,
                )
            ],
        )

        tracker.partial_run(run, summary)

        assert run.status == "partial"
        assert run.error_category == "FETCH_ERROR"
        assert run.metadata_json["summary"]["counts"]["skipped"] == 1


def session_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
