from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from core.errors import ScraperError
from integrations.sources.mapper_utils import SourceMapperResult
from modules.persistence import JobPersistenceRepository, RawJobInput
from modules.runs import RunCounts, RunErrorSummary, RunStage, RunStateTracker
from modules.runs.tracker import RunSummary


class PipelineSource(Protocol):
    source_platform: str

    async def fetch_raw_jobs(self) -> Sequence[Any]:
        """Fetch source raw jobs."""

    def map_raw_job(self, raw_job: Any, *, scraped_at: datetime) -> SourceMapperResult:
        """Map one raw job to canonical job."""


SyncHook = Callable[[list[SourceMapperResult], str, str], Awaitable[None]]


@dataclass(frozen=True)
class PipelineConfig:
    max_concurrency_per_source: int = 4
    allow_partial: bool = True

    def __post_init__(self) -> None:
        if self.max_concurrency_per_source <= 0:
            raise ValueError("max_concurrency_per_source must be greater than zero")


@dataclass
class SourcePipelineResult:
    source_platform: str
    status: str
    counts: RunCounts = field(default_factory=RunCounts)
    errors: list[RunErrorSummary] = field(default_factory=list)


@dataclass
class PipelineResult:
    run_id: str
    correlation_id: str
    status: str
    counts: RunCounts
    source_results: list[SourcePipelineResult]
    stage_events: list[str]


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        sources: Sequence[PipelineSource],
        persistence: JobPersistenceRepository,
        run_tracker: RunStateTracker,
        config: PipelineConfig | None = None,
        sync_hook: SyncHook | None = None,
        correlation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.sources = list(sources)
        self.persistence = persistence
        self.run_tracker = run_tracker
        self.config = config or PipelineConfig()
        self.sync_hook = sync_hook
        self.correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))

    async def run(self, *, run_id: str | None = None) -> PipelineResult:
        correlation_id = self.correlation_id_factory()
        run = self.run_tracker.start_run(
            source_platform="all",
            stage=RunStage.PIPELINE,
            run_id=run_id,
            metadata={"correlationId": correlation_id},
        )
        stage_events: list[str] = []

        try:
            source_results = await asyncio.gather(
                *[
                    self._run_source(source, run.id, correlation_id, stage_events)
                    for source in self.sources
                ]
            )
        except Exception as exc:
            summary = RunSummary()
            error = error_summary("all", exc)
            summary.errors.append(error)
            self.run_tracker.fail_run(
                run,
                summary,
                error_category=error.category,
                error_message=error.message,
            )
            raise

        summary = merge_source_results(source_results)
        if summary.errors:
            self.run_tracker.partial_run(run, summary)
            status = "partial"
        else:
            self.run_tracker.complete_run(run, summary)
            status = "completed"

        return PipelineResult(
            run_id=run.id,
            correlation_id=correlation_id,
            status=status,
            counts=summary.counts,
            source_results=source_results,
            stage_events=stage_events,
        )

    async def _run_source(
        self,
        source: PipelineSource,
        run_id: str,
        correlation_id: str,
        stage_events: list[str],
    ) -> SourcePipelineResult:
        result = SourcePipelineResult(source_platform=source.source_platform, status="started")
        mapped_jobs: list[SourceMapperResult] = []

        try:
            stage_events.append(f"{source.source_platform}:scrape")
            fetched = list(await source.fetch_raw_jobs())
            result.counts.fetched = len(fetched)

            stage_events.append(f"{source.source_platform}:normalize")
            semaphore = asyncio.Semaphore(self.config.max_concurrency_per_source)
            mapped_jobs = await asyncio.gather(
                *[self._map_one(source, raw_job, semaphore) for raw_job in fetched]
            )
            result.counts.parsed = len(fetched)
            result.counts.normalized = len(mapped_jobs)

            stage_events.append(f"{source.source_platform}:enrich")
            mapped_jobs = await maybe_enrich_mapped_jobs(source, mapped_jobs)

            for raw_job, mapped in zip(fetched, mapped_jobs, strict=True):
                raw_input = raw_input_from(raw_job, run_id=run_id)
                self.persistence.write_job(raw_input, mapped.job)
                result.counts.persisted += 1

            stage_events.append(f"{source.source_platform}:sync")
            if self.sync_hook is not None:
                await self.sync_hook(mapped_jobs, run_id, correlation_id)

            result.status = "completed"
            return result
        except Exception as exc:
            result.errors.append(error_summary(source.source_platform, exc))
            result.counts.skipped = max(result.counts.fetched - result.counts.persisted, 0)
            result.status = "failed"
            if not self.config.allow_partial:
                raise
            return result

    async def _map_one(
        self,
        source: PipelineSource,
        raw_job: Any,
        semaphore: asyncio.Semaphore,
    ) -> SourceMapperResult:
        async with semaphore:
            return source.map_raw_job(raw_job, scraped_at=utc_now())


async def maybe_enrich_mapped_jobs(
    source: PipelineSource,
    mapped_jobs: list[SourceMapperResult],
) -> list[SourceMapperResult]:
    enrich = getattr(source, "enrich_mapped_jobs", None)
    if enrich is None:
        return mapped_jobs
    return await enrich(mapped_jobs)


def raw_input_from(raw_job: Any, *, run_id: str) -> RawJobInput:
    return RawJobInput(
        scrape_run_id=run_id,
        source_platform=raw_job.source_platform,
        external_id=raw_job.external_id,
        source_url=getattr(raw_job, "source_url", None),
        raw_payload=raw_job.raw_payload,
        scraped_at=utc_now(),
    )


def merge_source_results(results: Sequence[SourcePipelineResult]) -> RunSummary:
    summary = RunSummary()
    for result in results:
        summary.counts.fetched += result.counts.fetched
        summary.counts.parsed += result.counts.parsed
        summary.counts.normalized += result.counts.normalized
        summary.counts.persisted += result.counts.persisted
        summary.counts.skipped += result.counts.skipped
        summary.errors.extend(result.errors)
        summary.source_counts[result.source_platform] = result.counts.model_dump()
    return summary


def error_summary(source_platform: str, exc: Exception) -> RunErrorSummary:
    if isinstance(exc, ScraperError):
        return RunErrorSummary(
            source_platform=source_platform,
            category=exc.code,
            message=exc.message,
            external_id=exc.external_id,
            retryable=exc.retryable,
        )
    return RunErrorSummary(
        source_platform=source_platform,
        category=exc.__class__.__name__,
        message=str(exc),
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
