from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select

from core.errors import NormalizeError, ScraperError
from integrations.sources.mapper_utils import SourceMapperResult
from modules.jobs import (
    AINormalizationBatchPromptInput,
    AINormalizationBatchPromptItem,
    AINormalizationPromptInput,
    CanonicalJobSchema,
    NormalizationEndpointType,
    SourcePlatform,
)
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


class AINormalizationClient(Protocol):
    async def normalize_job(self, prompt_input: AINormalizationPromptInput) -> CanonicalJobSchema:
        """Return canonical normalized job output from AI."""


SyncHook = Callable[[list[SourceMapperResult], str, str], Awaitable[None]]
StageHook = Callable[[str, str], Awaitable[RunCounts | None]]
ProgressHook = Callable[[str], None]

_DETAIL_HINT_KEYS = {
    "description",
    "responsibilities",
    "requirements",
    "qualifications",
    "content",
}


@dataclass(frozen=True)
class PipelineConfig:
    max_concurrency_per_source: int = 4
    allow_partial: bool = True
    ai_normalization_fail_open: bool = True
    ai_normalization_batch_size: int = 5
    ai_normalization_inter_batch_delay_ms: int = 0
    progress_hook: ProgressHook | None = None

    def __post_init__(self) -> None:
        if self.max_concurrency_per_source <= 0:
            raise ValueError("max_concurrency_per_source must be greater than zero")
        if self.ai_normalization_batch_size <= 0:
            raise ValueError("ai_normalization_batch_size must be greater than zero")
        if self.ai_normalization_inter_batch_delay_ms < 0:
            raise ValueError("ai_normalization_inter_batch_delay_ms must be zero or greater")


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
        ai_normalization_client: AINormalizationClient | None = None,
    ) -> None:
        self.sources = list(sources)
        self.persistence = persistence
        self.run_tracker = run_tracker
        self.config = config or PipelineConfig()
        self.sync_hook = sync_hook
        self.quarantine = quarantine
        self.stage_hooks = dict(stage_hooks or {})
        self.correlation_id_factory = correlation_id_factory or (lambda: str(uuid4()))
        self.ai_normalization_client = ai_normalization_client

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
        if self.ai_normalization_client is None:
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
        else:
            await self._normalize_source_with_ai_batch(source, raw_jobs, result)
        self.persistence.session.commit()
        result.counts.parsed = result.counts.normalized
        result.status = "failed" if result.errors else "completed"
        return result

    async def _normalize_source_with_ai_batch(
        self,
        source: PipelineSource,
        raw_jobs: Sequence[RawJob],
        result: SourcePipelineResult,
    ) -> None:
        total_batches = chunk_count(len(raw_jobs), self.config.ai_normalization_batch_size)
        for batch_index, raw_batch in enumerate(
            chunked(raw_jobs, self.config.ai_normalization_batch_size),
            start=1,
        ):
            self._emit_progress(
                "[normalize] "
                f"source={source.source_platform} "
                f"batch={batch_index}/{total_batches} size={len(raw_batch)}"
            )
            await self._normalize_batch(source, raw_batch, result)
            if (
                self.config.ai_normalization_inter_batch_delay_ms > 0
                and batch_index < total_batches
            ):
                delay_ms = self.config.ai_normalization_inter_batch_delay_ms
                self._emit_progress(
                    f"[normalize] source={source.source_platform} wait_ms={delay_ms}"
                )
                await asyncio.sleep(delay_ms / 1000)

    async def _normalize_batch(
        self,
        source: PipelineSource,
        raw_batch: Sequence[RawJob],
        result: SourcePipelineResult,
    ) -> None:
        mapped_by_item_id: dict[str, SourceMapperResult] = {}
        raw_by_item_id: dict[str, RawJob] = {}
        prompt_items: list[AINormalizationBatchPromptItem] = []

        for raw_job in raw_batch:
            item_id = raw_job.id
            try:
                mapped = source.map_raw_job(
                    raw_job_stub_from(raw_job),
                    scraped_at=raw_job.scraped_at,
                )
            except Exception as exc:
                self._record_normalize_failure(source.source_platform, raw_job, exc, result)
                continue

            prompt_input = prompt_input_from_raw_job(
                raw_job,
                source_platform=source.source_platform,
                external_id=raw_job.external_id,
            )
            if prompt_input is None:
                self.persistence.upsert_normalized_job(mapped.job, raw_job_id=raw_job.id)
                if self.quarantine is not None:
                    self.quarantine.resolve_for_raw_job(raw_job.id)
                result.counts.normalized += 1
                result.counts.persisted += 1
                continue

            mapped_by_item_id[item_id] = mapped
            raw_by_item_id[item_id] = raw_job
            prompt_items.append(
                AINormalizationBatchPromptItem(
                    item_id=item_id,
                    source_platform=prompt_input.source_platform,
                    endpoint_type=prompt_input.endpoint_type,
                    raw_payload_subset=prompt_input.raw_payload_subset,
                )
            )

        if not prompt_items:
            return

        normalize_jobs = getattr(self.ai_normalization_client, "normalize_jobs", None)
        if not callable(normalize_jobs):
            await self._normalize_batch_with_single_requests(
                source=source,
                prompt_items=prompt_items,
                mapped_by_item_id=mapped_by_item_id,
                raw_by_item_id=raw_by_item_id,
                result=result,
            )
            return

        try:
            batch_results = await normalize_jobs(
                AINormalizationBatchPromptInput(items=prompt_items)
            )
        except Exception as exc:  # noqa: BLE001
            for item_id in [item.item_id for item in prompt_items]:
                raw_job = raw_by_item_id[item_id]
                mapped = mapped_by_item_id[item_id]
                if self.config.ai_normalization_fail_open:
                    self.persistence.upsert_normalized_job(mapped.job, raw_job_id=raw_job.id)
                    if self.quarantine is not None:
                        self.quarantine.resolve_for_raw_job(raw_job.id)
                    result.counts.normalized += 1
                    result.counts.persisted += 1
                    continue
                self._record_normalize_failure(
                    source.source_platform,
                    raw_job,
                    normalize_error_from_ai_exception(
                        exc,
                        source_platform=source.source_platform,
                        external_id=raw_job.external_id,
                    ),
                    result,
                )
            return

        for item in batch_results:
            raw_job = raw_by_item_id[item.item_id]
            if item.normalized_job is None:
                if self.config.ai_normalization_fail_open:
                    mapped = mapped_by_item_id[item.item_id]
                    self.persistence.upsert_normalized_job(mapped.job, raw_job_id=raw_job.id)
                    if self.quarantine is not None:
                        self.quarantine.resolve_for_raw_job(raw_job.id)
                    result.counts.normalized += 1
                    result.counts.persisted += 1
                    continue
                self._record_normalize_failure(
                    source.source_platform,
                    raw_job,
                    normalize_error_from_batch_item(
                        source_platform=source.source_platform,
                        external_id=raw_job.external_id,
                        error_code=item.error_code,
                        error_message=item.error_message,
                    ),
                    result,
                )
                continue
            self.persistence.upsert_normalized_job(item.normalized_job, raw_job_id=raw_job.id)
            if self.quarantine is not None:
                self.quarantine.resolve_for_raw_job(raw_job.id)
            result.counts.normalized += 1
            result.counts.persisted += 1

    async def _normalize_batch_with_single_requests(
        self,
        *,
        source: PipelineSource,
        prompt_items: Sequence[AINormalizationBatchPromptItem],
        mapped_by_item_id: Mapping[str, SourceMapperResult],
        raw_by_item_id: Mapping[str, RawJob],
        result: SourcePipelineResult,
    ) -> None:
        semaphore = asyncio.Semaphore(self.config.max_concurrency_per_source)
        for item in prompt_items:
            raw_job = raw_by_item_id[item.item_id]
            mapped = mapped_by_item_id[item.item_id]
            try:
                normalized = await self._map_stored_raw_job(source, raw_job, semaphore)
            except Exception as exc:
                if self.config.ai_normalization_fail_open:
                    self.persistence.upsert_normalized_job(mapped.job, raw_job_id=raw_job.id)
                    if self.quarantine is not None:
                        self.quarantine.resolve_for_raw_job(raw_job.id)
                    result.counts.normalized += 1
                    result.counts.persisted += 1
                    continue
                self._record_normalize_failure(source.source_platform, raw_job, exc, result)
                continue

            self.persistence.upsert_normalized_job(normalized.job, raw_job_id=raw_job.id)
            if self.quarantine is not None:
                self.quarantine.resolve_for_raw_job(raw_job.id)
            result.counts.normalized += 1
            result.counts.persisted += 1

    def _record_normalize_failure(
        self,
        source_platform: str,
        raw_job: RawJob,
        exc: Exception,
        result: SourcePipelineResult,
    ) -> None:
        summary = error_summary(source_platform, exc)
        result.errors.append(summary)
        result.counts.skipped += 1
        if self.quarantine is not None:
            self.quarantine.record_raw_job_failure(
                raw_job,
                error_category=summary.category,
                error_message=summary.message,
                source_field_path=source_field_path_from(exc),
                retryable=retryable_from(exc),
            )

    def _emit_progress(self, message: str) -> None:
        if self.config.progress_hook is None:
            return
        self.config.progress_hook(message)

    async def _map_one(
        self,
        source: PipelineSource,
        raw_job: Any,
        semaphore: asyncio.Semaphore,
    ) -> SourceMapperResult:
        async with semaphore:
            mapped = source.map_raw_job(raw_job, scraped_at=utc_now())
            return await self._apply_ai_normalization(source, raw_job, mapped)

    async def _map_stored_raw_job(
        self,
        source: PipelineSource,
        raw_job: RawJob,
        semaphore: asyncio.Semaphore,
    ) -> SourceMapperResult:
        async with semaphore:
            mapped = source.map_raw_job(raw_job_stub_from(raw_job), scraped_at=raw_job.scraped_at)
            return await self._apply_ai_normalization(source, raw_job, mapped)

    async def _apply_ai_normalization(
        self,
        source: PipelineSource,
        raw_job: Any,
        mapped: SourceMapperResult,
    ) -> SourceMapperResult:
        if self.ai_normalization_client is None:
            return mapped

        external_id = external_id_from(raw_job)
        prompt_input = prompt_input_from_raw_job(
            raw_job,
            source_platform=source.source_platform,
            external_id=external_id,
        )
        if prompt_input is None:
            return mapped

        try:
            normalized_job = await self.ai_normalization_client.normalize_job(prompt_input)
        except Exception as exc:  # noqa: BLE001
            if self.config.ai_normalization_fail_open:
                return mapped
            raise normalize_error_from_ai_exception(
                exc,
                source_platform=source.source_platform,
                external_id=external_id,
            ) from exc

        provenance = dict(mapped.field_provenance)
        provenance["normalization"] = "ai"
        return SourceMapperResult(job=normalized_job, field_provenance=provenance)

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


def external_id_from(raw_job: Any) -> str | None:
    value = getattr(raw_job, "external_id", None)
    return value if isinstance(value, str) else None


def prompt_input_from_raw_job(
    raw_job: Any,
    *,
    source_platform: str,
    external_id: str | None,
) -> AINormalizationPromptInput | None:
    raw_payload = getattr(raw_job, "raw_payload", None)
    if not isinstance(raw_payload, dict) or not raw_payload:
        return None

    source_url = getattr(raw_job, "source_url", None)
    payload_subset = {
        "sourcePlatform": source_platform,
        "externalId": external_id,
        "sourceUrl": source_url if isinstance(source_url, str) else None,
        "scrapedAt": (
            raw_job.scraped_at.isoformat()
            if isinstance(getattr(raw_job, "scraped_at", None), datetime)
            else None
        ),
        "payload": raw_payload,
    }
    return AINormalizationPromptInput(
        source_platform=source_platform_enum(source_platform, external_id=external_id),
        endpoint_type=endpoint_type_from_payload(raw_payload),
        raw_payload_subset=payload_subset,
    )


def source_platform_enum(value: str, *, external_id: str | None) -> SourcePlatform:
    try:
        return SourcePlatform(value)
    except ValueError as exc:
        raise NormalizeError(
            "unsupported source platform for AI normalization",
            source_platform=value,
            external_id=external_id,
            retryable=False,
            details={"source_field_path": "source_platform"},
        ) from exc


def endpoint_type_from_payload(raw_payload: dict[str, Any]) -> NormalizationEndpointType:
    return (
        NormalizationEndpointType.DETAIL
        if has_detail_coverage(raw_payload)
        else NormalizationEndpointType.LIST
    )


def has_detail_coverage(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _DETAIL_HINT_KEYS and isinstance(item, str) and item.strip():
                return True
            if has_detail_coverage(item):
                return True
        return False
    if isinstance(value, list):
        return any(has_detail_coverage(item) for item in value)
    return False


def normalize_error_from_ai_exception(
    exc: Exception,
    *,
    source_platform: str,
    external_id: str | None,
) -> NormalizeError:
    return NormalizeError(
        "AI normalization failed",
        source_platform=source_platform,
        external_id=external_id,
        retryable=bool(getattr(exc, "retryable", False)),
        details={
            "error": str(getattr(exc, "code", exc.__class__.__name__)),
            "source_field_path": "raw_payload",
        },
    )


def normalize_error_from_batch_item(
    *,
    source_platform: str,
    external_id: str | None,
    error_code: str | None,
    error_message: str | None,
) -> NormalizeError:
    code = error_code or "NORMALIZE_PARTIAL_ERROR"
    message = error_message or "AI normalization batch returned partial error"
    return NormalizeError(
        message,
        source_platform=source_platform,
        external_id=external_id,
        retryable=False,
        details={
            "error": code,
            "source_field_path": "raw_payload",
        },
    )


def source_field_path_from(exc: Exception) -> str | None:
    if isinstance(exc, ScraperError):
        value = exc.details.get("source_field_path") or exc.details.get("field")
        return value if isinstance(value, str) else None
    return None


def retryable_from(exc: Exception) -> bool:
    if isinstance(exc, ScraperError):
        return exc.retryable
    return bool(getattr(exc, "retryable", False))


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


def chunk_count(total: int, size: int) -> int:
    if total <= 0:
        return 0
    return (total + size - 1) // size


def chunked(items: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


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
