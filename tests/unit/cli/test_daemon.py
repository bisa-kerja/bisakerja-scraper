from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cli.daemon import run_exists, scheduled_run_id
from jobs.scheduler import ScheduledStage
from modules.persistence import Base, ScrapeRun


def test_scheduled_run_id_uses_notify_suffix() -> None:
    run_id = scheduled_run_id(
        ScheduledStage.NOTIFY_HANDOFF,
        timezone=ZoneInfo("Asia/Jakarta"),
        now=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
    )
    assert run_id == "scheduled-20260504-notify"


def test_run_exists_checks_scrape_run_id(tmp_path) -> None:
    database_path = tmp_path / "runs.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ScrapeRun(
                id="scheduled-20260504-scrape",
                source_platform="all",
                stage="scrape",
                status="completed",
            )
        )
        session.commit()
        assert run_exists(session, "scheduled-20260504-scrape") is True
        assert run_exists(session, "scheduled-20260504-sync") is False
