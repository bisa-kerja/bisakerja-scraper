from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings
from integrations.backend import BackendSyncResult
from integrations.sources.dealls.list import (
    DeallsListAdapter,
    DeallsListQuery,
    build_dealls_http_client,
    extract_dealls_source_timestamp,
)
from integrations.sources.dealls.list import (
    RawSourceJob as DeallsRawSourceJob,
)
from integrations.sources.dealls.mapper import map_dealls_job
from integrations.sources.glints.list import (
    GlintsListAdapter,
    GlintsListQuery,
    build_glints_http_client,
    extract_glints_source_timestamp,
)
from integrations.sources.glints.list import (
    RawSourceJob as GlintsRawSourceJob,
)
from integrations.sources.glints.mapper import map_glints_job
from integrations.sources.jobstreet.list import (
    JobStreetListQuery,
    build_jobstreet_http_client,
    extract_jobstreet_source_timestamp,
    parse_jobstreet_list_payload,
)
from integrations.sources.jobstreet.list import (
    RawSourceJob as JobStreetRawSourceJob,
)
from integrations.sources.jobstreet.mapper import map_jobstreet_job
from integrations.sources.kalibrr.build_id import KalibrrBuildIdResolver
from integrations.sources.kalibrr.list import (
    KalibrrListAdapter,
    KalibrrListQuery,
    build_kalibrr_http_client,
    extract_kalibrr_source_timestamp,
)
from integrations.sources.kalibrr.list import (
    RawSourceJob as KalibrrRawSourceJob,
)
from integrations.sources.kalibrr.mapper import map_kalibrr_job
from integrations.sources.mapper_utils import SourceMapperResult
from jobs.pipeline import PipelineOrchestrator, PipelineResult
from jobs.scheduler import ManualTriggerGuard, ScheduledStage
from modules.enrichment.repositories import EnrichmentSource, EnrichmentStagingRepository
from modules.enrichment.schemas import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentOutput,
    RequirementType,
)
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CanonicalJobStatus,
    CompanySchema,
    LocationSchema,
    SourceMetadataSchema,
    SourcePlatform,
)
from modules.notifications import HandoffSuccess, NotificationHandoffRepository
from modules.notifications.handoff import RecommendationHandoffWorker
from modules.persistence import (
    Base,
    JobPersistenceRepository,
    NormalizedJob,
    NotificationHandoffEvent,
    RawJob,
    ScrapeRun,
    SyncEvent,
)
from modules.runs import RunCounts, RunStage, RunStateTracker
from modules.sync import BackendSyncWorker, SyncEventRepository

SOURCE_CHOICES = ("all", "dealls", "glints", "jobstreet", "kalibrr")
STAGE_CHOICES = ("full", "scrape", "normalize", "enrich", "sync", "notify-handoff")
DEFAULT_FIXTURE_ROOT = Path("tests/fixtures/raw")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(args.command_handler(args))
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper-pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--stage", choices=STAGE_CHOICES, default="full")
    run_parser.add_argument("--source", choices=SOURCE_CHOICES, default="all")
    run_parser.add_argument("--limit", type=positive_int, default=None)
    run_parser.add_argument("--keyword", action="append", default=None)
    run_parser.add_argument("--keywords", default=None)
    run_parser.add_argument("--latest", action="store_true")
    run_parser.add_argument("--recency-days", type=recency_days, default=None)
    run_parser.add_argument("--env-file", default=None)
    run_parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    run_parser.add_argument("--run-id", default=None)
    run_parser.add_argument("--execute", action="store_true")
    run_parser.set_defaults(command_handler=run_pipeline)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-id", required=True)
    status_parser.add_argument("--env-file", default=None)
    status_parser.add_argument("--database-url", default=None)
    status_parser.set_defaults(command_handler=run_status)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--run-id", required=True)
    verify_parser.add_argument("--env-file", default=None)
    verify_parser.add_argument("--database-url", default=None)
    verify_parser.set_defaults(command_handler=run_verify)
    return parser


async def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    keywords = resolve_keywords(args, settings)
    limit = args.limit or settings.scraper_max_items_per_keyword
    recency_mode = "latest" if args.latest else settings.scraper_recency_mode.value
    recency_days_value = args.recency_days or settings.scraper_recency_days
    engine = build_engine(settings.scraper_database_url, execute=args.execute)
    if not args.execute:
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    guard = ManualTriggerGuard()
    with factory() as session:
        runner = ManualPipelineRunner(
            session=session,
            settings=settings,
            stage=args.stage,
            source=args.source,
            keywords=keywords,
            fixture_root=Path(args.fixture_root),
            limit=limit,
            recency_mode=recency_mode,
            recency_days=recency_days_value,
            execute=args.execute,
            run_id=args.run_id,
        )
        result = await guard.run(stage_for_guard(args.stage), runner.run_stage)
        if not result.accepted:
            return {
                "check": "pipeline-run",
                "status": "fail",
                "reason": result.reason,
                "stage": args.stage,
            }
        return runner.output or {
            "check": "pipeline-run",
            "status": "fail",
            "reason": "pipeline produced no output",
            "stage": args.stage,
        }


async def run_status(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    database_url = args.database_url or settings.scraper_database_url
    engine = create_engine(to_sync_url(database_url), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            run = session.scalar(select(ScrapeRun).where(ScrapeRun.id == args.run_id))
            if run is None:
                return {
                    "check": "pipeline-status",
                    "status": "fail",
                    "reason": "run not found",
                    "runId": args.run_id,
                }
            return {
                "check": "pipeline-status",
                "status": "ok",
                "runId": run.id,
                "runStatus": run.status,
                "stage": run.stage,
                "sourcePlatform": run.source_platform,
                "counts": {
                    "raw": run.raw_records_count,
                    "normalized": run.normalized_records_count,
                },
                "errorCategory": run.error_category,
            }
    finally:
        engine.dispose()


async def run_verify(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    database_url = args.database_url or settings.scraper_database_url
    engine = create_engine(to_sync_url(database_url), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            return verify_database_state(session, run_id=args.run_id)
    finally:
        engine.dispose()


def verify_database_state(session: Session, *, run_id: str) -> dict[str, Any]:
    run_ids = stage_run_ids(run_id)
    runs = list(
        session.scalars(
            select(ScrapeRun)
            .where(ScrapeRun.id.in_(run_ids))
            .order_by(ScrapeRun.started_at.asc(), ScrapeRun.id.asc())
        ).all()
    )
    raw_jobs = list(
        session.scalars(
            select(RawJob)
            .where(RawJob.scrape_run_id.in_(run_ids))
            .order_by(RawJob.source_platform.asc(), RawJob.external_id.asc())
        ).all()
    )
    raw_job_ids = [job.id for job in raw_jobs]
    normalized_jobs = []
    if raw_job_ids:
        normalized_jobs = list(
            session.scalars(
                select(NormalizedJob).where(NormalizedJob.raw_job_id.in_(raw_job_ids))
            ).all()
        )
    sync_events = list(
        session.scalars(select(SyncEvent).where(SyncEvent.scrape_run_id.in_(run_ids))).all()
    )
    handoff_events = list(
        session.scalars(
            select(NotificationHandoffEvent).where(
                NotificationHandoffEvent.scrape_run_id.in_(run_ids)
            )
        ).all()
    )
    raw_identity_counts = Counter((job.source_platform, job.external_id) for job in raw_jobs)
    normalized_identity_counts = Counter(
        (job.source_platform, job.external_id) for job in normalized_jobs
    )
    raw_source_keyword_counts = Counter(
        (
            job.source_platform,
            metadata_value(job.metadata_json, "keyword") or "unknown",
        )
        for job in raw_jobs
    )
    raw_source_counts = Counter(job.source_platform for job in raw_jobs)
    normalized_source_counts = Counter(job.source_platform for job in normalized_jobs)
    sync_status_counts = Counter(event.status for event in sync_events)
    handoff_status_counts = Counter(event.status for event in handoff_events)

    return {
        "check": "pipeline-verify",
        "status": "ok" if runs else "fail",
        "runId": run_id,
        "stageRunIds": run_ids,
        "runs": [
            {
                "runId": run.id,
                "stage": run.stage,
                "status": run.status,
                "raw": run.raw_records_count,
                "normalized": run.normalized_records_count,
                "errorCategory": run.error_category,
            }
            for run in runs
        ],
        "rawRows": len(raw_jobs),
        "normalizedRows": len(normalized_jobs),
        "syncEvents": len(sync_events),
        "handoffEvents": len(handoff_events),
        "rawBySource": dict(sorted(raw_source_counts.items())),
        "normalizedBySource": dict(sorted(normalized_source_counts.items())),
        "rawBySourceKeyword": {
            f"{source}:{keyword}": count
            for (source, keyword), count in sorted(raw_source_keyword_counts.items())
        },
        "syncByStatus": dict(sorted(sync_status_counts.items())),
        "handoffByStatus": dict(sorted(handoff_status_counts.items())),
        "duplicateRawIdentities": duplicate_count(raw_identity_counts),
        "duplicateNormalizedIdentities": duplicate_count(normalized_identity_counts),
        "latestMetadata": latest_metadata_summary(raw_jobs),
    }


def stage_run_ids(run_id: str) -> list[str]:
    suffixes = ("scrape", "normalize", "enrich", "sync", "notify")
    if any(run_id.endswith(f"-{suffix}") for suffix in suffixes):
        base_run_id = run_id.rsplit("-", 1)[0]
        return [f"{base_run_id}-{suffix}" for suffix in suffixes]
    return [f"{run_id}-{suffix}" for suffix in suffixes]


def scrape_run_id_from_stage_run_id(run_id: str) -> str | None:
    for suffix in ("normalize", "enrich", "sync", "notify"):
        marker = f"-{suffix}"
        if run_id.endswith(marker):
            return f"{run_id[: -len(marker)]}-scrape"
    return None


def duplicate_count(counts: Counter[tuple[str, str]]) -> int:
    return sum(count - 1 for count in counts.values() if count > 1)


def metadata_value(metadata: dict[str, Any] | None, key: str) -> Any:
    return metadata.get(key) if isinstance(metadata, dict) else None


def latest_metadata_summary(raw_jobs: Sequence[RawJob]) -> dict[str, Any]:
    newest = None
    oldest = None
    requested_limit = None
    recency_mode = None
    recency_days = None
    for job in raw_jobs:
        metadata = job.metadata_json if isinstance(job.metadata_json, dict) else {}
        requested_limit = requested_limit or metadata.get("requestedLimit")
        recency_mode = recency_mode or metadata.get("recencyMode")
        recency_days = recency_days or metadata.get("recencyDays")
        source_timestamp = metadata.get("sourceTimestamp")
        if isinstance(source_timestamp, str):
            newest = source_timestamp if newest is None else max(newest, source_timestamp)
            oldest = source_timestamp if oldest is None else min(oldest, source_timestamp)
    return {
        "recencyMode": recency_mode,
        "recencyDays": recency_days,
        "requestedLimit": requested_limit,
        "newestSourceTimestamp": newest,
        "oldestSourceTimestamp": oldest,
    }


class ManualPipelineRunner:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        stage: str,
        source: str,
        keywords: tuple[str, ...],
        fixture_root: Path,
        limit: int,
        recency_mode: str,
        recency_days: int,
        execute: bool,
        run_id: str | None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.stage = stage
        self.source = source
        self.keywords = keywords
        self.fixture_root = fixture_root
        self.limit = limit
        self.recency_mode = recency_mode
        self.recency_days = recency_days
        self.execute = execute
        self.run_id = run_id
        self.output: dict[str, Any] | None = None
        self.stage_run_ids: dict[str, str] = {}

    async def run_stage(self, stage: ScheduledStage) -> None:
        stage_value = self.stage
        if self.run_id and stage_value == "full":
            run_id_prefix = self.run_id
        else:
            run_id_prefix = self.run_id
        orchestrator = self.build_orchestrator()
        if stage_value == "full":
            result = await self.run_full(orchestrator, run_id_prefix=run_id_prefix)
        else:
            result = await orchestrator.run_stage(stage_value, run_id=run_id_prefix)
        self.output = output_from_result(
            result,
            stage=stage_value,
            source=self.source,
            keywords=self.keywords,
            execute=self.execute,
            limit=self.limit,
            recency_mode=self.recency_mode,
            recency_days=self.recency_days,
            stage_run_ids=self.stage_run_ids,
        )

    async def run_named_stage(self, stage: str) -> None:
        await self.run_stage(stage_for_guard(stage))

    def build_orchestrator(self) -> PipelineOrchestrator:
        sync_run_id: dict[str, str] = {}

        async def enrich_hook(run_id: str, correlation_id: str) -> RunCounts:
            jobs = self.normalized_jobs_for_stage(run_id)
            repository = EnrichmentStagingRepository(self.session)
            for job in jobs:
                repository.upsert_output(
                    job=job,
                    output=fake_enrichment_output(),
                    ai_request_log_id=None,
                    source=EnrichmentSource.AI,
                )
            self.session.commit()
            return RunCounts(fetched=len(jobs), persisted=len(jobs))

        async def sync_hook(run_id: str, correlation_id: str) -> RunCounts:
            worker = BackendSyncWorker(
                session=self.session,
                client=RecordingBackendClient(),
                events=SyncEventRepository(self.session),
            )
            max_jobs = self.limit * source_count(self.source) * len(self.keywords)
            result = await worker.sync_eligible_jobs(
                scrape_run_id=run_id,
                limit=max_jobs,
                batch_size=min(max_jobs, 100),
            )
            self.session.commit()
            sync_run_id["value"] = run_id
            return RunCounts(fetched=result.attempted, persisted=result.sent, skipped=result.failed)

        async def handoff_hook(run_id: str, correlation_id: str) -> RunCounts:
            worker = RecommendationHandoffWorker(
                session=self.session,
                repository=NotificationHandoffRepository(self.session),
                client=RecordingHandoffClient(),
            )
            result = await worker.handoff_synced_jobs(
                scrape_run_id=sync_run_id.get("value", run_id)
            )
            self.session.commit()
            return RunCounts(fetched=result.attempted, persisted=result.sent, skipped=result.failed)

        return PipelineOrchestrator(
            sources=pipeline_sources(
                source=self.source,
                keywords=self.keywords,
                settings=self.settings,
                fixture_root=self.fixture_root,
                limit=self.limit,
                recency_mode=self.recency_mode,
                recency_days=self.recency_days,
                execute=self.execute,
            ),
            persistence=JobPersistenceRepository(self.session),
            run_tracker=RunStateTracker(self.session),
            stage_hooks={
                RunStage.ENRICH.value: enrich_hook,
                RunStage.SYNC.value: sync_hook,
                RunStage.NOTIFY_HANDOFF.value: handoff_hook,
            },
            correlation_id_factory=lambda: "manual-pipeline",
        )

    def normalized_jobs_for_stage(self, run_id: str) -> list[NormalizedJob]:
        scrape_run_id = scrape_run_id_from_stage_run_id(run_id)
        if scrape_run_id is None:
            return list(self.session.scalars(select(NormalizedJob)).all())
        raw_job_ids = list(
            self.session.scalars(select(RawJob.id).where(RawJob.scrape_run_id == scrape_run_id))
        )
        if not raw_job_ids:
            return []
        return list(
            self.session.scalars(
                select(NormalizedJob).where(NormalizedJob.raw_job_id.in_(raw_job_ids))
            ).all()
        )

    async def run_full(
        self,
        orchestrator: PipelineOrchestrator,
        *,
        run_id_prefix: str | None,
    ) -> PipelineResult:
        scrape = await orchestrator.run_scrape(run_id=suffixed_run_id(run_id_prefix, "scrape"))
        normalize = await orchestrator.run_normalize(
            run_id=suffixed_run_id(run_id_prefix, "normalize")
        )
        enrich = await orchestrator.run_enrich(run_id=suffixed_run_id(run_id_prefix, "enrich"))
        sync = await orchestrator.run_sync(run_id=suffixed_run_id(run_id_prefix, "sync"))
        notify = await orchestrator.run_notify_handoff(
            run_id=suffixed_run_id(run_id_prefix, "notify")
        )
        self.stage_run_ids = {
            "scrape": scrape.run_id,
            "normalize": normalize.run_id,
            "enrich": enrich.run_id,
            "sync": sync.run_id,
            "notify": notify.run_id,
        }
        statuses = {scrape.status, normalize.status, enrich.status, sync.status, notify.status}
        return PipelineResult(
            run_id=scrape.run_id,
            correlation_id=scrape.correlation_id,
            status="partial" if "partial" in statuses else "completed",
            counts=RunCounts(
                fetched=scrape.counts.fetched,
                parsed=normalize.counts.parsed,
                normalized=normalize.counts.normalized,
                persisted=notify.counts.persisted,
                skipped=(
                    scrape.counts.skipped
                    + normalize.counts.skipped
                    + enrich.counts.skipped
                    + sync.counts.skipped
                    + notify.counts.skipped
                ),
            ),
            source_results=scrape.source_results,
            stage_events=[
                *scrape.stage_events,
                *normalize.stage_events,
                *enrich.stage_events,
                *sync.stage_events,
                *notify.stage_events,
            ],
        )


@dataclass(frozen=True)
class FixtureRawJob:
    source_platform: str
    external_id: str
    source_url: str
    raw_payload: dict[str, Any]
    keyword: str
    requested_limit: int
    recency_mode: str
    recency_days: int
    source_timestamp: datetime


class FixturePipelineSource:
    def __init__(
        self,
        source_platform: str,
        keyword: str,
        fixture_path: Path,
        limit: int,
        recency_mode: str,
        recency_days: int,
    ) -> None:
        self.source_platform = source_platform
        self.keyword = keyword
        self.fixture_path = fixture_path
        self.requested_limit = limit
        self.recency_mode = recency_mode
        self.recency_days = recency_days

    async def fetch_raw_jobs(self) -> list[FixtureRawJob]:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        now = datetime.now(UTC)
        return [
            FixtureRawJob(
                source_platform=self.source_platform,
                external_id=f"{self.source_platform}-fixture-{index}",
                source_url=f"https://example.test/{self.source_platform}/fixture-{index}",
                raw_payload=payload,
                keyword=self.keyword,
                requested_limit=self.requested_limit,
                recency_mode=self.recency_mode,
                recency_days=self.recency_days,
                source_timestamp=now - timedelta(minutes=index),
            )
            for index in range(1, self.requested_limit + 1)
        ]

    def map_raw_job(self, raw_job: FixtureRawJob, *, scraped_at: datetime) -> SourceMapperResult:
        platform = SourcePlatform(raw_job.source_platform)
        source_timestamp = source_timestamp_from_raw_job(raw_job) or scraped_at
        return SourceMapperResult(
            job=CanonicalJobSchema(
                source=SourceMetadataSchema(
                    platform=platform,
                    external_job_id=raw_job.external_id,
                    source_url=raw_job.source_url,
                    scraped_at=scraped_at,
                    source_updated_at=source_timestamp,
                ),
                title=f"{platform.value.title()} Backend Engineer",
                company=CompanySchema(name=f"{platform.value.title()} Company"),
                location=LocationSchema(display="Jakarta", city="Jakarta", country="Indonesia"),
                description="Build Python APIs and data pipelines.",
                requirements="Python and SQL experience.",
                skills=["Python", "SQL"],
                posted_at=source_timestamp,
                last_seen_at=datetime.now(UTC),
                status=CanonicalJobStatus.ACTIVE,
            ),
            field_provenance={"title": "fixture"},
        )


@dataclass(frozen=True)
class LiveRawJob:
    source_platform: str
    external_id: str
    source_url: str
    raw_payload: dict[str, Any]
    keyword: str
    requested_limit: int
    recency_mode: str
    recency_days: int
    source_timestamp: datetime | None
    source_job: Any


class LivePipelineSource:
    def __init__(
        self,
        *,
        source_platform: str,
        keyword: str,
        requested_limit: int,
        recency_mode: str,
        recency_days: int,
        fetcher,
        mapper,
        raw_model,
        timestamp_extractor,
    ) -> None:
        self.source_platform = source_platform
        self.keyword = keyword
        self.requested_limit = requested_limit
        self.recency_mode = recency_mode
        self.recency_days = recency_days
        self._fetcher = fetcher
        self._mapper = mapper
        self._raw_model = raw_model
        self._timestamp_extractor = timestamp_extractor

    async def fetch_raw_jobs(self) -> list[LiveRawJob]:
        raw_jobs = await self._fetcher(self.keyword, self.requested_limit, self.recency_days)
        selected = raw_jobs[: self.requested_limit]
        return [
            LiveRawJob(
                source_platform=raw_job.source_platform,
                external_id=raw_job.external_id,
                source_url=raw_job.source_url,
                raw_payload=raw_job.raw_payload,
                keyword=self.keyword,
                requested_limit=self.requested_limit,
                recency_mode=self.recency_mode,
                recency_days=self.recency_days,
                source_timestamp=self._timestamp_extractor(raw_job.raw_payload),
                source_job=raw_job,
            )
            for raw_job in selected
        ]

    def map_raw_job(self, raw_job: LiveRawJob, *, scraped_at: datetime) -> SourceMapperResult:
        source_job = getattr(raw_job, "source_job", None)
        if source_job is None:
            source_job = self._raw_model(
                source_platform=raw_job.source_platform,
                external_id=raw_job.external_id,
                source_url=raw_job.source_url,
                raw_payload=raw_job.raw_payload,
            )
        return self._mapper(source_job, scraped_at=scraped_at)


def pipeline_sources(
    *,
    source: str,
    keywords: tuple[str, ...],
    settings: Settings,
    fixture_root: Path,
    limit: int,
    recency_mode: str,
    recency_days: int,
    execute: bool,
) -> list[FixturePipelineSource | LivePipelineSource]:
    if not execute:
        return fixture_sources(
            source=source,
            keywords=keywords,
            fixture_root=fixture_root,
            limit=limit,
            recency_mode=recency_mode,
            recency_days=recency_days,
        )
    return live_sources(
        source=source,
        keywords=keywords,
        settings=settings,
        limit=limit,
        recency_mode=recency_mode,
        recency_days=recency_days,
    )


def live_sources(
    *,
    source: str,
    keywords: tuple[str, ...],
    settings: Settings,
    limit: int,
    recency_mode: str,
    recency_days: int,
) -> list[LivePipelineSource]:
    selected = live_platforms(source, settings)
    factories = {
        "dealls": build_live_dealls_source,
        "glints": build_live_glints_source,
        "jobstreet": build_live_jobstreet_source,
        "kalibrr": build_live_kalibrr_source,
    }
    return [
        factories[platform](
            keyword=keyword,
            limit=limit,
            recency_mode=recency_mode,
            recency_days=recency_days,
            settings=settings,
        )
        for platform in selected
        for keyword in keywords
    ]


def live_platforms(source: str, settings: Settings) -> tuple[str, ...]:
    if source == "all":
        return tuple(
            platform
            for platform in SOURCE_CHOICES[1:]
            if platform != "jobstreet" or settings.jobstreet_enabled
        )
    if source == "jobstreet" and not settings.jobstreet_enabled:
        raise ValueError("JobStreet source is disabled")
    return (source,)


def build_live_dealls_source(
    *,
    keyword: str,
    limit: int,
    recency_mode: str,
    recency_days: int,
    settings: Settings,
) -> LivePipelineSource:
    async def fetcher(keyword: str, limit: int, recency_days: int):
        async with build_dealls_http_client(
            base_url=dealls_api_base_url(settings.dealls_base_url),
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            max_response_bytes=settings.http_response_max_bytes,
            rate_limit_per_minute=settings.dealls_rate_limit_per_minute,
        ) as http_client:
            result = await DeallsListAdapter(http_client).fetch_page(
                DeallsListQuery(limit=limit, search=keyword)
            )
            return result.raw_jobs

    return LivePipelineSource(
        source_platform="dealls",
        keyword=keyword,
        requested_limit=limit,
        recency_mode=recency_mode,
        recency_days=recency_days,
        fetcher=fetcher,
        mapper=map_dealls_job,
        raw_model=DeallsRawSourceJob,
        timestamp_extractor=extract_dealls_source_timestamp,
    )


def dealls_api_base_url(configured_url: str) -> str:
    parsed = urlparse(configured_url)
    if parsed.netloc in {"dealls.com", "www.dealls.com"}:
        return "https://api.sejutacita.id/v1"
    return configured_url


def origin_base_url(configured_url: str) -> str:
    parsed = urlparse(configured_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return configured_url


def jobstreet_search_path(*, keyword: str, recency_days: int) -> str:
    clean_keyword = keyword.strip()
    if "/" in clean_keyword:
        encoded_keyword = quote(clean_keyword, safe="")
        return f"/id/jobs?keywords={encoded_keyword}&daterange={recency_days}"
    slug = quote(clean_keyword.replace(" ", "-"), safe="")
    return f"/id/{slug}-jobs?daterange={recency_days}"


def jobstreet_payload_from_search_page(html: str) -> dict[str, Any]:
    marker = "window.SEEK_REDUX_DATA = "
    marker_start = html.find(marker)
    if marker_start == -1:
        raise ValueError("JobStreet page missing search data")
    payload = json.loads(extract_balanced_json_object(html, marker_start + len(marker)))
    results_root = payload.get("results") if isinstance(payload, dict) else None
    nested_results = results_root.get("results") if isinstance(results_root, dict) else None
    jobs = nested_results.get("jobs") if isinstance(nested_results, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("JobStreet page missing jobs list")
    total_count = results_root.get("totalCount") if isinstance(results_root, dict) else len(jobs)
    return {"data": {"jobSearchV6": {"data": jobs, "totalCount": total_count}}}


def extract_balanced_json_object(text: str, start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unterminated JSON object")


def build_live_glints_source(
    *,
    keyword: str,
    limit: int,
    recency_mode: str,
    recency_days: int,
    settings: Settings,
) -> LivePipelineSource:
    async def fetcher(keyword: str, limit: int, recency_days: int):
        async with build_glints_http_client(
            base_url=origin_base_url(settings.glints_graphql_url),
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            max_response_bytes=settings.http_response_max_bytes,
            rate_limit_per_minute=settings.glints_rate_limit_per_minute,
        ) as http_client:
            result = await GlintsListAdapter(http_client).fetch_page(
                GlintsListQuery(
                    page_size=limit,
                    search_term=keyword,
                    country_code=settings.glints_country_code,
                )
            )
            return result.raw_jobs

    return LivePipelineSource(
        source_platform="glints",
        keyword=keyword,
        requested_limit=limit,
        recency_mode=recency_mode,
        recency_days=recency_days,
        fetcher=fetcher,
        mapper=map_glints_job,
        raw_model=GlintsRawSourceJob,
        timestamp_extractor=extract_glints_source_timestamp,
    )


def build_live_jobstreet_source(
    *,
    keyword: str,
    limit: int,
    recency_mode: str,
    recency_days: int,
    settings: Settings,
) -> LivePipelineSource:
    async def fetcher(keyword: str, limit: int, recency_days: int):
        token = (
            settings.jobstreet_bearer_token.get_secret_value()
            if settings.jobstreet_bearer_token is not None
            else None
        )
        async with build_jobstreet_http_client(
            base_url=origin_base_url(settings.jobstreet_graphql_url),
            bearer_token=token,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            max_response_bytes=settings.http_response_max_bytes,
            rate_limit_per_minute=settings.jobstreet_rate_limit_per_minute,
        ) as http_client:
            html = await http_client.request_text(
                "GET",
                jobstreet_search_path(keyword=keyword, recency_days=recency_days),
                headers={"accept": "text/html"},
            )
            payload = jobstreet_payload_from_search_page(html)
            result = parse_jobstreet_list_payload(
                payload,
                query=JobStreetListQuery(
                    keywords=keyword,
                    page_size=max(limit, 1),
                    date_range=recency_days,
                ),
            )
            return result.raw_jobs

    return LivePipelineSource(
        source_platform="jobstreet",
        keyword=keyword,
        requested_limit=limit,
        recency_mode=recency_mode,
        recency_days=recency_days,
        fetcher=fetcher,
        mapper=map_jobstreet_job,
        raw_model=JobStreetRawSourceJob,
        timestamp_extractor=extract_jobstreet_source_timestamp,
    )


def build_live_kalibrr_source(
    *,
    keyword: str,
    limit: int,
    recency_mode: str,
    recency_days: int,
    settings: Settings,
) -> LivePipelineSource:
    async def fetcher(keyword: str, limit: int, recency_days: int):
        async with build_kalibrr_http_client(
            base_url=settings.kalibrr_base_url,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            max_response_bytes=settings.http_response_max_bytes,
            rate_limit_per_minute=settings.kalibrr_rate_limit_per_minute,
        ) as http_client:
            result = await KalibrrListAdapter(
                http_client=http_client,
                build_id_resolver=KalibrrBuildIdResolver(http_client),
            ).fetch_page(KalibrrListQuery(keyword=keyword))
            return result.raw_jobs

    return LivePipelineSource(
        source_platform="kalibrr",
        keyword=keyword,
        requested_limit=limit,
        recency_mode=recency_mode,
        recency_days=recency_days,
        fetcher=fetcher,
        mapper=map_kalibrr_job,
        raw_model=KalibrrRawSourceJob,
        timestamp_extractor=extract_kalibrr_source_timestamp,
    )


class RecordingBackendClient:
    async def sync_jobs(self, jobs: list[dict[str, Any]]) -> BackendSyncResult:
        return BackendSyncResult(
            status_code=202,
            response_summary={"statusCode": 202, "statusClass": "2xx", "count": len(jobs)},
        )


class RecordingHandoffClient:
    async def send_candidates(self, payload: dict[str, Any]) -> HandoffSuccess:
        return HandoffSuccess({"statusCode": 202, "statusClass": "2xx"})


def fixture_sources(
    *,
    source: str,
    keywords: tuple[str, ...],
    fixture_root: Path,
    limit: int,
    recency_mode: str,
    recency_days: int,
) -> list[FixturePipelineSource]:
    selected = SOURCE_CHOICES[1:] if source == "all" else (source,)
    return [
        FixturePipelineSource(
            platform,
            keyword,
            fixture_root / platform / "sample.json",
            limit,
            recency_mode,
            recency_days,
        )
        for platform in selected
        for keyword in keywords
    ]


def source_count(source: str) -> int:
    return len(SOURCE_CHOICES) - 1 if source == "all" else 1


def output_from_result(
    result: PipelineResult,
    *,
    stage: str,
    source: str,
    keywords: tuple[str, ...],
    execute: bool,
    limit: int,
    recency_mode: str,
    recency_days: int,
    stage_run_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "check": "pipeline-run",
        "status": "ok" if result.status in {"completed", "partial"} else "fail",
        "mode": "execute" if execute else "dry-run",
        "stage": stage,
        "source": source,
        "keywords": list(keywords),
        "runId": result.run_id,
        "stageRunIds": stage_run_ids or {},
        "runStatus": result.status,
        "correlationId": result.correlation_id,
        "limit": limit,
        "recencyMode": recency_mode,
        "recencyDays": recency_days,
        "counts": result.counts.model_dump(),
        "sources": [
            {
                "source": source_result.source_platform,
                "keyword": source_result.keyword,
                "status": source_result.status,
                "counts": source_result.counts.model_dump(),
                "requestedLimit": source_result.requested_limit,
                "newestSourceTimestamp": serialize_datetime(source_result.newest_source_timestamp),
                "oldestSourceTimestamp": serialize_datetime(source_result.oldest_source_timestamp),
                "truncatedCount": source_result.truncated_count,
            }
            for source_result in result.source_results
        ],
        "events": result.stage_events,
    }


def build_engine(database_url: str, *, execute: bool) -> Engine:
    if not execute:
        return create_engine("sqlite:///:memory:")
    return create_engine(to_sync_url(database_url), pool_pre_ping=True)


def to_sync_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() == "postgresql" and url.drivername in {
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg_async",
    }:
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    return database_url


def load_settings(env_file: str | None) -> Settings:
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    if parsed > 100:
        raise argparse.ArgumentTypeError("must be less than or equal to 100")
    return parsed


def recency_days(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    if parsed > 365:
        raise argparse.ArgumentTypeError("must be less than or equal to 365")
    return parsed


def resolve_keywords(args: argparse.Namespace, settings: Settings) -> tuple[str, ...]:
    values: list[str] = []
    if args.keyword:
        values.extend(args.keyword)
    if args.keywords:
        values.append(args.keywords)
    if not values:
        return settings.scraper_keywords
    return parse_keyword_values(values)


def parse_keyword_values(values: Sequence[str]) -> tuple[str, ...]:
    keywords: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw_keyword in value.split(","):
            keyword = raw_keyword.strip()
            if not keyword:
                raise argparse.ArgumentTypeError("keywords must not contain empty entries")
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(keyword)
    return tuple(keywords)


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def source_timestamp_from_raw_job(raw_job: Any) -> datetime | None:
    value = getattr(raw_job, "source_timestamp", None)
    if isinstance(value, datetime):
        return value
    metadata = getattr(raw_job, "metadata_json", None)
    if isinstance(metadata, dict):
        raw_value = metadata.get("sourceTimestamp")
        if isinstance(raw_value, str):
            text = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                return None
    return None


def stage_for_guard(stage: str) -> ScheduledStage:
    if stage == "full":
        return ScheduledStage.SCRAPE
    return ScheduledStage(stage)


def suffixed_run_id(prefix: str | None, suffix: str) -> str | None:
    return f"{prefix}-{suffix}" if prefix else None


def fake_enrichment_output() -> EnrichmentOutput:
    return EnrichmentOutput(
        skills=[EnrichedSkill(name="Python", confidence=0.9)],
        requirements=[
            EnrichedRequirement(
                type=RequirementType.SKILL,
                value="SQL experience",
                confidence=0.8,
            )
        ],
        confidence=0.85,
    )


if __name__ == "__main__":
    raise SystemExit(main())
