from __future__ import annotations

import asyncio

import pytest

from jobs.scheduler import DailyPipelineScheduler, ScheduledStage, SchedulerConfig


def test_scheduler_registers_daily_stage_jobs() -> None:
    runner = RecordingRunner()
    scheduler = DailyPipelineScheduler(
        config=SchedulerConfig(
            scrape_cron="0 0 * * *",
            normalize_cron="0 2 * * *",
            enrich_cron="0 4 * * *",
            sync_cron="0 6 * * *",
            notify_handoff_cron="0 8 * * *",
        ),
        runner=runner,
    )

    scheduler.configure_jobs()

    jobs = {job.id: job for job in scheduler.scheduler.get_jobs()}
    assert set(jobs) == {
        "scrape-daily",
        "normalize-daily",
        "enrich-daily",
        "sync-daily",
        "notify-handoff-daily",
    }
    assert jobs["scrape-daily"].max_instances == 1
    assert jobs["scrape-daily"].coalesce is True


@pytest.mark.asyncio
async def test_scheduler_rejects_overlapping_manual_trigger() -> None:
    runner = BlockingRunner()
    scheduler = DailyPipelineScheduler(
        config=SchedulerConfig(
            scrape_cron="0 0 * * *",
            normalize_cron="0 2 * * *",
            enrich_cron="0 4 * * *",
            sync_cron="0 6 * * *",
            notify_handoff_cron="0 8 * * *",
        ),
        runner=runner,
    )

    first = asyncio.create_task(scheduler.trigger_stage(ScheduledStage.SCRAPE))
    await runner.started.wait()

    second = await scheduler.trigger_stage(ScheduledStage.SYNC)
    runner.release.set()
    first_result = await first

    assert first_result.accepted is True
    assert second.accepted is False
    assert second.reason == "run already active"
    assert runner.stages == [ScheduledStage.SCRAPE]


class RecordingRunner:
    def __init__(self) -> None:
        self.stages: list[ScheduledStage] = []

    async def run_stage(self, stage: ScheduledStage) -> None:
        self.stages.append(stage)


class BlockingRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_stage(self, stage: ScheduledStage) -> None:
        self.stages.append(stage)
        self.started.set()
        await self.release.wait()
