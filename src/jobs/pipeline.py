from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select

from core.errors import ScraperError
from integrations.sources.mapper_utils import SourceMapperResult
from modules.persistence import JobPersistenceRepository, RawJob, RawJobInput
from modules.quarantine import QuarantineRepository
from modules.runs import RunCounts, RunErrorSummary, RunStage, RunStateTracker
from modules.runs.tracker import RunSummary


class PipelineSource(Protocol):
    source_platform: str

    async def fetch_raw_jobs(self) -> Sequence[Any]:
        """Fetch source raw jobs."""

    def map_raw_job(self, raw_job: Any, *, scraped_at: datetime) -> SourceMapperResult:
        """Map one raw job to canonical job."""


SyncHook = Callable[[list[SourceMapperResult], str, str], Awaitable[None]]
StageHook = Callable[[str, str], Awaitable[RunCounts | None]]


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
    keyword: str | None = None
    requested_limit: int | None = None
    recency_mode: str | None = None
    recency_days: int | None = None
    newest_source_timestamp: datetime | None = None
    oldest_source_timestamp: datetime | None = None
    truncated_count: int = 0
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
        quarantine: QuarantineRepository | None = None,
        stage_hooks: Mapping[str, StageHook] | None = None,
        correlation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.sources = list(sources)
        self.persistence = persistence
        self.run_tracker = run_tracker
        self.config = config or PipelineConfig()
        self.sync_hook = sync_hook
        self.quarantine = quarantine
        self.stage_hooks = dict(stage_hooks or {})
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

    async def run_stage(
        self,
        stage: str | RunStage,
        *,
        run_id: str | None = None,
    ) -> PipelineResult:
        stage_value = stage.value if isinstance(stage, RunStage) else stage
        if stage_value == RunStage.SCRAPE.value:
            return await self.run_scrape(run_id=run_id)
        if stage_value == RunStage.NORMALIZE.value:
            return await self.run_normalize(run_id=run_id)
        if stage_value == RunStage.ENRICH.value:
            return await self.run_enrich(run_id=run_id)
        if stage_value == RunStage.SYNC.value:
            return await self.run_sync(run_id=run_id)
        if stage_value == RunStage.NOTIFY_HANDOFF.value:
            return await self.run_notify_handoff(run_id=run_id)
        raise ValueError(f"unsupported pipeline stage: {stage_value}")

    async def run_scrape(self, *, run_id: str | None = None) -> PipelineResult:
        correlation_id = self.correlation_id_factory()
        run = self.run_tracker.start_run(
            source_platform="all",
            stage=RunStage.SCRAPE,
            run_id=run_id,
            metadata={"correlationId": correlation_id},
        )
        stage_events: list[str] = []
        source_results = await asyncio.gather(
            *[self._scrape_source(source, run.id, stage_events) for source in self.sources]
        )
        return self._finish_stage_run(
            run=run,
            correlation_id=correlation_id,
            source_results=source_results,
            stage_events=stage_events,
        )

    async def run_normalize(self, *, run_id: str | None = None) -> PipelineResult:
        correlation_id = self.correlation_id_factory()
        run = self.run_tracker.start_run(
            source_platform="all",
            stage=RunStage.NORMALIZE,
            run_id=run_id,
            metadata={"correlationId": correlation_id},
        )
        stage_events: list[str] = []
        source_results: list[SourcePipelineResult] = []
        for source in unique_sources_by_platform(self.sources):
            source_results.append(await self._normalize_source(source, run.id, stage_events))
        return self._finish_stage_run(
            run=run,
            correlation_id=correlation_id,
            source_results=source_results,
            stage_events=stage_events,
        )

    async def run_enrich(self, *, run_id: str | None = None) -> PipelineResult:
        return await self._run_hook_stage(RunStage.ENRICH, run_id=run_id)

    async def run_sync(self, *, run_id: str | None = None) -> PipelineResult:
        return await self._run_hook_stage(RunStage.SYNC, run_id=run_id)

    async def run_notify_handoff(self, *, run_id: str | None = None) -> PipelineResult:
        return await self._run_hook_stage(RunStage.NOTIFY_HANDOFF, run_id=run_id)

    async def _run_source(
        self,
        source: PipelineSource,
        run_id: str,
        correlation_id: str,
        stage_events: list[str],
    ) -> SourcePipelineResult:
        result = source_pipeline_result_from(source)
        mapped_jobs: list[SourceMapperResult] = []

        try:
            stage_events.append(f"{source.source_platform}:scrape")
            fetched = sorted_by_source_timestamp(list(await source.fetch_raw_jobs()))
            result.counts.fetched = len(fetched)
            update_source_timestamp_bounds(result, fetched)

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

    async def _scrape_source(
        self,
        source: PipelineSource,
        run_id: str,
        stage_events: list[str],
    ) -> SourcePipelineResult:
        result = source_pipeline_result_from(source)
        try:
            stage_events.append(f"{source.source_platform}:scrape")
            fetched = sorted_by_source_timestamp(list(await source.fetch_raw_jobs()))
            result.counts.fetched = len(fetched)
            update_source_timestamp_bounds(result, fetched)
            for raw_job in fetched:
                self.persistence.upsert_raw_job(raw_input_from(raw_job, run_id=run_id))
                result.counts.persisted += 1
            self.persistence.session.commit()
            result.status = "completed"
            return result
        except Exception as exc:
            self.persistence.session.rollback()
            result.errors.append(error_summary(source.source_platform, exc))
            result.counts.skipped = max(result.counts.fetched - result.counts.persisted, 0)
            result.status = "failed"
            if not self.config.allow_partial:
                raise
            return result

    async def _normalize_source(
        self,
        source: PipelineSource,
        run_id: str,
        stage_events: list[str],
    ) -> SourcePipelineResult:
        result = SourcePipelineResult(source_platform=source.source_platform, status="started")
        raw_jobs_statement = select(RawJob).where(RawJob.source_platform == source.source_platform)
        scrape_run_id = scrape_run_id_for_normalize_run(run_id)
        if scrape_run_id is not None:
            raw_jobs_statement = raw_jobs_statement.where(RawJob.scrape_run_id == scrape_run_id)
        raw_jobs = list(
            self.persistence.session.scalars(
                raw_jobs_statement.order_by(RawJob.scraped_at.asc(), RawJob.id.asc())
            ).all()
        )
        result.counts.fetched = len(raw_jobs)
        stage_events.append(f"{source.source_platform}:normalize")
        semaphore = asyncio.Semaphore(self.config.max_concurrency_per_source)
        for raw_job in raw_jobs:
            try:
                mapped = await self._map_stored_raw_job(source, raw_job, semaphore)
                self.persistence.upsert_normalized_job(mapped.job, raw_job_id=raw_job.id)
                if self.quarantine is not None:
                    self.quarantine.resolve_for_raw_job(raw_job.id)
                result.counts.normalized += 1
                result.counts.persisted += 1
            except Exception as exc:
                result.errors.append(error_summary(source.source_platform, exc))
                result.counts.skipped += 1
                if self.quarantine is not None:
                    self.quarantine.record_raw_job_failure(
                        raw_job,
                        error_category=error_summary(source.source_platform, exc).category,
                        error_message=error_summary(source.source_platform, exc).message,
                        source_field_path=source_field_path_from(exc),
                        retryable=retryable_from(exc),
                    )
        self.persistence.session.commit()
        result.counts.parsed = result.counts.normalized
        result.status = "failed" if result.errors else "completed"
        return result

    async def _map_one(
        self,
        source: PipelineSource,
        raw_job: Any,
        semaphore: asyncio.Semaphore,
    ) -> SourceMapperResult:
        async with semaphore:
            return source.map_raw_job(raw_job, scraped_at=utc_now())

    async def _map_stored_raw_job(
        self,
        source: PipelineSource,
        raw_job: RawJob,
        semaphore: asyncio.Semaphore,
    ) -> SourceMapperResult:
        async with semaphore:
            return source.map_raw_job(raw_job_stub_from(raw_job), scraped_at=raw_job.scraped_at)

    async def _run_hook_stage(
        self,
        stage: RunStage,
        *,
        run_id: str | None = None,
    ) -> PipelineResult:
        correlation_id = self.correlation_id_factory()
        run = self.run_tracker.start_run(
            source_platform="all",
            stage=stage,
            run_id=run_id,
            metadata={"correlationId": correlation_id},
        )
        hook = self.stage_hooks.get(stage.value)
        summary = RunSummary()
        stage_events = [stage.value]
        try:
            if hook is not None:
                hook_counts = await hook(run.id, correlation_id)
                if hook_counts is not None:
                    summary.counts = hook_counts
            self.run_tracker.complete_run(run, summary)
            status = "completed"
        except Exception as exc:
            error = error_summary("all", exc)
            summary.errors.append(error)
            self.run_tracker.fail_run(
                run,
                summary,
                error_category=error.category,
                error_message=error.message,
            )
            status = "failed"
            if not self.config.allow_partial:
                raise
        return PipelineResult(
            run_id=run.id,
            correlation_id=correlation_id,
            status=status,
            counts=summary.counts,
            source_results=[],
            stage_events=stage_events,
        )

    def _finish_stage_run(
        self,
        *,
        run,
        correlation_id: str,
        source_results: list[SourcePipelineResult],
        stage_events: list[str],
    ) -> PipelineResult:
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
        metadata_json=raw_metadata_from(raw_job),
        scraped_at=utc_now(),
    )


def raw_job_stub_from(raw_job: RawJob) -> RawJob:
    return raw_job


def source_field_path_from(exc: Exception) -> str | None:
    if isinstance(exc, ScraperError):
        value = exc.details.get("source_field_path") or exc.details.get("field")
        return value if isinstance(value, str) else None
    return None


def retryable_from(exc: Exception) -> bool:
    return exc.retryable if isinstance(exc, ScraperError) else False


def merge_source_results(results: Sequence[SourcePipelineResult]) -> RunSummary:
    summary = RunSummary()
    for result in results:
        summary.counts.fetched += result.counts.fetched
        summary.counts.parsed += result.counts.parsed
        summary.counts.normalized += result.counts.normalized
        summary.counts.persisted += result.counts.persisted
        summary.counts.skipped += result.counts.skipped
        summary.errors.extend(result.errors)
        source_key = result.source_platform
        if result.keyword:
            source_key = f"{result.source_platform}:{result.keyword}"
        summary.source_counts[source_key] = result.counts.model_dump()
    return summary


def source_pipeline_result_from(source: PipelineSource) -> SourcePipelineResult:
    return SourcePipelineResult(
        source_platform=source.source_platform,
        status="started",
        keyword=getattr(source, "keyword", None),
        requested_limit=getattr(source, "requested_limit", None),
        recency_mode=getattr(source, "recency_mode", None),
        recency_days=getattr(source, "recency_days", None),
    )


def unique_sources_by_platform(sources: Sequence[PipelineSource]) -> list[PipelineSource]:
    selected: list[PipelineSource] = []
    seen: set[str] = set()
    for source in sources:
        if source.source_platform in seen:
            continue
        seen.add(source.source_platform)
        selected.append(source)
    return selected


def scrape_run_id_for_normalize_run(run_id: str) -> str | None:
    if run_id.endswith("-normalize"):
        return f"{run_id[: -len('-normalize')]}-scrape"
    return None


def sorted_by_source_timestamp(raw_jobs: list[Any]) -> list[Any]:
    return sorted(
        raw_jobs,
        key=lambda raw_job: source_timestamp_sort_key(getattr(raw_job, "source_timestamp", None)),
        reverse=True,
    )


def source_timestamp_sort_key(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.min.replace(tzinfo=UTC)


def update_source_timestamp_bounds(result: SourcePipelineResult, raw_jobs: Sequence[Any]) -> None:
    timestamps = [
        value
        for raw_job in raw_jobs
        if isinstance((value := getattr(raw_job, "source_timestamp", None)), datetime)
    ]
    if not timestamps:
        return
    result.newest_source_timestamp = max(timestamps)
    result.oldest_source_timestamp = min(timestamps)


def raw_metadata_from(raw_job: Any) -> dict[str, Any]:
    metadata = {
        "keyword": getattr(raw_job, "keyword", None),
        "recencyMode": getattr(raw_job, "recency_mode", None),
        "recencyDays": getattr(raw_job, "recency_days", None),
        "requestedLimit": getattr(raw_job, "requested_limit", None),
        "sourceTimestamp": serialized_datetime(getattr(raw_job, "source_timestamp", None)),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def serialized_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


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
