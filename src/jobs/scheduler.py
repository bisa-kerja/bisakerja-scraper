from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings


class ScheduledStage(StrEnum):
    SCRAPE = "scrape"
    NORMALIZE = "normalize"
    ENRICH = "enrich"
    SYNC = "sync"
    NOTIFY_HANDOFF = "notify-handoff"


class StageRunner(Protocol):
    async def run_stage(self, stage: ScheduledStage) -> None:
        """Run one scheduled stage."""


StageCallable = Callable[[ScheduledStage], Awaitable[None]]


@dataclass(frozen=True)
class ScheduledRunResult:
    stage: ScheduledStage
    accepted: bool
    reason: str | None = None


@dataclass(frozen=True)
class SchedulerConfig:
    scrape_cron: str
    normalize_cron: str
    enrich_cron: str
    sync_cron: str
    notify_handoff_cron: str
    timezone: str = "Asia/Jakarta"

    @classmethod
    def from_settings(cls, settings: Settings) -> SchedulerConfig:
        return cls(
            scrape_cron=settings.scrape_schedule_cron,
            normalize_cron=settings.normalize_schedule_cron,
            enrich_cron=settings.enrich_schedule_cron,
            sync_cron=settings.sync_schedule_cron,
            notify_handoff_cron=settings.notify_handoff_schedule_cron,
        )

    def cron_by_stage(self) -> Mapping[ScheduledStage, str]:
        return {
            ScheduledStage.SCRAPE: self.scrape_cron,
            ScheduledStage.NORMALIZE: self.normalize_cron,
            ScheduledStage.ENRICH: self.enrich_cron,
            ScheduledStage.SYNC: self.sync_cron,
            ScheduledStage.NOTIFY_HANDOFF: self.notify_handoff_cron,
        }


class ManualTriggerGuard:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_stage: ScheduledStage | None = None

    @property
    def active_stage(self) -> ScheduledStage | None:
        return self._active_stage

    async def run(self, stage: ScheduledStage, callback: StageCallable) -> ScheduledRunResult:
        if self._lock.locked():
            return ScheduledRunResult(stage=stage, accepted=False, reason="run already active")

        async with self._lock:
            self._active_stage = stage
            try:
                await callback(stage)
            finally:
                self._active_stage = None

        return ScheduledRunResult(stage=stage, accepted=True)


class DailyPipelineScheduler:
    def __init__(
        self,
        *,
        config: SchedulerConfig,
        runner: StageRunner,
        scheduler: AsyncIOScheduler | None = None,
        guard: ManualTriggerGuard | None = None,
    ) -> None:
        self.config = config
        self.runner = runner
        self.guard = guard or ManualTriggerGuard()
        timezone = ZoneInfo(config.timezone)
        self.scheduler = scheduler or AsyncIOScheduler(timezone=timezone)

    def configure_jobs(self) -> None:
        for stage, cron in self.config.cron_by_stage().items():
            self.scheduler.add_job(
                self.trigger_stage,
                trigger=CronTrigger.from_crontab(cron, timezone=ZoneInfo(self.config.timezone)),
                args=[stage],
                id=f"{stage.value}-daily",
                name=f"{stage.value} daily pipeline stage",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )

    def start(self, *, paused: bool = False) -> None:
        if not self.scheduler.get_jobs():
            self.configure_jobs()
        self.scheduler.start(paused=paused)

    def shutdown(self, *, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

    async def trigger_stage(self, stage: ScheduledStage) -> ScheduledRunResult:
        return await self.guard.run(stage, self.runner.run_stage)


__all__ = [
    "DailyPipelineScheduler",
    "ManualTriggerGuard",
    "ScheduledRunResult",
    "ScheduledStage",
    "SchedulerConfig",
    "StageRunner",
]
