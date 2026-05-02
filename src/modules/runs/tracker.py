from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from modules.persistence.models import ScrapeRun


class RunStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class RunStage(StrEnum):
    SCRAPE = "scrape"
    NORMALIZE = "normalize"
    ENRICH = "enrich"
    SYNC = "sync"
    PIPELINE = "pipeline"


@dataclass
class RunCounts:
    fetched: int = 0
    parsed: int = 0
    normalized: int = 0
    persisted: int = 0
    skipped: int = 0

    def model_dump(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "parsed": self.parsed,
            "normalized": self.normalized,
            "persisted": self.persisted,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class RunErrorSummary:
    source_platform: str
    category: str
    message: str
    external_id: str | None = None
    retryable: bool | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "sourcePlatform": self.source_platform,
            "category": self.category,
            "message": self.message,
            "externalId": self.external_id,
            "retryable": self.retryable,
        }


@dataclass
class RunSummary:
    counts: RunCounts = field(default_factory=RunCounts)
    errors: list[RunErrorSummary] = field(default_factory=list)
    source_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "counts": self.counts.model_dump(),
            "errors": [error.model_dump() for error in self.errors],
            "sourceCounts": self.source_counts,
        }


class RunStateTracker:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start_run(
        self,
        *,
        source_platform: str,
        stage: RunStage | str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ScrapeRun:
        values: dict[str, Any] = {
            "source_platform": source_platform,
            "stage": stage.value if isinstance(stage, RunStage) else stage,
            "status": RunStatus.STARTED.value,
            "started_at": utc_now(),
            "metadata_json": metadata or {},
        }
        if run_id is not None:
            values["id"] = run_id
        run = ScrapeRun(**values)
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def complete_run(self, run: ScrapeRun, summary: RunSummary) -> ScrapeRun:
        return self._finish(run, RunStatus.COMPLETED, summary)

    def fail_run(
        self,
        run: ScrapeRun,
        summary: RunSummary,
        *,
        error_category: str,
        error_message: str,
    ) -> ScrapeRun:
        return self._finish(
            run,
            RunStatus.FAILED,
            summary,
            error_category=error_category,
            error_message=error_message,
        )

    def partial_run(self, run: ScrapeRun, summary: RunSummary) -> ScrapeRun:
        category = summary.errors[0].category if summary.errors else None
        message = summary.errors[0].message if summary.errors else None
        return self._finish(
            run,
            RunStatus.PARTIAL,
            summary,
            error_category=category,
            error_message=message,
        )

    def update_summary(self, run: ScrapeRun, summary: RunSummary) -> ScrapeRun:
        run.raw_records_count = summary.counts.fetched
        run.normalized_records_count = summary.counts.normalized
        run.metadata_json = {**(run.metadata_json or {}), "summary": summary.model_dump()}
        self.session.commit()
        self.session.refresh(run)
        return run

    def _finish(
        self,
        run: ScrapeRun,
        status: RunStatus,
        summary: RunSummary,
        *,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> ScrapeRun:
        run.status = status.value
        run.finished_at = utc_now()
        run.raw_records_count = summary.counts.fetched
        run.normalized_records_count = summary.counts.normalized
        run.error_category = error_category
        run.error_message = error_message
        run.metadata_json = {**(run.metadata_json or {}), "summary": summary.model_dump()}
        self.session.commit()
        self.session.refresh(run)
        return run


def utc_now() -> datetime:
    return datetime.now(UTC)
