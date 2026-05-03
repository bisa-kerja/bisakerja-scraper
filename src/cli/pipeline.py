from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings
from integrations.backend import BackendSyncResult
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
from modules.persistence import Base, JobPersistenceRepository, NormalizedJob, ScrapeRun
from modules.runs import RunCounts, RunStage, RunStateTracker
from modules.sync import BackendSyncWorker, SyncEventRepository

SOURCE_CHOICES = ("all", "dealls", "glints", "jobstreet", "kalibrr")
STAGE_CHOICES = ("full", "scrape", "normalize", "enrich", "sync", "notify-handoff")
DEFAULT_FIXTURE_ROOT = Path("tests/fixtures/raw")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = asyncio.run(args.command_handler(args))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scraper-pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--stage", choices=STAGE_CHOICES, default="full")
    run_parser.add_argument("--source", choices=SOURCE_CHOICES, default="all")
    run_parser.add_argument("--limit", type=positive_int, default=10)
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
    return parser


async def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    engine = build_engine(settings.scraper_database_url, execute=args.execute)
    if not args.execute:
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    guard = ManualTriggerGuard()
    with factory() as session:
        runner = ManualPipelineRunner(
            session=session,
            stage=args.stage,
            source=args.source,
            fixture_root=Path(args.fixture_root),
            limit=args.limit,
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


class ManualPipelineRunner:
    def __init__(
        self,
        *,
        session: Session,
        stage: str,
        source: str,
        fixture_root: Path,
        limit: int,
        execute: bool,
        run_id: str | None,
    ) -> None:
        self.session = session
        self.stage = stage
        self.source = source
        self.fixture_root = fixture_root
        self.limit = limit
        self.execute = execute
        self.run_id = run_id
        self.output: dict[str, Any] | None = None

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
            execute=self.execute,
            limit=self.limit,
        )

    async def run_named_stage(self, stage: str) -> None:
        await self.run_stage(stage_for_guard(stage))

    def build_orchestrator(self) -> PipelineOrchestrator:
        sync_run_id: dict[str, str] = {}

        async def enrich_hook(run_id: str, correlation_id: str) -> RunCounts:
            jobs = list(self.session.scalars(select(NormalizedJob)).all())
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
            max_jobs = self.limit * source_count(self.source)
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
            sources=fixture_sources(
                source=self.source,
                fixture_root=self.fixture_root,
                limit=self.limit,
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


class FixturePipelineSource:
    def __init__(self, source_platform: str, fixture_path: Path, limit: int) -> None:
        self.source_platform = source_platform
        self.fixture_path = fixture_path
        self.limit = limit

    async def fetch_raw_jobs(self) -> list[FixtureRawJob]:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        return [
            FixtureRawJob(
                source_platform=self.source_platform,
                external_id=f"{self.source_platform}-fixture-{index}",
                source_url=f"https://example.test/{self.source_platform}/fixture-{index}",
                raw_payload=payload,
            )
            for index in range(1, self.limit + 1)
        ]

    def map_raw_job(self, raw_job: FixtureRawJob, *, scraped_at: datetime) -> SourceMapperResult:
        platform = SourcePlatform(raw_job.source_platform)
        return SourceMapperResult(
            job=CanonicalJobSchema(
                source=SourceMetadataSchema(
                    platform=platform,
                    external_job_id=raw_job.external_id,
                    source_url=raw_job.source_url,
                    scraped_at=scraped_at,
                ),
                title=f"{platform.value.title()} Backend Engineer",
                company=CompanySchema(name=f"{platform.value.title()} Company"),
                location=LocationSchema(display="Jakarta", city="Jakarta", country="Indonesia"),
                description="Build Python APIs and data pipelines.",
                requirements="Python and SQL experience.",
                skills=["Python", "SQL"],
                last_seen_at=datetime.now(UTC),
                status=CanonicalJobStatus.ACTIVE,
            ),
            field_provenance={"title": "fixture"},
        )


class RecordingBackendClient:
    async def sync_normalized_jobs(self, jobs: list[NormalizedJob]) -> BackendSyncResult:
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
    fixture_root: Path,
    limit: int,
) -> list[FixturePipelineSource]:
    selected = SOURCE_CHOICES[1:] if source == "all" else (source,)
    return [
        FixturePipelineSource(platform, fixture_root / platform / "sample.json", limit)
        for platform in selected
    ]


def source_count(source: str) -> int:
    return len(SOURCE_CHOICES) - 1 if source == "all" else 1


def output_from_result(
    result: PipelineResult,
    *,
    stage: str,
    source: str,
    execute: bool,
    limit: int,
) -> dict[str, Any]:
    return {
        "check": "pipeline-run",
        "status": "ok" if result.status in {"completed", "partial"} else "fail",
        "mode": "execute" if execute else "dry-run",
        "stage": stage,
        "source": source,
        "runId": result.run_id,
        "runStatus": result.status,
        "correlationId": result.correlation_id,
        "limit": limit,
        "counts": result.counts.model_dump(),
        "sources": [
            {
                "source": source_result.source_platform,
                "status": source_result.status,
                "counts": source_result.counts.model_dump(),
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
