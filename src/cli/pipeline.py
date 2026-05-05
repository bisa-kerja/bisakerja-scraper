from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import shlex
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from config.database_urls import to_sync_postgres_url
from config.settings import Settings
from integrations.ai import OpenAIEnrichmentClient, OpenAINormalizationClient
from integrations.backend import (
    BackendNotificationHandoffClient,
    BackendSyncClient,
    BackendSyncResult,
)
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
from jobs.pipeline import PipelineConfig, PipelineOrchestrator, PipelineResult
from jobs.scheduler import ManualTriggerGuard, ScheduledStage
from modules.enrichment import EnrichmentService, EnrichmentServiceConfig
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
    AIRequestLog,
    Base,
    JobPersistenceRepository,
    JobRequirementStaging,
    JobSkillStaging,
    NormalizationQuarantine,
    NormalizedJob,
    NotificationHandoffEvent,
    RawJob,
    ScrapeRun,
    StageJob,
    SyncEvent,
)
from modules.runs import RunCounts, RunStage, RunStateTracker
from modules.sync import BackendSyncWorker, SyncEventRepository

SOURCE_CHOICES = ("all", "dealls", "glints", "jobstreet", "kalibrr")
STAGE_CHOICES = ("full", "scrape", "normalize", "enrich", "sync", "notify-handoff")
WIZARD_MODE_CHOICES = ("dry-run", "execute", "status", "verify", "staging-report")
WIZARD_ENV_PRESET_CHOICES = (".env.example", ".env", ".env.production")
SAFE_AUTO_APPROVE_ENVS = {"local", "test"}
DEFAULT_FIXTURE_ROOT = Path("tests/fixtures/raw")
PLATFORM_SOURCES = SOURCE_CHOICES[1:]
SENSITIVE_TOKEN_PATTERN = re.compile(r"(bearer\s+)[^\s]+", re.IGNORECASE)
SENSITIVE_QUERY_PATTERN = re.compile(r"((token|password|secret|key)=)[^&\s]+", re.IGNORECASE)


class CliInputError(ValueError):
    """Raised when CLI input is invalid but should not trigger traceback."""


@dataclass(frozen=True)
class SourceSelection:
    requested: tuple[str, ...]
    executed: tuple[str, ...]
    skipped: tuple[dict[str, str], ...]


class PipelineArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - exercised via main()
        raise CliInputError(message)


def command_check_name(command: str | None) -> str:
    mapping = {
        "run": "pipeline-run",
        "status": "pipeline-status",
        "verify": "pipeline-verify",
        "staging-report": "staging-report",
        "preflight": "pipeline-preflight",
        "wizard": "pipeline-wizard",
        "quick-dry-run": "pipeline-quick-dry-run",
    }
    if command is None:
        return "pipeline-cli"
    return mapping.get(command, "pipeline-cli")


def cli_fail_result(
    *,
    check: str,
    reason: str,
    command: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "check": check,
        "status": "fail",
        "command": command,
        "reason": redact_text(reason),
    }
    if error_type is not None:
        result["errorType"] = error_type
    return result


def redact_text(text: str) -> str:
    compact = " ".join(text.strip().split())
    compact = SENSITIVE_TOKEN_PATTERN.sub(r"\1***", compact)
    compact = SENSITIVE_QUERY_PATTERN.sub(r"\1***", compact)
    return compact


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CliInputError as exc:
        result = cli_fail_result(check="pipeline-cli", reason=str(exc), command="parse")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    except SystemExit as exc:
        if exc.code == 0:
            raise
        result = cli_fail_result(
            check="pipeline-cli",
            reason="argument parsing failed",
            command="parse",
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 1
    try:
        result = asyncio.run(args.command_handler(args))
    except CliInputError as exc:
        result = cli_fail_result(
            check=command_check_name(args.command),
            reason=str(exc),
            command=args.command,
        )
    except Exception as exc:  # pragma: no cover - integration behavior asserted by CLI tests
        result = cli_fail_result(
            check=command_check_name(args.command),
            reason=str(exc),
            command=args.command,
            error_type=type(exc).__name__,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = PipelineArgumentParser(prog="scraper-pipeline")
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
    mode_group = run_parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--execute", action="store_true")
    run_parser.set_defaults(command_handler=run_pipeline)

    wizard_parser = subparsers.add_parser("wizard")
    wizard_parser.add_argument("--mode", choices=WIZARD_MODE_CHOICES, default=None)
    wizard_parser.add_argument("--stage", choices=STAGE_CHOICES, default=None)
    wizard_parser.add_argument("--source", choices=SOURCE_CHOICES, default=None)
    wizard_parser.add_argument("--limit", type=positive_int, default=None)
    wizard_parser.add_argument("--keyword", action="append", default=None)
    wizard_parser.add_argument("--keywords", default=None)
    wizard_parser.add_argument("--latest", action="store_true")
    wizard_parser.add_argument("--recency-days", type=recency_days, default=None)
    wizard_parser.add_argument("--env-file", default=None)
    wizard_parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    wizard_parser.add_argument("--run-id", default=None)
    wizard_parser.add_argument("--database-url", default=None)
    wizard_parser.add_argument("--scraper-database-url", default=None)
    wizard_parser.add_argument("--backend-database-url", default=None)
    wizard_parser.add_argument("--backend-base-url", default=None)
    wizard_parser.add_argument("--backend-token", default=None)
    wizard_parser.add_argument("--sample-per-source", type=positive_sample_size, default=1)
    wizard_parser.add_argument("--stage-p95-threshold-ms", type=positive_metric_value, default=None)
    wizard_parser.add_argument("--ai-p95-threshold-ms", type=positive_metric_value, default=None)
    wizard_parser.add_argument("--sync-p95-threshold-ms", type=positive_metric_value, default=None)
    wizard_parser.add_argument("--retry-threshold", type=non_negative_metric_value, default=None)
    wizard_parser.add_argument("--glints-partial-min-rate", type=ratio_0_to_1, default=0.95)
    wizard_parser.add_argument("--glints-partial-max-rate", type=ratio_0_to_1, default=1.0)
    wizard_parser.add_argument("--dry-run", action="store_true")
    wizard_parser.add_argument("--execute", action="store_true")
    wizard_parser.add_argument("--yes", action="store_true")
    wizard_parser.set_defaults(command_handler=run_wizard)

    quick_dry_run_parser = subparsers.add_parser("quick-dry-run")
    quick_dry_run_parser.add_argument("--stage", choices=STAGE_CHOICES, default="full")
    quick_dry_run_parser.add_argument("--source", choices=SOURCE_CHOICES, default="all")
    quick_dry_run_parser.add_argument("--limit", type=positive_int, default=1)
    quick_dry_run_parser.add_argument("--keyword", action="append", default=None)
    quick_dry_run_parser.add_argument("--keywords", default=None)
    quick_dry_run_parser.add_argument("--latest", action="store_true")
    quick_dry_run_parser.add_argument("--recency-days", type=recency_days, default=None)
    quick_dry_run_parser.add_argument("--env-file", default=".env.example")
    quick_dry_run_parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    quick_dry_run_parser.add_argument("--run-id", default=None)
    quick_dry_run_parser.set_defaults(command_handler=run_quick_dry_run)

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

    staging_parser = subparsers.add_parser("staging-report")
    staging_parser.add_argument("--run-id", required=True)
    staging_parser.add_argument("--env-file", default=None)
    staging_parser.add_argument("--scraper-database-url", default=None)
    staging_parser.add_argument("--backend-database-url", default=None)
    staging_parser.add_argument("--backend-base-url", default=None)
    staging_parser.add_argument("--backend-token", default=None)
    staging_parser.add_argument("--sample-per-source", type=positive_sample_size, default=1)
    staging_parser.add_argument(
        "--stage-p95-threshold-ms",
        type=positive_metric_value,
        default=None,
    )
    staging_parser.add_argument("--ai-p95-threshold-ms", type=positive_metric_value, default=None)
    staging_parser.add_argument("--sync-p95-threshold-ms", type=positive_metric_value, default=None)
    staging_parser.add_argument("--retry-threshold", type=non_negative_metric_value, default=None)
    staging_parser.add_argument(
        "--glints-partial-min-rate",
        type=ratio_0_to_1,
        default=0.95,
    )
    staging_parser.add_argument(
        "--glints-partial-max-rate",
        type=ratio_0_to_1,
        default=1.0,
    )
    staging_parser.set_defaults(command_handler=run_staging_report)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--stage", choices=STAGE_CHOICES, default="full")
    preflight_parser.add_argument("--source", choices=SOURCE_CHOICES, default="all")
    preflight_parser.add_argument("--env-file", default=None)
    preflight_parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    mode_group = preflight_parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--execute", action="store_true")
    preflight_parser.set_defaults(command_handler=run_preflight)
    return parser


async def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    source_selection = select_sources(
        source=args.source,
        settings=settings,
        execute=args.execute,
    )
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
            source_selection=source_selection,
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


async def run_quick_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    run_args = argparse.Namespace(
        stage=args.stage,
        source=args.source,
        limit=args.limit,
        keyword=args.keyword,
        keywords=args.keywords,
        latest=args.latest,
        recency_days=args.recency_days,
        env_file=args.env_file,
        fixture_root=args.fixture_root,
        run_id=args.run_id,
        dry_run=True,
        execute=False,
    )
    return await run_pipeline(run_args)


async def run_wizard(args: argparse.Namespace) -> dict[str, Any]:
    selected_mode = resolve_wizard_mode(args)
    interactive_tty = wizard_tty_available()

    if not interactive_tty:
        return await run_wizard_non_tty(args, selected_mode)

    mode = selected_mode or wizard_prompt_choice(
        "Select mode",
        WIZARD_MODE_CHOICES,
        default="dry-run",
    )
    env_file = args.env_file or wizard_prompt_env_file(default=".env.example")
    settings = load_settings(env_file)

    if mode in {"dry-run", "execute"}:
        run_args = wizard_build_run_args(
            args=args,
            mode=mode,
            env_file=env_file,
            settings=settings,
            interactive=True,
        )
        preview = wizard_run_preview(run_args=run_args, settings=settings)
        wizard_emit_summary(preview)
        wizard_require_confirmation(
            preview=preview,
            interactive=True,
            auto_approve=args.yes,
        )
        run_result = await run_pipeline(run_args)
        return wizard_wrap_pipeline_result(
            mode=mode,
            preview=preview,
            run_result=run_result,
        )

    if mode in {"status", "verify"}:
        run_id = args.run_id or wizard_prompt_text("Run id")
        command_args = argparse.Namespace(
            run_id=run_id,
            env_file=env_file,
            database_url=args.database_url,
        )
        result = await (run_status(command_args) if mode == "status" else run_verify(command_args))
        return wizard_wrap_read_result(mode=mode, result=result)

    if mode == "staging-report":
        run_id = args.run_id or wizard_prompt_text("Run id")
        command_args = argparse.Namespace(
            run_id=run_id,
            env_file=env_file,
            scraper_database_url=args.scraper_database_url,
            backend_database_url=args.backend_database_url,
            backend_base_url=args.backend_base_url,
            backend_token=args.backend_token,
            sample_per_source=args.sample_per_source,
            stage_p95_threshold_ms=args.stage_p95_threshold_ms,
            ai_p95_threshold_ms=args.ai_p95_threshold_ms,
            sync_p95_threshold_ms=args.sync_p95_threshold_ms,
            retry_threshold=args.retry_threshold,
            glints_partial_min_rate=args.glints_partial_min_rate,
            glints_partial_max_rate=args.glints_partial_max_rate,
        )
        result = await run_staging_report(command_args)
        return wizard_wrap_read_result(mode=mode, result=result)

    raise CliInputError(f"unsupported wizard mode: {mode}")


async def run_wizard_non_tty(
    args: argparse.Namespace,
    selected_mode: str | None,
) -> dict[str, Any]:
    mode = selected_mode or "dry-run"
    if mode != "dry-run":
        raise CliInputError(
            "wizard requires TTY for mode other than dry-run. "
            "Use regular subcommands (run/status/verify/staging-report) in non-interactive mode."
        )
    if args.execute:
        raise CliInputError("wizard non-TTY does not allow --execute")
    if not args.yes:
        raise CliInputError("wizard non-TTY requires --yes for safe dry-run execution")

    env_file = args.env_file or ".env.example"
    settings = load_settings(env_file)
    run_args = wizard_build_run_args(
        args=args,
        mode="dry-run",
        env_file=env_file,
        settings=settings,
        interactive=False,
    )
    preview = wizard_run_preview(run_args=run_args, settings=settings)
    wizard_require_confirmation(
        preview=preview,
        interactive=False,
        auto_approve=True,
    )
    run_result = await run_pipeline(run_args)
    return wizard_wrap_pipeline_result(
        mode="dry-run",
        preview=preview,
        run_result=run_result,
    )


def resolve_wizard_mode(args: argparse.Namespace) -> str | None:
    if args.mode is not None and (args.dry_run or args.execute):
        raise CliInputError("wizard mode conflict: use either --mode or --dry-run/--execute")
    if args.dry_run and args.execute:
        raise CliInputError("wizard mode conflict: --dry-run and --execute are mutually exclusive")
    if args.mode is not None:
        return args.mode
    if args.execute:
        return "execute"
    if args.dry_run:
        return "dry-run"
    return None


def wizard_tty_available() -> bool:
    stdin_ready = bool(getattr(sys.stdin, "isatty", lambda: False)())
    stdout_ready = bool(getattr(sys.stdout, "isatty", lambda: False)())
    return stdin_ready and stdout_ready


def wizard_prompt_env_file(*, default: str) -> str:
    use_preset = wizard_prompt_yes_no(
        "Use preset env file list?",
        default=True,
    )
    if use_preset:
        return wizard_prompt_choice(
            "Select env file",
            WIZARD_ENV_PRESET_CHOICES,
            default=default,
        )
    return wizard_prompt_text("Custom env file path", default=default)


def wizard_build_run_args(
    *,
    args: argparse.Namespace,
    mode: str,
    env_file: str,
    settings: Settings,
    interactive: bool,
) -> argparse.Namespace:
    stage = args.stage or (
        wizard_prompt_choice("Select stage", STAGE_CHOICES, default="full")
        if interactive
        else "full"
    )
    source = args.source or (
        wizard_prompt_choice("Select source", SOURCE_CHOICES, default="all")
        if interactive
        else "all"
    )
    limit = args.limit
    if limit is None:
        default_limit = settings.scraper_max_items_per_keyword
        limit = (
            wizard_prompt_int("Limit per keyword", default=default_limit)
            if interactive
            else default_limit
        )
    recency_days_value = args.recency_days
    if recency_days_value is None:
        recency_days_value = (
            wizard_prompt_int("Recency days", default=settings.scraper_recency_days)
            if interactive
            else settings.scraper_recency_days
        )

    keyword = args.keyword
    keywords = args.keywords
    if keyword is None and keywords is None and interactive:
        use_env_keywords = wizard_prompt_yes_no(
            f"Use env keyword preset ({', '.join(settings.scraper_keywords)})?",
            default=True,
        )
        if not use_env_keywords:
            keywords = wizard_prompt_text("Custom keywords (comma-separated)")

    run_id = args.run_id
    if interactive and not run_id:
        if wizard_prompt_yes_no("Set custom run id?", default=False):
            run_id = wizard_prompt_text("Run id")

    return argparse.Namespace(
        stage=stage,
        source=source,
        limit=limit,
        keyword=keyword,
        keywords=keywords,
        latest=args.latest,
        recency_days=recency_days_value,
        env_file=env_file,
        fixture_root=args.fixture_root,
        run_id=run_id,
        dry_run=mode == "dry-run",
        execute=mode == "execute",
    )


def wizard_run_preview(*, run_args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    source_selection = select_sources(
        source=run_args.source,
        settings=settings,
        execute=run_args.execute,
    )
    keywords = resolve_keywords(run_args, settings)
    backend_mode = backend_sync_mode(settings, execute=run_args.execute)
    env_name = settings.app_env.value
    risks: list[str] = []
    if run_args.execute:
        risks.append("execute mode mutates scraper database and may call live source APIs")
    if env_name in {"staging", "production"}:
        risks.append(f"environment is {env_name}")
    if settings.backend_sync_enabled:
        risks.append("BACKEND_SYNC_ENABLED=true (live backend sync/handoff)")
    if (
        run_args.execute
        and "jobstreet" in source_selection.executed
        and settings.jobstreet_enabled
        and settings.jobstreet_bearer_token is not None
    ):
        risks.append("JobStreet live token will be used")
    if run_args.execute and settings.ai_enrichment_enabled:
        risks.append("AI enrichment is enabled")

    run_tokens = build_run_command_tokens(run_args)
    mutation_scope = "read-only fixture flow"
    if run_args.execute:
        mutation_scope = "source fetch + scraper DB write"
        if settings.backend_sync_enabled:
            mutation_scope += " + backend sync/handoff"

    return {
        "mode": "execute" if run_args.execute else "dry-run",
        "envFile": run_args.env_file,
        "env": env_name,
        "stage": run_args.stage,
        "source": run_args.source,
        "keywords": list(keywords),
        "limit": run_args.limit,
        "recencyMode": "latest" if run_args.latest else settings.scraper_recency_mode.value,
        "recencyDays": run_args.recency_days,
        "requestedSources": list(source_selection.requested),
        "executedSources": list(source_selection.executed),
        "skippedSources": list(source_selection.skipped),
        "commandEquivalent": shlex.join(run_tokens),
        "scraperDatabaseUrl": redact_database_url(settings.scraper_database_url),
        "backendSyncMode": backend_mode,
        "backendTarget": settings.backend_sync_base_url,
        "expectedMutationScope": mutation_scope,
        "risks": risks,
    }


def wizard_require_confirmation(
    *,
    preview: dict[str, Any],
    interactive: bool,
    auto_approve: bool,
) -> None:
    risks = preview["risks"]
    if not risks:
        if auto_approve:
            return
        if not interactive:
            raise CliInputError("wizard non-TTY safe dry-run requires --yes")
        return

    if not interactive:
        raise CliInputError(
            "wizard non-TTY cannot bypass risk confirmation. Use interactive TTY for this run."
        )
    confirmation = wizard_prompt_text("Type YES to continue", default="")
    if confirmation != "YES":
        raise CliInputError("confirmation rejected; wizard run cancelled")


def wizard_wrap_pipeline_result(
    *,
    mode: str,
    preview: dict[str, Any],
    run_result: dict[str, Any],
) -> dict[str, Any]:
    source_counts: dict[str, dict[str, int]] = {}
    for source_row in run_result.get("sources", []):
        source_name = source_row.get("source")
        counts = source_row.get("counts")
        if not isinstance(source_name, str) or not isinstance(counts, dict):
            continue
        aggregate = source_counts.setdefault(
            source_name,
            {"fetched": 0, "parsed": 0, "normalized": 0, "persisted": 0, "skipped": 0},
        )
        for key in aggregate:
            value = counts.get(key)
            if isinstance(value, int):
                aggregate[key] += value
    run_id = run_result.get("runId")
    env_file = preview.get("envFile")
    verify_command = (
        (
            f"PYTHONPATH=src uv run python -m cli.pipeline verify --run-id {run_id} "
            f"--env-file {env_file}"
        )
        if isinstance(run_id, str) and run_id and isinstance(env_file, str) and env_file
        else None
    )
    return {
        "check": "pipeline-wizard",
        "status": run_result.get("status", "fail"),
        "mode": mode,
        "summary": preview,
        "result": run_result,
        "friendly": {
            "status": run_result.get("runStatus"),
            "runId": run_id,
            "sourceCounts": source_counts,
            "skippedSources": run_result.get("skippedSources", []),
            "nextSuggestedAction": (
                "Review failed/skipped sources before execute run"
                if run_result.get("status") != "ok"
                else "Run verify for deterministic evidence"
            ),
            "verifyCommand": verify_command,
        },
    }


def wizard_emit_summary(preview: dict[str, Any]) -> None:
    print("Wizard summary:", file=sys.stderr)
    print(json.dumps(preview, indent=2, sort_keys=True), file=sys.stderr)


def wizard_wrap_read_result(*, mode: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "check": "pipeline-wizard",
        "status": result.get("status", "fail"),
        "mode": mode,
        "result": result,
        "friendly": {
            "status": result.get("status"),
            "runId": result.get("runId"),
            "nextSuggestedAction": (
                "Inspect failed checks and rerun with corrected inputs"
                if result.get("status") != "ok"
                else "Capture output as verification evidence"
            ),
        },
    }


def build_run_command_tokens(args: argparse.Namespace) -> list[str]:
    tokens = ["python", "-m", "cli.pipeline", "run"]
    tokens.extend(["--stage", args.stage])
    tokens.extend(["--source", args.source])
    if args.limit is not None:
        tokens.extend(["--limit", str(args.limit)])
    for keyword in args.keyword or []:
        tokens.extend(["--keyword", keyword])
    if args.keywords:
        tokens.extend(["--keywords", args.keywords])
    if args.latest:
        tokens.append("--latest")
    if args.recency_days is not None:
        tokens.extend(["--recency-days", str(args.recency_days)])
    if args.env_file:
        tokens.extend(["--env-file", args.env_file])
    if args.fixture_root:
        tokens.extend(["--fixture-root", args.fixture_root])
    if args.run_id:
        tokens.extend(["--run-id", args.run_id])
    tokens.append("--execute" if args.execute else "--dry-run")
    return tokens


def wizard_prompt_choice(prompt: str, choices: Sequence[str], *, default: str) -> str:
    if default not in choices:
        raise CliInputError(f"internal wizard error: default '{default}' is not in choices")
    options = ", ".join(f"{index + 1}:{choice}" for index, choice in enumerate(choices))
    while True:
        raw = wizard_prompt_text(f"{prompt} ({options})", default=str(choices.index(default) + 1))
        if raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(choices):
                return choices[index]
        normalized = raw.strip().lower()
        for choice in choices:
            if normalized == choice.lower():
                return choice
        print(f"Invalid choice '{raw}'.", file=sys.stderr)


def wizard_prompt_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = wizard_prompt_text(f"{prompt} ({suffix})", default="" if not default else "y").lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer yes or no.", file=sys.stderr)


def wizard_prompt_int(prompt: str, *, default: int) -> int:
    while True:
        raw = wizard_prompt_text(prompt, default=str(default))
        try:
            value = int(raw)
        except ValueError:
            print("Input must be an integer.", file=sys.stderr)
            continue
        if value <= 0:
            print("Input must be greater than zero.", file=sys.stderr)
            continue
        return value


def wizard_prompt_text(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    print(f"{prompt}{suffix}: ", end="", file=sys.stderr)
    try:
        raw = input()
    except EOFError as exc:
        raise CliInputError("interactive input ended unexpectedly (EOF)") from exc
    except OSError as exc:
        raise CliInputError("interactive input is unavailable in this environment") from exc
    value = raw.strip()
    if not value and default is not None:
        return default
    if not value:
        raise CliInputError(f"{prompt} must not be empty")
    return value


async def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    source_selection = select_sources(
        source=args.source,
        settings=settings,
        execute=args.execute,
    )
    fixture_root = Path(args.fixture_root)
    fixture_check = fixture_availability(source_selection.requested, fixture_root=fixture_root)
    migration_check = migration_target_check()
    backend_mode = backend_sync_mode(settings, execute=args.execute)

    checks = [
        {"name": "env", "passed": True},
        {"name": "migrationTarget", "passed": migration_check["status"] == "ok"},
        {
            "name": "sourceSelection",
            "passed": bool(source_selection.executed),
        },
        {"name": "fixtures", "passed": fixture_check["status"] == "ok"},
        {"name": "backendSyncMode", "passed": backend_mode["status"] == "ok"},
        {"name": "secretRedaction", "passed": True},
    ]
    failed = sum(1 for check in checks if not check["passed"])
    return {
        "check": "pipeline-preflight",
        "status": "ok" if failed == 0 else "fail",
        "mode": "execute" if args.execute else "dry-run",
        "stage": args.stage,
        "source": args.source,
        "requestedSources": list(source_selection.requested),
        "executedSources": list(source_selection.executed),
        "skippedSources": list(source_selection.skipped),
        "env": {
            "appEnv": settings.app_env.value,
            "port": settings.port,
            "backendSyncEnabled": settings.backend_sync_enabled,
            "aiEnrichmentEnabled": settings.ai_enrichment_enabled,
        },
        "migrationTarget": migration_check,
        "fixtures": fixture_check,
        "backendSyncMode": backend_mode,
        "redactedEvidencePreview": {
            "scraperDatabaseUrl": redact_database_url(settings.scraper_database_url),
            "backendDatabaseUrl": redact_database_url(settings.backend_database_url),
            "backendBaseUrl": settings.backend_sync_base_url,
            "jobstreetTokenConfigured": settings.jobstreet_bearer_token is not None,
        },
        "checks": checks,
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


async def run_staging_report(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.env_file)
    scraper_database_url = args.scraper_database_url or settings.scraper_database_url
    scraper_engine = create_engine(to_sync_url(scraper_database_url), pool_pre_ping=True)

    try:
        with Session(scraper_engine) as scraper_session:
            report = build_staging_report(
                scraper_session,
                run_id=args.run_id,
                sample_per_source=args.sample_per_source,
            )
    finally:
        scraper_engine.dispose()

    backend_database_url = args.backend_database_url or settings.backend_database_url
    if backend_database_url:
        backend_engine = create_engine(to_sync_url(backend_database_url), pool_pre_ping=True)
        try:
            with Session(backend_engine) as backend_session:
                report["backendDatabaseConsistency"] = verify_backend_database_consistency(
                    backend_session
                )
        finally:
            backend_engine.dispose()
    else:
        report["backendDatabaseConsistency"] = {
            "status": "skipped",
            "reason": "backend database URL is not configured",
        }

    backend_base_url = args.backend_base_url or settings.backend_sync_base_url
    backend_token = args.backend_token
    if backend_token is None and settings.backend_sync_service_token is not None:
        backend_token = settings.backend_sync_service_token.get_secret_value()
    if backend_base_url:
        report["backendApiReadCheck"] = await verify_backend_read_paths(
            run_id=args.run_id,
            source_targets=report["sourceTargets"],
            backend_base_url=backend_base_url,
            backend_token=backend_token,
            timeout_seconds=settings.backend_sync_timeout_seconds,
            sample_per_source=args.sample_per_source,
        )
    else:
        report["backendApiReadCheck"] = {
            "status": "skipped",
            "reason": "backend base URL is not configured",
        }

    report["gates"] = evaluate_staging_gates(
        report,
        stage_p95_threshold_ms=args.stage_p95_threshold_ms,
        ai_p95_threshold_ms=args.ai_p95_threshold_ms,
        sync_p95_threshold_ms=args.sync_p95_threshold_ms,
        retry_threshold=args.retry_threshold,
        glints_partial_min_rate=args.glints_partial_min_rate,
        glints_partial_max_rate=args.glints_partial_max_rate,
    )
    invariant_failed = report.get("invariants", {}).get("failed", 0)
    report["status"] = "ok" if report["gates"]["failed"] == 0 and invariant_failed == 0 else "fail"
    return report


def build_staging_report(
    session: Session,
    *,
    run_id: str,
    sample_per_source: int,
) -> dict[str, Any]:
    run_ids = stage_run_ids(run_id)
    runs = list(
        session.scalars(
            select(ScrapeRun)
            .where(ScrapeRun.id.in_(run_ids))
            .order_by(ScrapeRun.started_at.asc(), ScrapeRun.id.asc())
        ).all()
    )
    run_by_id = {run.id: run for run in runs}
    stage_id_map = stage_id_map_from(run_ids)

    raw_jobs = list(
        session.scalars(
            select(RawJob)
            .where(RawJob.scrape_run_id.in_(run_ids))
            .order_by(RawJob.source_platform.asc(), RawJob.external_id.asc())
        ).all()
    )
    raw_job_ids = [job.id for job in raw_jobs]
    normalized_jobs: list[NormalizedJob] = []
    if raw_job_ids:
        normalized_jobs = list(
            session.scalars(
                select(NormalizedJob)
                .where(NormalizedJob.raw_job_id.in_(raw_job_ids))
                .order_by(NormalizedJob.source_platform.asc(), NormalizedJob.external_id.asc())
            ).all()
        )
    normalized_job_ids = [job.id for job in normalized_jobs]

    sync_events = list(
        session.scalars(
            select(SyncEvent)
            .where(SyncEvent.scrape_run_id.in_(run_ids))
            .order_by(SyncEvent.attempted_at.asc(), SyncEvent.id.asc())
        ).all()
    )
    handoff_events = list(
        session.scalars(
            select(NotificationHandoffEvent)
            .where(NotificationHandoffEvent.scrape_run_id.in_(run_ids))
            .order_by(
                NotificationHandoffEvent.attempted_at.asc(),
                NotificationHandoffEvent.id.asc(),
            )
        ).all()
    )
    quarantine_rows = list(
        session.scalars(
            select(NormalizationQuarantine)
            .where(NormalizationQuarantine.scrape_run_id.in_(run_ids))
            .order_by(NormalizationQuarantine.created_at.asc(), NormalizationQuarantine.id.asc())
        ).all()
    )

    ai_logs: list[AIRequestLog] = []
    skill_rows: list[JobSkillStaging] = []
    requirement_rows: list[JobRequirementStaging] = []
    if normalized_job_ids:
        ai_logs = list(
            session.scalars(
                select(AIRequestLog)
                .where(AIRequestLog.normalized_job_id.in_(normalized_job_ids))
                .order_by(AIRequestLog.created_at.asc(), AIRequestLog.id.asc())
            ).all()
        )
        skill_rows = list(
            session.scalars(
                select(JobSkillStaging).where(
                    JobSkillStaging.normalized_job_id.in_(normalized_job_ids)
                )
            ).all()
        )
        requirement_rows = list(
            session.scalars(
                select(JobRequirementStaging).where(
                    JobRequirementStaging.normalized_job_id.in_(normalized_job_ids)
                )
            ).all()
        )

    stage_jobs = list(
        session.scalars(
            select(StageJob)
            .where(StageJob.scrape_run_id.in_(run_ids))
            .order_by(StageJob.created_at.asc(), StageJob.id.asc())
        ).all()
    )

    run_skipped = sum(run_summary_value(run, "skipped") for run in runs)
    sync_sent = [event for event in sync_events if event.status == "sent"]
    sync_failed = [event for event in sync_events if event.status in {"failed", "dead-letter"}]
    handoff_failed = [
        event for event in handoff_events if event.status in {"failed", "dead-letter"}
    ]
    ai_failed = [log for log in ai_logs if log.status != "succeeded"]
    ai_retries = [log.retry_count for log in ai_logs]
    ai_latencies = [log.latency_ms for log in ai_logs if isinstance(log.latency_ms, int)]

    enriched_job_ids = {
        job_id
        for job_id in (
            *[log.normalized_job_id for log in ai_logs if log.status == "succeeded"],
            *[row.normalized_job_id for row in skill_rows],
            *[row.normalized_job_id for row in requirement_rows],
        )
        if isinstance(job_id, str)
    }

    sync_latencies = [
        duration_ms_between(event.attempted_at, event.completed_at)
        for event in sync_events
        if event.completed_at is not None
    ]
    sync_latencies = [value for value in sync_latencies if value is not None]

    stage_timings = {
        stage: stage_duration_entry(stage, stage_run_id, run_by_id)
        for stage, stage_run_id in stage_id_map.items()
    }
    stage_latency_values = [
        entry["durationMs"]
        for entry in stage_timings.values()
        if isinstance(entry["durationMs"], int)
    ]
    stage_p95 = percentile_nearest_rank(stage_latency_values, 95)
    ai_p95 = percentile_nearest_rank(ai_latencies, 95)
    sync_p95 = percentile_nearest_rank(sync_latencies, 95)

    raw_identity_counts = Counter((job.source_platform, job.external_id) for job in raw_jobs)
    normalized_identity_counts = Counter(
        (job.source_platform, job.external_id) for job in normalized_jobs
    )
    active_without_last_seen = [
        job.id
        for job in normalized_jobs
        if job.status == CanonicalJobStatus.ACTIVE.value and job.last_seen_at is None
    ]
    queue_backlog = Counter(job.status for job in stage_jobs)
    quarantine_by_reason = Counter(row.error_category for row in quarantine_rows)
    source_targets = source_targets_from_sync(sync_sent, sample_per_source=sample_per_source)
    partial_data = partial_data_summary(normalized_jobs)
    stage_runs = stage_runs_by_name(run_by_id=run_by_id, stage_id_map=stage_id_map)
    sync_reason = infer_sync_zero_sent_reason(
        sync_run=stage_runs.get("sync"),
        enrich_run=stage_runs.get("enrich"),
        normalized_count=len(normalized_jobs),
        sync_events=sync_events,
    )
    notify_reason = infer_notify_zero_sent_reason(
        notify_run=stage_runs.get("notify"),
        sync_sent_count=len(sync_sent),
        handoff_events=handoff_events,
    )
    invariants = build_strict_invariant_checks(
        stage_runs=stage_runs,
        raw_jobs=raw_jobs,
        normalized_jobs=normalized_jobs,
        quarantine_rows=quarantine_rows,
        ai_logs=ai_logs,
        sync_events=sync_events,
        handoff_events=handoff_events,
        sync_zero_sent_reason=sync_reason,
        notify_zero_sent_reason=notify_reason,
    )

    return {
        "check": "staging-report",
        "runId": run_id,
        "stageRunIds": stage_id_map,
        "stageStatuses": stage_status_summary(stage_runs),
        "runRowsFound": len(runs),
        "stageCounts": {
            "fetched": len(raw_jobs),
            "rawPersisted": len(raw_jobs),
            "normalized": len(normalized_jobs),
            "enriched": len(enriched_job_ids),
            "syncUpserted": len(sync_sent),
            "skipped": run_skipped,
            "quarantined": len(quarantine_rows),
            "errors": len(sync_failed) + len(handoff_failed) + len(ai_failed),
        },
        "latency": {
            "stageDurationsMs": stage_timings,
            "stageP95Ms": stage_p95,
            "aiP95Ms": ai_p95,
            "syncP95Ms": sync_p95,
        },
        "retries": {
            "aiTotalRetries": sum(ai_retries),
            "aiMaxRetryCount": max(ai_retries, default=0),
            "syncFailedEvents": len(sync_failed),
        },
        "queue": {
            "backlogByStatus": dict(sorted(queue_backlog.items())),
            "totalRows": len(stage_jobs),
        },
        "quarantine": {
            "count": len(quarantine_rows),
            "openCount": sum(1 for row in quarantine_rows if row.status == "open"),
            "byReason": dict(sorted(quarantine_by_reason.items())),
        },
        "consistency": {
            "duplicateRawIdentities": duplicate_count(raw_identity_counts),
            "duplicateNormalizedIdentities": duplicate_count(normalized_identity_counts),
            "activeMissingLastSeenAt": len(active_without_last_seen),
            "status": (
                "ok"
                if duplicate_count(raw_identity_counts) == 0
                and duplicate_count(normalized_identity_counts) == 0
                and not active_without_last_seen
                else "fail"
            ),
        },
        "syncOutcome": {
            "attempted": len(sync_events),
            "sent": len(sync_sent),
            "failed": len(sync_failed),
            "zeroSentReason": sync_reason,
        },
        "notifyOutcome": {
            "attempted": len(handoff_events),
            "sent": len(handoff_events) - len(handoff_failed),
            "failed": len(handoff_failed),
            "zeroSentReason": notify_reason,
        },
        "invariants": invariants,
        "partialData": partial_data,
        "sourceTargets": source_targets,
    }


def verify_backend_database_consistency(session: Session) -> dict[str, Any]:
    duplicate_rows = session.execute(
        text(
            """
        SELECT source_platform_id, external_job_id, COUNT(*) AS total
        FROM job_listings
        GROUP BY source_platform_id, external_job_id
        HAVING COUNT(*) > 1
        """
        )
    ).all()
    orphan_company = session.execute(
        text(
            """
        SELECT COUNT(*) AS total
        FROM job_listings jl
        LEFT JOIN companies c ON c.id = jl.company_id
        WHERE c.id IS NULL
        """
        )
    ).scalar_one()
    orphan_job_skill = session.execute(
        text(
            """
        SELECT COUNT(*) AS total
        FROM job_skills js
        LEFT JOIN skills s ON s.id = js.skill_id
        WHERE s.id IS NULL
        """
        )
    ).scalar_one()
    orphan_job_requirement = session.execute(
        text(
            """
        SELECT COUNT(*) AS total
        FROM job_requirements jr
        LEFT JOIN job_listings jl ON jl.id = jr.job_listing_id
        WHERE jl.id IS NULL
        """
        )
    ).scalar_one()
    active_missing_last_seen = session.execute(
        text(
            """
        SELECT COUNT(*) AS total
        FROM job_listings
        WHERE status = 'ACTIVE' AND last_seen_at IS NULL
        """
        )
    ).scalar_one()
    duplicate_count_rows = len(duplicate_rows)
    status = (
        "ok"
        if duplicate_count_rows == 0
        and orphan_company == 0
        and orphan_job_skill == 0
        and orphan_job_requirement == 0
        and active_missing_last_seen == 0
        else "fail"
    )
    return {
        "status": status,
        "duplicateSourceExternalRows": duplicate_count_rows,
        "orphanCompanyRefs": orphan_company,
        "orphanSkillRefs": orphan_job_skill,
        "orphanRequirementRefs": orphan_job_requirement,
        "activeMissingLastSeenAt": active_missing_last_seen,
    }


async def verify_backend_read_paths(
    *,
    run_id: str,
    source_targets: list[dict[str, Any]],
    backend_base_url: str,
    backend_token: str | None,
    timeout_seconds: float,
    sample_per_source: int,
) -> dict[str, Any]:
    origin = origin_base_url(backend_base_url)
    headers: dict[str, str] = {}
    if backend_token:
        headers["authorization"] = f"Bearer {backend_token}"
    checks: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(
            base_url=origin,
            timeout=httpx.Timeout(timeout_seconds),
            headers=headers,
        ) as client:
            for target in source_targets:
                source = str(target["source"])
                list_response = await client.get(
                    "/api/v1/jobs",
                    params={"sourcePlatform": source, "limit": sample_per_source},
                )
                list_ok = 200 <= list_response.status_code < 300
                list_body = safe_json_dict(list_response)
                jobs = jobs_from_list_body(list_body)

                detail_ok = False
                detail_status = None
                detail_id = None
                if jobs:
                    first_job = jobs[0]
                    detail_id = first_job.get("id") if isinstance(first_job, dict) else None
                    if isinstance(detail_id, str) and detail_id:
                        detail_response = await client.get(f"/api/v1/jobs/{detail_id}")
                        detail_status = detail_response.status_code
                        detail_ok = 200 <= detail_response.status_code < 300

                checks.append(
                    {
                        "source": source,
                        "listStatusCode": list_response.status_code,
                        "listOk": list_ok,
                        "listSampleCount": len(jobs),
                        "detailId": detail_id,
                        "detailStatusCode": detail_status,
                        "detailOk": detail_ok if detail_id else False,
                    }
                )
    except httpx.HTTPError as exc:
        return {
            "status": "fail",
            "runId": run_id,
            "baseUrl": origin,
            "reason": exc.__class__.__name__,
            "message": str(exc),
            "checks": checks,
        }

    failed = [item for item in checks if not item["listOk"] or not item["detailOk"]]
    return {
        "status": "ok" if not failed else "fail",
        "runId": run_id,
        "baseUrl": origin,
        "checks": checks,
        "failedChecks": len(failed),
    }


def evaluate_staging_gates(
    report: dict[str, Any],
    *,
    stage_p95_threshold_ms: int | None,
    ai_p95_threshold_ms: int | None,
    sync_p95_threshold_ms: int | None,
    retry_threshold: int | None,
    glints_partial_min_rate: float,
    glints_partial_max_rate: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    stage_p95 = report.get("latency", {}).get("stageP95Ms")
    ai_p95 = report.get("latency", {}).get("aiP95Ms")
    sync_p95 = report.get("latency", {}).get("syncP95Ms")
    ai_retries = report.get("retries", {}).get("aiMaxRetryCount")

    checks.append(
        gate_entry(
            name="consistency",
            passed=report.get("consistency", {}).get("status") == "ok",
            actual=report.get("consistency", {}),
            expected="no duplicate identities and all active jobs have lastSeenAt",
        )
    )
    checks.append(
        gate_entry(
            name="backendDatabaseConsistency",
            passed=report.get("backendDatabaseConsistency", {}).get("status") in {"ok", "skipped"},
            actual=report.get("backendDatabaseConsistency", {}),
            expected="no orphan relation and no duplicate source identity rows",
        )
    )
    checks.append(
        gate_entry(
            name="backendApiReadCheck",
            passed=report.get("backendApiReadCheck", {}).get("status") in {"ok", "skipped"},
            actual=report.get("backendApiReadCheck", {}).get("status"),
            expected="list and detail read paths succeed for each source sample",
        )
    )
    checks.append(
        glints_partial_gate(
            report,
            min_rate=glints_partial_min_rate,
            max_rate=glints_partial_max_rate,
        )
    )

    if stage_p95_threshold_ms is not None and isinstance(stage_p95, int):
        checks.append(
            gate_entry(
                name="stageP95Threshold",
                passed=stage_p95 <= stage_p95_threshold_ms,
                actual=stage_p95,
                expected=f"<= {stage_p95_threshold_ms}",
            )
        )
    if ai_p95_threshold_ms is not None and isinstance(ai_p95, int):
        checks.append(
            gate_entry(
                name="aiP95Threshold",
                passed=ai_p95 <= ai_p95_threshold_ms,
                actual=ai_p95,
                expected=f"<= {ai_p95_threshold_ms}",
            )
        )
    if sync_p95_threshold_ms is not None and isinstance(sync_p95, int):
        checks.append(
            gate_entry(
                name="syncP95Threshold",
                passed=sync_p95 <= sync_p95_threshold_ms,
                actual=sync_p95,
                expected=f"<= {sync_p95_threshold_ms}",
            )
        )
    if retry_threshold is not None and isinstance(ai_retries, int):
        checks.append(
            gate_entry(
                name="retryThreshold",
                passed=ai_retries <= retry_threshold,
                actual=ai_retries,
                expected=f"<= {retry_threshold}",
            )
        )

    passed = sum(1 for check in checks if check["passed"])
    failed = sum(1 for check in checks if not check["passed"])
    return {"checks": checks, "passed": passed, "failed": failed}


def gate_entry(*, name: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {"name": name, "passed": passed, "actual": actual, "expected": expected}


def glints_partial_gate(
    report: dict[str, Any],
    *,
    min_rate: float,
    max_rate: float,
) -> dict[str, Any]:
    by_source = report.get("partialData", {}).get("bySource", {})
    if not isinstance(by_source, dict):
        return gate_entry(
            name="glintsPartialRate",
            passed=True,
            actual="missing",
            expected=f"between {min_rate} and {max_rate} when glints data exists",
        )
    glints = by_source.get("glints")
    if not isinstance(glints, dict):
        return gate_entry(
            name="glintsPartialRate",
            passed=True,
            actual="skipped",
            expected=f"between {min_rate} and {max_rate} when glints data exists",
        )
    total = glints.get("total")
    rate = glints.get("partialRate")
    if not isinstance(total, int) or total <= 0:
        return gate_entry(
            name="glintsPartialRate",
            passed=True,
            actual="skipped",
            expected=f"between {min_rate} and {max_rate} when glints data exists",
        )
    passed = isinstance(rate, float) and min_rate <= rate <= max_rate
    return gate_entry(
        name="glintsPartialRate",
        passed=passed,
        actual=rate,
        expected=f"between {min_rate} and {max_rate}",
    )


def stage_runs_by_name(
    *,
    run_by_id: dict[str, ScrapeRun],
    stage_id_map: dict[str, str],
) -> dict[str, ScrapeRun | None]:
    return {stage: run_by_id.get(run_id) for stage, run_id in stage_id_map.items()}


def run_summary_counts(run: ScrapeRun | None) -> dict[str, int]:
    if run is None:
        return {}
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    summary = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    result: dict[str, int] = {}
    for key in ("fetched", "parsed", "normalized", "persisted", "skipped"):
        value = counts.get(key)
        if isinstance(value, int):
            result[key] = value
    return result


def stage_status_summary(stage_runs: dict[str, ScrapeRun | None]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for stage_name, run in stage_runs.items():
        if run is None:
            summary[stage_name] = {"runId": None, "status": "missing"}
            continue
        summary[stage_name] = {
            "runId": run.id,
            "status": run.status,
            "errorCategory": run.error_category,
            "errorMessage": redact_text(run.error_message or "") if run.error_message else None,
            "counts": run_summary_counts(run),
        }
    return summary


def contains_sensitive_fragment(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if "postgresql://" in lowered or "postgresql+asyncpg://" in lowered:
        return True
    if "cookie" in lowered and "=" in lowered:
        return True
    if "authorization" in lowered and "bearer" in lowered:
        return True
    redacted = redact_text(value)
    return redacted != value


def infer_sync_zero_sent_reason(
    *,
    sync_run: ScrapeRun | None,
    enrich_run: ScrapeRun | None,
    normalized_count: int,
    sync_events: Sequence[SyncEvent],
) -> str | None:
    sync_sent = sum(1 for event in sync_events if event.status == "sent")
    if sync_sent > 0:
        return None
    if sync_run is None:
        return "sync stage row missing"
    if sync_run.status != "completed":
        if sync_run.error_category:
            return f"sync stage {sync_run.status}: {sync_run.error_category}"
        return f"sync stage {sync_run.status}"

    sync_counts = run_summary_counts(sync_run)
    enrich_counts = run_summary_counts(enrich_run)
    sync_attempted = sync_counts.get("fetched", 0)
    sync_failed = sync_counts.get("skipped", 0)
    sync_persisted = sync_counts.get("persisted", 0)
    enrich_persisted = enrich_counts.get("persisted", 0)
    enrich_failed = enrich_counts.get("skipped", 0)

    if sync_persisted > 0:
        return None
    if sync_failed > 0:
        return "all sync attempts failed"
    if normalized_count == 0:
        return "no normalized rows available for sync"
    if enrich_failed > 0 and enrich_persisted == 0:
        return "all enrichment items failed"
    if sync_attempted == 0:
        return "no eligible jobs for sync"
    return None


def infer_notify_zero_sent_reason(
    *,
    notify_run: ScrapeRun | None,
    sync_sent_count: int,
    handoff_events: Sequence[NotificationHandoffEvent],
) -> str | None:
    handoff_sent = sum(1 for event in handoff_events if event.status == "sent")
    if handoff_sent > 0:
        return None
    if notify_run is None:
        return "notify-handoff stage row missing"
    if notify_run.status != "completed":
        if notify_run.error_category:
            return f"notify-handoff stage {notify_run.status}: {notify_run.error_category}"
        return f"notify-handoff stage {notify_run.status}"

    notify_counts = run_summary_counts(notify_run)
    notify_attempted = notify_counts.get("fetched", 0)
    notify_failed = notify_counts.get("skipped", 0)
    notify_persisted = notify_counts.get("persisted", 0)

    if notify_persisted > 0:
        return None
    if notify_failed > 0:
        return "all notify-handoff attempts failed"
    if sync_sent_count == 0:
        return "no sent sync events available for handoff"
    if notify_attempted == 0:
        return "no eligible handoff events"
    return None


def build_strict_invariant_checks(
    *,
    stage_runs: dict[str, ScrapeRun | None],
    raw_jobs: Sequence[RawJob],
    normalized_jobs: Sequence[NormalizedJob],
    quarantine_rows: Sequence[NormalizationQuarantine],
    ai_logs: Sequence[AIRequestLog],
    sync_events: Sequence[SyncEvent],
    handoff_events: Sequence[NotificationHandoffEvent],
    sync_zero_sent_reason: str | None,
    notify_zero_sent_reason: str | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    missing_stage_rows = [stage for stage, run in stage_runs.items() if run is None]
    checks.append(
        gate_entry(
            name="stageRowsPresent",
            passed=not missing_stage_rows,
            actual=missing_stage_rows,
            expected="scrape, normalize, enrich, sync, and notify stage rows exist",
        )
    )

    raw_count = len(raw_jobs)
    normalized_count = len(normalized_jobs)
    quarantine_count = len(quarantine_rows)
    normalize_run = stage_runs.get("normalize")
    normalize_skipped = run_summary_counts(normalize_run).get("skipped", 0)
    raw_gap = raw_count - normalized_count
    normalize_gap_has_reason = raw_gap <= 0 or quarantine_count > 0 or normalize_skipped > 0
    checks.append(
        gate_entry(
            name="normalizeCountInvariant",
            passed=raw_gap >= 0 and normalize_gap_has_reason,
            actual={
                "rawRows": raw_count,
                "normalizedRows": normalized_count,
                "quarantineRows": quarantine_count,
                "normalizeSkipped": normalize_skipped,
                "gap": raw_gap,
            },
            expected="rawRows >= normalizedRows and any gap has quarantine or skipped evidence",
        )
    )

    unsafe_quarantine_rows = [
        row.id
        for row in quarantine_rows
        if not row.error_category
        or not row.error_message
        or contains_sensitive_fragment(row.error_message)
    ]
    checks.append(
        gate_entry(
            name="quarantineSafeErrorEvidence",
            passed=not unsafe_quarantine_rows,
            actual={"unsafeRowIds": unsafe_quarantine_rows, "total": len(quarantine_rows)},
            expected="quarantine rows have safe category and redacted message",
        )
    )

    enrich_run = stage_runs.get("enrich")
    enrich_failed_or_partial = enrich_run is not None and enrich_run.status in {"failed", "partial"}
    ai_failed = [log for log in ai_logs if log.status != "succeeded"]
    enrich_failure_has_evidence = not enrich_failed_or_partial or bool(ai_failed)
    checks.append(
        gate_entry(
            name="enrichFailureHasAiEvidence",
            passed=enrich_failure_has_evidence,
            actual={
                "enrichStatus": enrich_run.status if enrich_run is not None else "missing",
                "failedAiLogs": len(ai_failed),
            },
            expected="failed or partial enrich stage includes failed AI request evidence",
        )
    )

    sync_run = stage_runs.get("sync")
    sync_completed_zero_sent_without_reason = (
        sync_run is not None
        and sync_run.status == "completed"
        and sum(1 for event in sync_events if event.status == "sent") == 0
        and sync_zero_sent_reason is None
    )
    checks.append(
        gate_entry(
            name="syncZeroSentHasReason",
            passed=not sync_completed_zero_sent_without_reason,
            actual={
                "syncStatus": sync_run.status if sync_run is not None else "missing",
                "sent": sum(1 for event in sync_events if event.status == "sent"),
                "reason": sync_zero_sent_reason,
            },
            expected="completed sync with zero sent has explicit reason",
        )
    )

    notify_run = stage_runs.get("notify")
    notify_completed_zero_sent_without_reason = (
        notify_run is not None
        and notify_run.status == "completed"
        and sum(1 for event in handoff_events if event.status == "sent") == 0
        and notify_zero_sent_reason is None
    )
    checks.append(
        gate_entry(
            name="notifyZeroSentHasReason",
            passed=not notify_completed_zero_sent_without_reason,
            actual={
                "notifyStatus": notify_run.status if notify_run is not None else "missing",
                "sent": sum(1 for event in handoff_events if event.status == "sent"),
                "reason": notify_zero_sent_reason,
            },
            expected="completed notify-handoff with zero sent has explicit reason",
        )
    )

    failed_stage_without_error = []
    for stage_name, run in stage_runs.items():
        if run is None or run.status not in {"failed", "partial"}:
            continue
        summary_errors = run_summary_errors(run)
        has_row_error = bool(run.error_category or run.error_message)
        if not has_row_error and not summary_errors:
            failed_stage_without_error.append(stage_name)
    checks.append(
        gate_entry(
            name="failedStageHasErrorEvidence",
            passed=not failed_stage_without_error,
            actual=failed_stage_without_error,
            expected="failed or partial stage rows expose safe error evidence",
        )
    )

    passed = sum(1 for check in checks if check["passed"])
    failed = len(checks) - passed
    return {"checks": checks, "passed": passed, "failed": failed}


def run_summary_errors(run: ScrapeRun) -> list[dict[str, Any]]:
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    summary = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
    errors = summary.get("errors")
    if not isinstance(errors, list):
        return []
    safe_errors: list[dict[str, Any]] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        if isinstance(message, str):
            item = {**item, "message": redact_text(message)}
        safe_errors.append(item)
    return safe_errors


def stage_id_map_from(run_ids: list[str]) -> dict[str, str]:
    stages = ("scrape", "normalize", "enrich", "sync", "notify")
    return {stage: run_id for stage, run_id in zip(stages, run_ids, strict=True)}


def stage_duration_entry(
    stage: str,
    run_id: str,
    run_by_id: dict[str, ScrapeRun],
) -> dict[str, Any]:
    run = run_by_id.get(run_id)
    if run is None:
        return {"runId": run_id, "status": "missing", "durationMs": None}
    return {
        "runId": run.id,
        "status": run.status,
        "durationMs": duration_ms_between(run.started_at, run.finished_at),
    }


def duration_ms_between(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    if started_at is None or finished_at is None:
        return None
    delta = finished_at - started_at
    return int(delta.total_seconds() * 1000)


def percentile_nearest_rank(values: Sequence[int], percentile: int) -> int | None:
    clean = sorted(value for value in values if isinstance(value, int))
    if not clean:
        return None
    rank = max(1, math.ceil((percentile / 100) * len(clean)))
    return clean[rank - 1]


def source_targets_from_sync(
    sync_sent: Sequence[SyncEvent],
    *,
    sample_per_source: int,
) -> list[dict[str, Any]]:
    counts = Counter(event.source_platform for event in sync_sent)
    return [
        {
            "source": source,
            "sentCount": count,
            "sample": min(count, sample_per_source),
        }
        for source, count in sorted(counts.items())
    ]


def partial_data_summary(normalized_jobs: Sequence[NormalizedJob]) -> dict[str, Any]:
    by_source: dict[str, dict[str, float | int]] = {}
    total_partial = 0
    for job in normalized_jobs:
        source = job.source_platform
        state = detail_completeness_state(job)
        source_entry = by_source.setdefault(
            source,
            {
                "total": 0,
                "partial": 0,
                "complete": 0,
                "unknown": 0,
                "partialRate": 0.0,
            },
        )
        source_entry["total"] += 1
        if state == "partial":
            source_entry["partial"] += 1
            total_partial += 1
        elif state == "complete":
            source_entry["complete"] += 1
        else:
            source_entry["unknown"] += 1

    for source_entry in by_source.values():
        total = int(source_entry["total"])
        partial = int(source_entry["partial"])
        source_entry["partialRate"] = round(partial / total, 4) if total else 0.0

    return {
        "totalPartial": total_partial,
        "totalNormalized": len(normalized_jobs),
        "bySource": {source: by_source[source] for source in sorted(by_source)},
    }


def detail_completeness_state(job: NormalizedJob) -> str:
    payload = job.normalized_payload if isinstance(job.normalized_payload, dict) else {}
    presentation = payload.get("presentation")
    if not isinstance(presentation, dict):
        return "unknown"
    source_labels = presentation.get("source_labels")
    if not isinstance(source_labels, dict):
        return "unknown"

    explicit = source_labels.get("detailCompleteness")
    if isinstance(explicit, str):
        normalized = explicit.strip().lower()
        if normalized in {"partial", "complete", "unknown"}:
            return normalized

    coverage = source_labels.get("detailCoverage")
    if isinstance(coverage, str):
        normalized = coverage.strip().lower()
        if normalized in {"unavailable", "list-only"}:
            return "partial"
        if normalized in {"embedded", "available", "full"}:
            return "complete"
    return "unknown"


def run_summary_value(run: ScrapeRun, key: str) -> int:
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    summary = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    value = counts.get(key)
    return value if isinstance(value, int) else 0


def safe_json_dict(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def jobs_from_list_body(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


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
    normalized_job_ids = [job.id for job in normalized_jobs]
    quarantine_rows = list(
        session.scalars(
            select(NormalizationQuarantine).where(
                NormalizationQuarantine.scrape_run_id.in_(run_ids)
            )
        ).all()
    )
    ai_logs: list[AIRequestLog] = []
    if normalized_job_ids:
        ai_logs = list(
            session.scalars(
                select(AIRequestLog).where(AIRequestLog.normalized_job_id.in_(normalized_job_ids))
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
    run_by_id = {run.id: run for run in runs}
    stage_id_map = stage_id_map_from(run_ids)
    stage_runs = stage_runs_by_name(run_by_id=run_by_id, stage_id_map=stage_id_map)
    sync_sent_count = sum(1 for event in sync_events if event.status == "sent")
    sync_zero_sent_reason = infer_sync_zero_sent_reason(
        sync_run=stage_runs.get("sync"),
        enrich_run=stage_runs.get("enrich"),
        normalized_count=len(normalized_jobs),
        sync_events=sync_events,
    )
    notify_zero_sent_reason = infer_notify_zero_sent_reason(
        notify_run=stage_runs.get("notify"),
        sync_sent_count=sync_sent_count,
        handoff_events=handoff_events,
    )
    invariants = build_strict_invariant_checks(
        stage_runs=stage_runs,
        raw_jobs=raw_jobs,
        normalized_jobs=normalized_jobs,
        quarantine_rows=quarantine_rows,
        ai_logs=ai_logs,
        sync_events=sync_events,
        handoff_events=handoff_events,
        sync_zero_sent_reason=sync_zero_sent_reason,
        notify_zero_sent_reason=notify_zero_sent_reason,
    )
    status = "ok" if runs and invariants["failed"] == 0 else "fail"

    return {
        "check": "pipeline-verify",
        "status": status,
        "runId": run_id,
        "stageRunIds": run_ids,
        "stageStatuses": stage_status_summary(stage_runs),
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
        "quarantineRows": len(quarantine_rows),
        "aiRequestLogs": len(ai_logs),
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
        "syncOutcome": {
            "sent": sync_sent_count,
            "zeroSentReason": sync_zero_sent_reason,
        },
        "notifyOutcome": {
            "sent": sum(1 for event in handoff_events if event.status == "sent"),
            "zeroSentReason": notify_zero_sent_reason,
        },
        "invariants": invariants,
        "latestMetadata": latest_metadata_summary(raw_jobs),
    }


def stage_run_ids(run_id: str) -> list[str]:
    suffixes = ("scrape", "normalize", "enrich", "sync", "notify")
    base_run_id = base_run_id_without_stage_suffix(run_id)
    return [f"{base_run_id}-{suffix}" for suffix in suffixes]


def scrape_run_id_from_stage_run_id(run_id: str) -> str | None:
    base_run_id = base_run_id_without_stage_suffix(run_id)
    if base_run_id != run_id:
        return f"{base_run_id}-scrape"
    return None


def base_run_id_without_stage_suffix(run_id: str) -> str:
    for suffix in (
        "notify-handoff",
        "notify",
        "normalize",
        "enrich",
        "scrape",
        "sync",
    ):
        marker = f"-{suffix}"
        if run_id.endswith(marker):
            return run_id[: -len(marker)]
    return run_id


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
        source_selection: SourceSelection,
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
        self.source_selection = source_selection
        self.output: dict[str, Any] | None = None
        self.stage_run_ids: dict[str, str] = {}
        self.stage_statuses: dict[str, str] = {}
        self.stage_count_breakdown: dict[str, dict[str, int]] = {}
        self.sync_diagnostics: dict[str, Any] = {}

    def emit_progress(self, message: str) -> None:
        if not self.execute:
            return
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)

    async def run_stage(self, stage: ScheduledStage) -> None:
        stage_value = self.stage
        if self.run_id and stage_value == "full":
            run_id_prefix = self.run_id
        else:
            run_id_prefix = self.run_id
        orchestrator = self.build_orchestrator()
        self.emit_progress(
            "pipeline start "
            f"stage={stage_value} source={self.source} "
            f"keywords={len(self.keywords)} limit={self.limit}"
        )
        if stage_value == "full":
            result = await self.run_full(orchestrator, run_id_prefix=run_id_prefix)
        else:
            self.emit_progress(f"stage start stage={stage_value}")
            result = await orchestrator.run_stage(stage_value, run_id=run_id_prefix)
            self.emit_progress(
                "stage done "
                f"stage={stage_value} status={result.status} "
                f"counts={result.counts.model_dump()}"
            )
            self.stage_statuses = {stage_value: result.status}
            self.stage_count_breakdown = {stage_value: result.counts.model_dump()}
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
            stage_statuses=self.stage_statuses,
            stage_count_breakdown=self.stage_count_breakdown,
            sync_diagnostics=self.sync_diagnostics,
            source_selection=self.source_selection,
        )

    async def run_named_stage(self, stage: str) -> None:
        await self.run_stage(stage_for_guard(stage))

    def build_orchestrator(self) -> PipelineOrchestrator:
        sync_run_id: dict[str, str] = {}
        ai_normalization_client = build_ai_normalization_client(
            self.settings,
            execute=self.execute,
        )
        ai_enrichment_client = build_ai_enrichment_client(
            self.settings,
            execute=self.execute,
        )
        backend_sync_client = build_backend_sync_client(
            self.settings,
            execute=self.execute,
        )
        handoff_client = build_handoff_client(
            self.settings,
            execute=self.execute,
        )

        async def enrich_hook(run_id: str, correlation_id: str) -> RunCounts:
            jobs = self.normalized_jobs_for_stage(run_id)
            if not jobs:
                return RunCounts()

            repository = EnrichmentStagingRepository(self.session)
            if ai_enrichment_client is None:
                for job in jobs:
                    repository.upsert_output(
                        job=job,
                        output=source_enrichment_output_from_job(job),
                        ai_request_log_id=None,
                        source=EnrichmentSource.SOURCE,
                    )
                self.session.commit()
            return RunCounts(
                fetched=len(jobs),
                parsed=len(jobs),
                normalized=len(jobs),
                persisted=len(jobs),
            )

            service = EnrichmentService(
                session=self.session,
                client=ai_enrichment_client,
                config=EnrichmentServiceConfig(
                    provider="openai-compatible",
                    model=self.settings.openai_model or ai_enrichment_client.model,
                    base_url=(
                        str(self.settings.openai_base_url)
                        if self.settings.openai_base_url is not None
                        else None
                    ),
                    batch_size=self.settings.openai_batch_size,
                    max_attempts=max(self.settings.openai_max_retries + 1, 1),
                ),
            )
            succeeded = 0
            failed = 0
            total_jobs = len(jobs)
            self.emit_progress(f"enrich start jobs={total_jobs}")
            for index, job in enumerate(jobs, start=1):
                self.emit_progress(f"enrich job start index={index}/{total_jobs} job_id={job.id}")
                result = await service.enrich_one(job, scrape_run_id=run_id)
                if result.status == "success":
                    succeeded += 1
                else:
                    failed += 1
                self.emit_progress(
                    "enrich job done "
                    f"index={index}/{total_jobs} job_id={job.id} status={result.status}"
                )
            self.session.commit()
            self.emit_progress(
                f"enrich done jobs={total_jobs} succeeded={succeeded} failed={failed}"
            )
            return RunCounts(
                fetched=len(jobs),
                parsed=len(jobs),
                normalized=len(jobs),
                persisted=succeeded,
                skipped=failed,
            )

        async def sync_hook(run_id: str, correlation_id: str) -> RunCounts:
            worker = BackendSyncWorker(
                session=self.session,
                client=backend_sync_client,
                events=SyncEventRepository(self.session),
            )
            max_jobs = self.limit * len(self.source_selection.executed) * len(self.keywords)
            self.emit_progress(f"sync start limit={max_jobs}")
            result = await worker.sync_eligible_jobs(
                scrape_run_id=run_id,
                limit=max_jobs,
                batch_size=min(max_jobs, 100),
            )
            self.session.commit()
            if result.failed:
                self.sync_diagnostics = {"failures": self.sync_failure_summary(run_id)}
                self.emit_progress(
                    "sync failures "
                    f"summary={json.dumps(self.sync_diagnostics['failures'], sort_keys=True)}"
                )
            self.emit_progress(
                f"sync done attempted={result.attempted} sent={result.sent} failed={result.failed}"
            )
            sync_run_id["value"] = run_id
            return RunCounts(fetched=result.attempted, persisted=result.sent, skipped=result.failed)

        async def handoff_hook(run_id: str, correlation_id: str) -> RunCounts:
            worker = RecommendationHandoffWorker(
                session=self.session,
                repository=NotificationHandoffRepository(self.session),
                client=handoff_client,
            )
            self.emit_progress("notify-handoff start")
            result = await worker.handoff_synced_jobs(
                scrape_run_id=sync_run_id.get("value", run_id)
            )
            self.session.commit()
            self.emit_progress(
                "notify-handoff done "
                f"attempted={result.attempted} sent={result.sent} failed={result.failed}"
            )
            return RunCounts(fetched=result.attempted, persisted=result.sent, skipped=result.failed)

        return PipelineOrchestrator(
            sources=pipeline_sources(
                selected_platforms=self.source_selection.executed,
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
            config=PipelineConfig(
                max_concurrency_per_source=self.settings.worker_concurrency,
                ai_normalization_batch_size=self.settings.openai_normalization_batch_size,
                ai_normalization_inter_batch_delay_ms=(
                    self.settings.openai_normalization_inter_batch_delay_ms
                ),
                progress_hook=self.emit_progress if self.execute else None,
            ),
            correlation_id_factory=lambda: "manual-pipeline",
            ai_normalization_client=ai_normalization_client,
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

    def sync_failure_summary(self, run_id: str) -> list[dict[str, Any]]:
        events = list(
            self.session.scalars(
                select(SyncEvent)
                .where(
                    SyncEvent.scrape_run_id == run_id,
                    SyncEvent.status.in_(("failed", "dead-letter")),
                )
                .order_by(SyncEvent.error_category.asc(), SyncEvent.id.asc())
            ).all()
        )
        counts: Counter[tuple[str, int | None, str | None]] = Counter()
        for event in events:
            summary = event.response_summary if isinstance(event.response_summary, dict) else {}
            status_code = summary.get("statusCode")
            endpoint_path = summary.get("endpointPath")
            counts[
                (
                    event.error_category or "unknown",
                    status_code if isinstance(status_code, int) else None,
                    endpoint_path if isinstance(endpoint_path, str) else None,
                )
            ] += 1
        return [
            {
                "category": category,
                "statusCode": status_code,
                "endpointPath": endpoint_path,
                "count": count,
            }
            for (category, status_code, endpoint_path), count in sorted(
                counts.items(),
                key=lambda item: (
                    item[0][0],
                    -1 if item[0][1] is None else item[0][1],
                    item[0][2] or "",
                ),
            )
        ]

    async def run_full(
        self,
        orchestrator: PipelineOrchestrator,
        *,
        run_id_prefix: str | None,
    ) -> PipelineResult:
        self.emit_progress("stage start stage=scrape")
        scrape = await orchestrator.run_scrape(run_id=suffixed_run_id(run_id_prefix, "scrape"))
        self.emit_progress(
            f"stage done stage=scrape status={scrape.status} counts={scrape.counts.model_dump()}"
        )
        self.emit_progress("stage start stage=normalize")
        normalize = await orchestrator.run_normalize(
            run_id=suffixed_run_id(run_id_prefix, "normalize")
        )
        self.emit_progress(
            "stage done "
            f"stage=normalize status={normalize.status} "
            f"counts={normalize.counts.model_dump()}"
        )
        self.emit_progress("stage start stage=enrich")
        enrich = await orchestrator.run_enrich(run_id=suffixed_run_id(run_id_prefix, "enrich"))
        self.emit_progress(
            f"stage done stage=enrich status={enrich.status} counts={enrich.counts.model_dump()}"
        )
        self.emit_progress("stage start stage=sync")
        sync = await orchestrator.run_sync(run_id=suffixed_run_id(run_id_prefix, "sync"))
        self.emit_progress(
            f"stage done stage=sync status={sync.status} counts={sync.counts.model_dump()}"
        )
        self.emit_progress("stage start stage=notify-handoff")
        notify = await orchestrator.run_notify_handoff(
            run_id=suffixed_run_id(run_id_prefix, "notify")
        )
        self.emit_progress(
            "stage done "
            f"stage=notify-handoff status={notify.status} "
            f"counts={notify.counts.model_dump()}"
        )
        self.stage_run_ids = {
            "scrape": scrape.run_id,
            "normalize": normalize.run_id,
            "enrich": enrich.run_id,
            "sync": sync.run_id,
            "notify": notify.run_id,
        }
        self.stage_statuses = {
            "scrape": scrape.status,
            "normalize": normalize.status,
            "enrich": enrich.status,
            "sync": sync.status,
            "notify-handoff": notify.status,
        }
        self.stage_count_breakdown = {
            "scrape": scrape.counts.model_dump(),
            "normalize": normalize.counts.model_dump(),
            "enrich": enrich.counts.model_dump(),
            "sync": sync.counts.model_dump(),
            "notify-handoff": notify.counts.model_dump(),
        }
        statuses = {scrape.status, normalize.status, enrich.status, sync.status, notify.status}
        status = (
            "failed"
            if "failed" in statuses
            else "partial"
            if "partial" in statuses
            else "completed"
        )
        return PipelineResult(
            run_id=scrape.run_id,
            correlation_id=scrape.correlation_id,
            status=status,
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
    selected_platforms: tuple[str, ...],
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
            selected_platforms=selected_platforms,
            keywords=keywords,
            fixture_root=fixture_root,
            limit=limit,
            recency_mode=recency_mode,
            recency_days=recency_days,
        )
    return live_sources(
        selected_platforms=selected_platforms,
        keywords=keywords,
        settings=settings,
        limit=limit,
        recency_mode=recency_mode,
        recency_days=recency_days,
    )


def select_sources(*, source: str, settings: Settings, execute: bool) -> SourceSelection:
    if execute and source == "jobstreet" and not settings.jobstreet_enabled:
        raise CliInputError(
            "JobStreet source is disabled (JOBSTREET_ENABLED=false). "
            "Use --dry-run for fixture validation or enable JobStreet for live execute."
        )
    requested = tuple(PLATFORM_SOURCES) if source == "all" else (source,)
    executed: list[str] = []
    skipped: list[dict[str, str]] = []
    for platform in requested:
        if execute and platform == "jobstreet" and not settings.jobstreet_enabled:
            skipped.append(
                {
                    "source": platform,
                    "reason": "disabled (JOBSTREET_ENABLED=false)",
                }
            )
            continue
        executed.append(platform)
    if not executed:
        skipped_sources = ", ".join(item["source"] for item in skipped) or source
        mode = "execute" if execute else "dry-run"
        raise CliInputError(f"no executable sources for mode {mode}: {skipped_sources}")
    return SourceSelection(
        requested=requested,
        executed=tuple(executed),
        skipped=tuple(skipped),
    )


def live_sources(
    *,
    selected_platforms: tuple[str, ...],
    keywords: tuple[str, ...],
    settings: Settings,
    limit: int,
    recency_mode: str,
    recency_days: int,
) -> list[LivePipelineSource]:
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
        for platform in selected_platforms
        for keyword in keywords
    ]


def live_platforms(source: str, settings: Settings) -> tuple[str, ...]:
    return select_sources(source=source, settings=settings, execute=True).executed


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


def build_backend_sync_client(
    settings: Settings,
    *,
    execute: bool,
) -> BackendSyncClient | RecordingBackendClient:
    if not execute or not settings.backend_sync_enabled:
        return RecordingBackendClient()
    if settings.backend_sync_base_url is None or settings.backend_sync_service_token is None:
        raise ValueError("backend sync client requires base URL and service token")
    return BackendSyncClient(
        base_url=settings.backend_sync_base_url,
        service_token=settings.backend_sync_service_token.get_secret_value(),
        timeout_seconds=settings.backend_sync_timeout_seconds,
        max_retries=settings.http_max_retries,
    )


def build_handoff_client(
    settings: Settings,
    *,
    execute: bool,
) -> BackendNotificationHandoffClient | RecordingHandoffClient:
    if not execute or not settings.backend_sync_enabled:
        return RecordingHandoffClient()
    if settings.backend_sync_base_url is None or settings.backend_sync_service_token is None:
        raise ValueError("notification handoff client requires base URL and service token")
    return BackendNotificationHandoffClient(
        base_url=settings.backend_sync_base_url,
        service_token=settings.backend_sync_service_token.get_secret_value(),
        timeout_seconds=settings.backend_sync_timeout_seconds,
    )


def fixture_sources(
    *,
    selected_platforms: tuple[str, ...],
    keywords: tuple[str, ...],
    fixture_root: Path,
    limit: int,
    recency_mode: str,
    recency_days: int,
) -> list[FixturePipelineSource]:
    return [
        FixturePipelineSource(
            platform,
            keyword,
            fixture_root / platform / "sample.json",
            limit,
            recency_mode,
            recency_days,
        )
        for platform in selected_platforms
        for keyword in keywords
    ]


def fixture_availability(
    requested_sources: tuple[str, ...],
    *,
    fixture_root: Path,
) -> dict[str, Any]:
    found: list[str] = []
    missing: list[str] = []
    for source in requested_sources:
        if (fixture_root / source / "sample.json").is_file():
            found.append(source)
        else:
            missing.append(source)
    return {
        "status": "ok" if not missing else "fail",
        "fixtureRoot": str(fixture_root),
        "availableSources": found,
        "missingSources": missing,
    }


def migration_target_check() -> dict[str, Any]:
    try:
        config = Config("alembic.ini")
        script = ScriptDirectory.from_config(config)
        heads = list(script.get_heads())
        current_head = script.get_current_head()
        if not heads:
            return {
                "status": "fail",
                "reason": "alembic script directory has no head revisions",
            }
        return {
            "status": "ok",
            "scriptLocation": config.get_main_option("script_location"),
            "heads": heads,
            "currentHead": current_head,
        }
    except Exception as exc:
        return {
            "status": "fail",
            "reason": redact_text(str(exc)),
        }


def backend_sync_mode(settings: Settings, *, execute: bool) -> dict[str, Any]:
    if not execute:
        return {
            "status": "ok",
            "mode": "recording",
            "reason": "dry-run mode always uses recording sync/handoff clients",
        }
    if not settings.backend_sync_enabled:
        return {
            "status": "ok",
            "mode": "recording",
            "reason": "BACKEND_SYNC_ENABLED=false",
        }
    if settings.backend_sync_base_url is None or settings.backend_sync_service_token is None:
        return {
            "status": "fail",
            "mode": "live",
            "reason": "backend sync enabled but base URL or service token is missing",
        }
    return {
        "status": "ok",
        "mode": "live",
        "baseUrl": settings.backend_sync_base_url,
    }


def redact_database_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return make_url(value).render_as_string(hide_password=True)
    except Exception:
        return redact_text(value)


def build_ai_normalization_client(
    settings: Settings,
    *,
    execute: bool,
) -> OpenAINormalizationClient | None:
    if not execute:
        return None
    if not settings.ai_enrichment_enabled:
        return None
    if (
        settings.openai_api_key is None
        or settings.openai_base_url is None
        or settings.openai_model is None
    ):
        return None
    return OpenAINormalizationClient(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=str(settings.openai_base_url),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def build_ai_enrichment_client(
    settings: Settings,
    *,
    execute: bool,
) -> OpenAIEnrichmentClient | None:
    if not execute:
        return None
    if not settings.ai_enrichment_enabled:
        return None
    if (
        settings.openai_api_key is None
        or settings.openai_base_url is None
        or settings.openai_model is None
    ):
        return None
    return OpenAIEnrichmentClient(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=str(settings.openai_base_url),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


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
    stage_statuses: dict[str, str] | None = None,
    stage_count_breakdown: dict[str, dict[str, int]] | None = None,
    sync_diagnostics: dict[str, Any] | None = None,
    source_selection: SourceSelection | None = None,
) -> dict[str, Any]:
    requested_sources = list(source_selection.requested) if source_selection else []
    executed_sources = list(source_selection.executed) if source_selection else []
    skipped_sources = list(source_selection.skipped) if source_selection else []
    breakdown = stage_count_breakdown or {}
    count_breakdown = {
        "rawPersisted": breakdown.get("scrape", {}).get("persisted", 0),
        "normalizedPersisted": breakdown.get("normalize", {}).get("persisted", 0),
        "enrichmentPersisted": breakdown.get("enrich", {}).get("persisted", 0),
        "syncSent": breakdown.get("sync", {}).get("persisted", 0),
        "notifyHandoffSent": breakdown.get("notify-handoff", {}).get("persisted", 0),
    }
    output = {
        "check": "pipeline-run",
        "status": "ok" if result.status in {"completed", "partial"} else "fail",
        "mode": "execute" if execute else "dry-run",
        "stage": stage,
        "source": source,
        "keywords": list(keywords),
        "runId": result.run_id,
        "stageRunIds": stage_run_ids or {},
        "stageStatuses": stage_statuses or {},
        "runStatus": result.status,
        "correlationId": result.correlation_id,
        "limit": limit,
        "recencyMode": recency_mode,
        "recencyDays": recency_days,
        "requestedSources": requested_sources,
        "executedSources": executed_sources,
        "skippedSources": skipped_sources,
        "counts": result.counts.model_dump(),
        "countBreakdown": count_breakdown,
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
    if sync_diagnostics:
        output["diagnostics"] = {"sync": sync_diagnostics}
    return output


def build_engine(database_url: str, *, execute: bool) -> Engine:
    if not execute:
        return create_engine("sqlite:///:memory:")
    return create_engine(to_sync_url(database_url), pool_pre_ping=True)


def to_sync_url(database_url: str) -> str:
    return to_sync_postgres_url(database_url)


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


def positive_sample_size(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    if parsed > 20:
        raise argparse.ArgumentTypeError("must be less than or equal to 20")
    return parsed


def positive_metric_value(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def non_negative_metric_value(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to zero")
    return parsed


def ratio_0_to_1(value: str) -> float:
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
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


def source_enrichment_output_from_job(job: NormalizedJob) -> EnrichmentOutput:
    payload = job.normalized_payload if isinstance(job.normalized_payload, dict) else {}
    raw_skills = payload.get("skills")
    skills = (
        [
            EnrichedSkill(name=skill, confidence=0.6)
            for skill in raw_skills
            if isinstance(skill, str) and skill.strip()
        ]
        if isinstance(raw_skills, list)
        else []
    )

    raw_requirements = payload.get("requirements")
    requirements = (
        [
            EnrichedRequirement(
                type=RequirementType.OTHER,
                value=raw_requirements.strip(),
                confidence=0.5,
            )
        ]
        if isinstance(raw_requirements, str) and raw_requirements.strip()
        else []
    )

    return EnrichmentOutput(
        skills=skills,
        requirements=requirements,
        confidence=0.5 if skills or requirements else 0.0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
