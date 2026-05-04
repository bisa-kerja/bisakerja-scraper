from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cli.pipeline import DEFAULT_FIXTURE_ROOT, ManualPipelineRunner, build_engine, load_settings
from config.logging import configure_logging
from config.settings import Settings
from jobs.scheduler import DailyPipelineScheduler, ScheduledStage, SchedulerConfig
from modules.persistence import ScrapeRun


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    asyncio.run(run_daemon(args))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper-daemon")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    parser.add_argument("--run-on-start", action="store_true")
    return parser


async def run_daemon(args: argparse.Namespace) -> None:
    settings = load_settings(args.env_file)
    configure_logging(
        service=settings.app_name,
        env=settings.app_env,
        level=settings.log_level,
    )
    logger = structlog.get_logger(__name__)
    config = SchedulerConfig.from_settings(settings)
    runner = DeploymentStageRunner(
        settings=settings,
        timezone=ZoneInfo(config.timezone),
        fixture_root=Path(args.fixture_root),
    )
    scheduler = DailyPipelineScheduler(config=config, runner=runner)
    scheduler.start()
    logger.info(
        "scheduler_started",
        timezone=config.timezone,
        cronByStage={stage.value: cron for stage, cron in config.cron_by_stage().items()},
    )

    if args.run_on_start:
        await scheduler.trigger_stage(ScheduledStage.SCRAPE)
        await scheduler.trigger_stage(ScheduledStage.NORMALIZE)
        await scheduler.trigger_stage(ScheduledStage.ENRICH)
        await scheduler.trigger_stage(ScheduledStage.SYNC)
        await scheduler.trigger_stage(ScheduledStage.NOTIFY_HANDOFF)

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)


class DeploymentStageRunner:
    def __init__(self, *, settings: Settings, timezone: ZoneInfo, fixture_root: Path) -> None:
        self.settings = settings
        self.timezone = timezone
        self.fixture_root = fixture_root
        self.logger = structlog.get_logger(__name__)

    async def run_stage(self, stage: ScheduledStage) -> None:
        run_id = scheduled_run_id(stage, timezone=self.timezone)
        engine = build_engine(self.settings.scraper_database_url, execute=True)
        factory = sessionmaker(bind=engine)
        try:
            with factory() as session:
                if run_exists(session, run_id):
                    self.logger.info(
                        "scheduler_stage_skipped_existing_run",
                        stage=stage.value,
                        runId=run_id,
                    )
                    return
                runner = ManualPipelineRunner(
                    session=session,
                    settings=self.settings,
                    stage=stage.value,
                    source="all",
                    keywords=self.settings.scraper_keywords,
                    fixture_root=self.fixture_root,
                    limit=self.settings.scraper_max_items_per_keyword,
                    recency_mode=self.settings.scraper_recency_mode.value,
                    recency_days=self.settings.scraper_recency_days,
                    execute=True,
                    run_id=run_id,
                )
                await runner.run_stage(stage)
                self.logger.info(
                    "scheduler_stage_completed",
                    stage=stage.value,
                    runId=run_id,
                    output=runner.output,
                )
        finally:
            engine.dispose()


def run_exists(session, run_id: str) -> bool:
    return session.scalar(select(ScrapeRun.id).where(ScrapeRun.id == run_id)) is not None


def scheduled_run_id(
    stage: ScheduledStage,
    *,
    timezone: ZoneInfo,
    now: datetime | None = None,
) -> str:
    suffix = "notify" if stage is ScheduledStage.NOTIFY_HANDOFF else stage.value
    current = now.astimezone(timezone) if now is not None else datetime.now(timezone)
    stamp = current.strftime("%Y%m%d")
    return f"scheduled-{stamp}-{suffix}"


if __name__ == "__main__":
    raise SystemExit(main())
