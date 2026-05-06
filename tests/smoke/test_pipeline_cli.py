from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cli.pipeline import (
    ManualPipelineRunner,
    RecordingBackendClient,
    RecordingHandoffClient,
    SourceSelection,
    build_backend_sync_client,
    build_handoff_client,
    live_platforms,
    main,
    stage_run_ids,
    to_sync_url,
)
from integrations.backend import BackendNotificationHandoffClient, BackendSyncClient
from jobs.pipeline import PipelineResult, SourcePipelineResult
from modules.persistence import (
    AIRequestLog,
    Base,
    NormalizedJob,
    NotificationHandoffEvent,
    RawJob,
    ScrapeRun,
    SyncEvent,
)
from modules.runs import RunCounts
from tests.integration.helpers import valid_env


def test_pipeline_full_dry_run_uses_fixture_flow(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "run",
                "--stage",
                "full",
                "--source",
                "all",
                "--limit",
                "1",
                "--keyword",
                "developer",
                "--dry-run",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["mode"] == "dry-run"
    assert output["stage"] == "full"
    assert output["source"] == "all"
    assert output["keywords"] == ["developer"]
    assert output["limit"] == 1
    assert output["recencyMode"] == "latest"
    assert output["recencyDays"] == 7
    assert output["counts"]["persisted"] == 4
    assert output["stageStatuses"] == {
        "scrape": "completed",
        "normalize": "completed",
        "enrich": "completed",
        "sync": "completed",
        "notify-handoff": "completed",
    }
    assert output["countBreakdown"]["rawPersisted"] == 4
    assert output["countBreakdown"]["normalizedPersisted"] == 4
    assert output["countBreakdown"]["enrichmentPersisted"] == 4
    assert output["countBreakdown"]["syncSent"] == 4
    assert output["countBreakdown"]["notifyHandoffSent"] == 4
    assert output["requestedSources"] == ["dealls", "glints", "jobstreet", "kalibrr"]
    assert output["executedSources"] == ["dealls", "glints", "jobstreet", "kalibrr"]
    assert output["skippedSources"] == []
    assert {item["source"] for item in output["sources"]} == {
        "dealls",
        "glints",
        "jobstreet",
        "kalibrr",
    }
    assert len(output["sources"]) == 4
    assert "password" not in json.dumps(output).lower()


def test_pipeline_stage_dry_run_limits_source(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "run",
                "--stage",
                "scrape",
                "--source",
                "dealls",
                "--limit",
                "2",
                "--keyword",
                "developer",
                "--dry-run",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["stage"] == "scrape"
    assert output["counts"]["fetched"] == 2
    assert output["sources"] == [
        {
            "counts": {
                "fetched": 2,
                "normalized": 0,
                "parsed": 0,
                "persisted": 2,
                "skipped": 0,
            },
            "keyword": "developer",
            "newestSourceTimestamp": output["sources"][0]["newestSourceTimestamp"],
            "oldestSourceTimestamp": output["sources"][0]["oldestSourceTimestamp"],
            "requestedLimit": 2,
            "source": "dealls",
            "status": "completed",
            "truncatedCount": 0,
        }
    ]


def test_pipeline_uses_env_keywords_and_cli_limit_per_keyword(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "run",
                "--stage",
                "scrape",
                "--source",
                "dealls",
                "--limit",
                "2",
                "--dry-run",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["keywords"] == ["developer", "intern", "ui/ux"]
    assert output["counts"]["fetched"] == 6
    assert [item["keyword"] for item in output["sources"]] == ["developer", "intern", "ui/ux"]
    assert all(item["requestedLimit"] == 2 for item in output["sources"])


def test_pipeline_full_normalizes_once_per_platform_with_overlapping_keywords(
    monkeypatch,
    capsys,
) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "run",
                "--stage",
                "full",
                "--source",
                "dealls",
                "--limit",
                "1",
                "--dry-run",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["keywords"] == ["developer", "intern", "ui/ux"]
    assert output["counts"]["fetched"] == 3
    assert output["counts"]["normalized"] == 1
    assert output["counts"]["persisted"] == 1


def test_pipeline_keyword_override_deduplicates_case_insensitive(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "run",
                "--stage",
                "scrape",
                "--source",
                "dealls",
                "--keywords",
                "Developer, developer,ui/ux",
                "--limit",
                "1",
                "--dry-run",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["keywords"] == ["Developer", "ui/ux"]
    assert output["counts"]["fetched"] == 2


def test_pipeline_rejects_invalid_stage(monkeypatch) -> None:
    apply_env(monkeypatch)

    assert main(["run", "--stage", "invalid", "--dry-run"]) == 1


def test_pipeline_requires_explicit_mode(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert main(["run", "--stage", "scrape", "--source", "dealls"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["check"] == "pipeline-cli"


def test_wizard_non_tty_requires_yes(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)
    monkeypatch.setattr("cli.pipeline.wizard_tty_available", lambda: False)

    assert main(["wizard", "--dry-run", "--env-file", ".env.example"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert output["check"] == "pipeline-wizard"
    assert "--yes" in output["reason"]


def test_wizard_non_tty_safe_dry_run_with_yes(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)
    monkeypatch.setattr("cli.pipeline.wizard_tty_available", lambda: False)

    assert (
        main(
            [
                "wizard",
                "--dry-run",
                "--source",
                "dealls",
                "--stage",
                "scrape",
                "--limit",
                "1",
                "--env-file",
                ".env.example",
                "--yes",
            ]
        )
        == 0
    )
    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output["check"] == "pipeline-wizard"
    assert output["status"] == "ok"
    assert output["mode"] == "dry-run"
    assert output["result"]["executedSources"] == ["dealls"]
    assert output["friendly"]["verifyCommand"] is not None
    assert "service-token" not in output_text
    assert "bearer" not in output_text.lower()


def test_wizard_non_tty_blocks_risky_env(monkeypatch, capsys) -> None:
    for key in valid_env():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("cli.pipeline.wizard_tty_available", lambda: False)

    assert (
        main(
            [
                "wizard",
                "--dry-run",
                "--source",
                "dealls",
                "--stage",
                "scrape",
                "--limit",
                "1",
                "--env-file",
                ".env.production.example",
                "--yes",
            ]
        )
        == 1
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert "cannot bypass" in output["reason"]


def test_wizard_interactive_dry_run_scripted_input(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)
    monkeypatch.setattr("cli.pipeline.wizard_tty_available", lambda: True)
    scripted = iter(
        [
            "1",  # mode dry-run
            "",  # use preset env file list (yes)
            "1",  # .env.example
            "2",  # stage scrape
            "2",  # source dealls
            "1",  # limit
            "7",  # recency days
            "",  # use env keyword preset
            "",  # set custom run id? no
        ]
    )
    monkeypatch.setattr("builtins.input", lambda: next(scripted))

    assert main(["wizard"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["mode"] == "dry-run"
    assert output["result"]["stage"] == "scrape"
    assert output["result"]["source"] == "dealls"


def test_wizard_execute_requires_explicit_yes_confirmation(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)
    monkeypatch.setattr("cli.pipeline.wizard_tty_available", lambda: True)
    scripted = iter(
        [
            "2",  # mode execute
            "",  # use preset env file list
            "1",  # .env.example
            "2",  # stage scrape
            "2",  # source dealls
            "1",  # limit
            "7",  # recency days
            "",  # use env keyword preset
            "",  # set custom run id? no
            "",  # confirm gate (must be YES)
        ]
    )
    monkeypatch.setattr("builtins.input", lambda: next(scripted))

    assert main(["wizard"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert "confirmation rejected" in output["reason"]


def test_quick_dry_run_runs_safe_defaults(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert main(["quick-dry-run", "--source", "dealls", "--stage", "scrape"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["check"] == "pipeline-run"
    assert output["mode"] == "dry-run"
    assert output["source"] == "dealls"
    assert output["stage"] == "scrape"


def test_pipeline_execute_jobstreet_disabled_returns_json_failure(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "run",
                "--stage",
                "scrape",
                "--source",
                "jobstreet",
                "--execute",
            ]
        )
        == 1
    )
    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output["status"] == "fail"
    assert output["check"] == "pipeline-run"
    assert "disabled" in output["reason"].lower()
    assert "traceback" not in output_text.lower()


def test_pipeline_preflight_reports_source_and_fixture_state(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "preflight",
                "--stage",
                "full",
                "--source",
                "all",
                "--dry-run",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["check"] == "pipeline-preflight"
    assert output["status"] == "ok"
    assert output["requestedSources"] == ["dealls", "glints", "jobstreet", "kalibrr"]
    assert output["executedSources"] == ["dealls", "glints", "jobstreet", "kalibrr"]
    assert output["fixtures"]["status"] == "ok"
    assert output["migrationTarget"]["status"] == "ok"


def test_pipeline_preflight_execute_all_reports_disabled_jobstreet(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert (
        main(
            [
                "preflight",
                "--stage",
                "full",
                "--source",
                "all",
                "--execute",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["requestedSources"] == ["dealls", "glints", "jobstreet", "kalibrr"]
    assert output["executedSources"] == ["dealls", "glints", "kalibrr"]
    assert output["skippedSources"] == [
        {"reason": "disabled (JOBSTREET_ENABLED=false)", "source": "jobstreet"}
    ]


def test_pipeline_execute_url_conversion_preserves_runtime_password() -> None:
    assert (
        to_sync_url("postgresql+asyncpg://scraper_user:secret@db.example/scraper")
        == "postgresql+psycopg://scraper_user:secret@db.example/scraper"
    )


def test_live_all_respects_jobstreet_enabled_flag() -> None:
    settings = valid_env(JOBSTREET_ENABLED="false")

    assert live_platforms("all", settings_from_env(settings)) == ("dealls", "glints", "kalibrr")


def test_pipeline_execute_uses_recording_clients_when_backend_sync_disabled() -> None:
    settings = settings_from_env(valid_env(BACKEND_SYNC_ENABLED="false"))

    assert isinstance(build_backend_sync_client(settings, execute=True), RecordingBackendClient)
    assert isinstance(build_handoff_client(settings, execute=True), RecordingHandoffClient)


def test_pipeline_execute_uses_real_clients_when_backend_sync_enabled() -> None:
    settings = settings_from_env(
        valid_env(
            BACKEND_SYNC_ENABLED="true",
            BACKEND_DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/backend_test",
            BACKEND_SYNC_BASE_URL="http://localhost:3000",
            BACKEND_SYNC_SERVICE_TOKEN="service-token",
        )
    )

    assert isinstance(build_backend_sync_client(settings, execute=True), BackendSyncClient)
    assert isinstance(
        build_handoff_client(settings, execute=True),
        BackendNotificationHandoffClient,
    )


def test_stage_run_ids_accept_notify_handoff_suffix() -> None:
    assert stage_run_ids("manual-run-notify-handoff") == [
        "manual-run-scrape",
        "manual-run-normalize",
        "manual-run-enrich",
        "manual-run-sync",
        "manual-run-notify",
    ]


@pytest.mark.asyncio
async def test_manual_full_run_marks_failed_when_any_stage_failed() -> None:
    runner = ManualPipelineRunner(
        session=None,
        settings=None,
        stage="full",
        source="all",
        keywords=("developer",),
        fixture_root=None,
        limit=1,
        recency_mode="latest",
        recency_days=7,
        execute=False,
        run_id=None,
        source_selection=SourceSelection(
            requested=("dealls",),
            executed=("dealls",),
            skipped=(),
        ),
    )

    class FakeOrchestrator:
        async def run_scrape(self, run_id=None):  # noqa: ANN001, ANN201
            return PipelineResult(
                run_id="run-scrape",
                correlation_id="corr",
                status="completed",
                counts=RunCounts(fetched=1),
                source_results=[SourcePipelineResult(source_platform="dealls", status="completed")],
                stage_events=["dealls:scrape"],
            )

        async def run_normalize(self, run_id=None):  # noqa: ANN001, ANN201
            return PipelineResult(
                run_id="run-normalize",
                correlation_id="corr",
                status="completed",
                counts=RunCounts(parsed=1, normalized=1),
                source_results=[],
                stage_events=["dealls:normalize"],
            )

        async def run_enrich(self, run_id=None):  # noqa: ANN001, ANN201
            return PipelineResult(
                run_id="run-enrich",
                correlation_id="corr",
                status="completed",
                counts=RunCounts(),
                source_results=[],
                stage_events=["enrich"],
            )

        async def run_sync(self, run_id=None):  # noqa: ANN001, ANN201
            return PipelineResult(
                run_id="run-sync",
                correlation_id="corr",
                status="failed",
                counts=RunCounts(skipped=1),
                source_results=[],
                stage_events=["sync"],
            )

        async def run_notify_handoff(self, run_id=None):  # noqa: ANN001, ANN201
            return PipelineResult(
                run_id="run-notify",
                correlation_id="corr",
                status="completed",
                counts=RunCounts(),
                source_results=[],
                stage_events=["notify-handoff"],
            )

    result = await runner.run_full(FakeOrchestrator(), run_id_prefix=None)
    assert result.status == "failed"


def test_manual_runner_emit_progress_only_in_execute_mode(capsys) -> None:
    runner_execute = ManualPipelineRunner(
        session=None,
        settings=None,
        stage="scrape",
        source="dealls",
        keywords=("developer",),
        fixture_root=None,
        limit=1,
        recency_mode="latest",
        recency_days=7,
        execute=True,
        run_id=None,
        source_selection=SourceSelection(
            requested=("dealls",),
            executed=("dealls",),
            skipped=(),
        ),
    )
    runner_execute.emit_progress("progress-check")
    assert "progress-check" in capsys.readouterr().err

    runner_dry_run = ManualPipelineRunner(
        session=None,
        settings=None,
        stage="scrape",
        source="dealls",
        keywords=("developer",),
        fixture_root=None,
        limit=1,
        recency_mode="latest",
        recency_days=7,
        execute=False,
        run_id=None,
        source_selection=SourceSelection(
            requested=("dealls",),
            executed=("dealls",),
            skipped=(),
        ),
    )
    runner_dry_run.emit_progress("should-not-print")
    assert "should-not-print" not in capsys.readouterr().err


def test_pipeline_status_reads_run(monkeypatch, tmp_path, capsys) -> None:
    apply_env(monkeypatch)
    database_path = tmp_path / "runs.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ScrapeRun(
                id="manual-1",
                source_platform="all",
                stage="sync",
                status="completed",
            )
        )
        session.commit()

    assert main(["status", "--run-id", "manual-1", "--database-url", database_url]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "check": "pipeline-status",
        "counts": {"normalized": 0, "raw": 0},
        "errorCategory": None,
        "runId": "manual-1",
        "runStatus": "completed",
        "sourcePlatform": "all",
        "stage": "sync",
        "status": "ok",
    }


def test_pipeline_verify_summarizes_database_without_raw_payload(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    apply_env(monkeypatch)
    database_path = tmp_path / "verify.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                ScrapeRun(
                    id="phase82-scrape",
                    source_platform="all",
                    stage="scrape",
                    status="completed",
                    raw_records_count=1,
                ),
                ScrapeRun(
                    id="phase82-normalize",
                    source_platform="all",
                    stage="normalize",
                    status="completed",
                    normalized_records_count=1,
                    metadata_json={"summary": {"counts": {"normalized": 1, "persisted": 1}}},
                ),
                ScrapeRun(
                    id="phase82-enrich",
                    source_platform="all",
                    stage="enrich",
                    status="completed",
                    metadata_json={"summary": {"counts": {"fetched": 1, "persisted": 1}}},
                ),
                ScrapeRun(
                    id="phase82-sync",
                    source_platform="all",
                    stage="sync",
                    status="completed",
                    metadata_json={"summary": {"counts": {"fetched": 1, "persisted": 1}}},
                ),
                ScrapeRun(
                    id="phase82-notify",
                    source_platform="all",
                    stage="notify-handoff",
                    status="completed",
                    metadata_json={"summary": {"counts": {"fetched": 1, "persisted": 1}}},
                ),
            ]
        )
        session.flush()
        raw = RawJob(
            scrape_run_id="phase82-scrape",
            source_platform="dealls",
            external_id="job-1",
            source_url="https://example.test/job-1",
            raw_payload={"secret": "must-not-print"},
            metadata_json={
                "keyword": "developer",
                "recencyMode": "latest",
                "recencyDays": 7,
                "requestedLimit": 50,
                "sourceTimestamp": "2026-05-03T01:00:00+00:00",
            },
        )
        session.add(raw)
        session.flush()
        normalized = NormalizedJob(
            raw_job_id=raw.id,
            source_platform="dealls",
            external_id="job-1",
            title="Backend Engineer",
            company_name="Example",
            source_url="https://example.test/job-1",
            status="ACTIVE",
            normalized_payload={"title": "Backend Engineer"},
            last_seen_at=datetime(2026, 5, 3, tzinfo=UTC),
        )
        session.add(normalized)
        session.flush()
        session.add_all(
            [
                AIRequestLog(
                    scrape_run_id="phase82-enrich",
                    normalized_job_id=normalized.id,
                    provider="openai-compatible",
                    model="gpt-4o-mini",
                    base_url_alias="api.openai.com",
                    latency_ms=120,
                    status="success",
                    retry_count=0,
                    request_hash="ai-hash-1",
                    response_summary={"skillsCount": 2},
                    error_category=None,
                    error_message=None,
                ),
                AIRequestLog(
                    scrape_run_id="phase82-enrich",
                    normalized_job_id=normalized.id,
                    provider="openai-compatible",
                    model="gpt-4o-mini",
                    base_url_alias="api.openai.com",
                    latency_ms=220,
                    status="failed",
                    retry_count=1,
                    request_hash="ai-hash-2",
                    response_summary={"errorCategory": "OPENAI_RATE_LIMIT"},
                    error_category="OPENAI_RATE_LIMIT",
                    error_message="rate limit",
                ),
            ]
        )
        session.flush()
        sync_event = SyncEvent(
            scrape_run_id="phase82-sync",
            normalized_job_id=normalized.id,
            source_platform="dealls",
            external_id="job-1",
            status="sent",
            target="backend",
            payload_hash="hash-verify-1",
            attempt_count=1,
            attempted_at=datetime(2026, 5, 3, tzinfo=UTC),
            completed_at=datetime(2026, 5, 3, tzinfo=UTC),
            response_summary={"statusCode": 202},
        )
        session.add(sync_event)
        session.flush()
        session.add(
            NotificationHandoffEvent(
                scrape_run_id="phase82-notify",
                normalized_job_id=normalized.id,
                sync_event_id=sync_event.id,
                source_platform="dealls",
                external_id="job-1",
                status="sent",
                payload_hash="hash-notify-verify-1",
                attempt_count=1,
                payload_json={"jobId": normalized.id},
                attempted_at=datetime(2026, 5, 3, tzinfo=UTC),
                completed_at=datetime(2026, 5, 3, tzinfo=UTC),
            )
        )
        session.commit()

    assert main(["verify", "--run-id", "phase82", "--database-url", database_url]) == 0

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output["status"] == "ok"
    assert output["rawRows"] == 1
    assert output["rawBySourceKeyword"] == {"dealls:developer": 1}
    assert output["duplicateRawIdentities"] == 0
    assert output["latestMetadata"]["requestedLimit"] == 50
    assert output["aiByModel"] == {
        "gpt-4o-mini": {
            "failed": 1,
            "rate_limited": 1,
            "requests": 2,
            "successes": 1,
        }
    }
    assert output["invariants"]["failed"] == 0
    assert "must-not-print" not in output_text


def test_pipeline_verify_fails_when_stage_rows_missing(monkeypatch, tmp_path, capsys) -> None:
    apply_env(monkeypatch)
    database_path = tmp_path / "verify-missing.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ScrapeRun(
                id="phase90-scrape",
                source_platform="all",
                stage="scrape",
                status="completed",
            )
        )
        session.commit()

    assert main(["verify", "--run-id", "phase90", "--database-url", database_url]) == 1

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    stage_row_check = next(
        check for check in output["invariants"]["checks"] if check["name"] == "stageRowsPresent"
    )
    assert stage_row_check["passed"] is False


def test_pipeline_staging_report_validates_counts_consistency_and_backend_checks(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    apply_env(monkeypatch)
    scraper_path = tmp_path / "scraper.db"
    scraper_url = f"sqlite:///{scraper_path}"
    backend_path = tmp_path / "backend.db"
    backend_url = f"sqlite:///{backend_path}"
    now = datetime(2026, 5, 4, 2, 0, tzinfo=UTC)

    scraper_engine = create_engine(scraper_url)
    Base.metadata.create_all(scraper_engine)
    with Session(scraper_engine) as session:
        session.add_all(
            [
                ScrapeRun(
                    id="phase85-scrape",
                    source_platform="all",
                    stage="scrape",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    raw_records_count=1,
                    metadata_json={"summary": {"counts": {"fetched": 1, "skipped": 0}}},
                ),
                ScrapeRun(
                    id="phase85-normalize",
                    source_platform="all",
                    stage="normalize",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    normalized_records_count=1,
                    metadata_json={"summary": {"counts": {"normalized": 1, "skipped": 0}}},
                ),
                ScrapeRun(
                    id="phase85-enrich",
                    source_platform="all",
                    stage="enrich",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"persisted": 1, "skipped": 0}}},
                ),
                ScrapeRun(
                    id="phase85-sync",
                    source_platform="all",
                    stage="sync",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"persisted": 1, "skipped": 0}}},
                ),
                ScrapeRun(
                    id="phase85-notify",
                    source_platform="all",
                    stage="notify-handoff",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"persisted": 1, "skipped": 0}}},
                ),
            ]
        )
        session.flush()
        raw = RawJob(
            scrape_run_id="phase85-scrape",
            source_platform="dealls",
            external_id="dealls-1",
            source_url="https://example.test/dealls-1",
            raw_payload={"title": "Backend Engineer"},
            metadata_json={"keyword": "developer"},
        )
        session.add(raw)
        session.flush()
        normalized = NormalizedJob(
            raw_job_id=raw.id,
            source_platform="dealls",
            external_id="dealls-1",
            title="Backend Engineer",
            company_name="Example Tech",
            source_url="https://example.test/dealls-1",
            apply_url="https://example.test/apply/dealls-1",
            status="ACTIVE",
            normalized_payload={"title": "Backend Engineer"},
            last_seen_at=now,
        )
        session.add(normalized)
        session.flush()
        sync_event = SyncEvent(
            scrape_run_id="phase85-sync",
            normalized_job_id=normalized.id,
            source_platform="dealls",
            external_id="dealls-1",
            status="sent",
            target="backend",
            payload_hash="hash-1",
            attempt_count=1,
            attempted_at=now,
            completed_at=now,
            response_summary={"statusCode": 202, "statusClass": "2xx"},
            metadata_json={"chunkId": "phase85-sync:1"},
        )
        session.add(sync_event)
        session.flush()
        session.add(
            NotificationHandoffEvent(
                scrape_run_id="phase85-notify",
                normalized_job_id=normalized.id,
                sync_event_id=sync_event.id,
                source_platform="dealls",
                external_id="dealls-1",
                status="sent",
                payload_hash="hash-notify-1",
                attempt_count=1,
                payload_json={"jobId": normalized.id},
                attempted_at=now,
                completed_at=now,
            )
        )
        session.commit()

    backend_engine = create_engine(backend_url)
    with backend_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE companies (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE skills (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            """
            CREATE TABLE job_listings (
                id TEXT PRIMARY KEY,
                source_platform_id TEXT NOT NULL,
                external_job_id TEXT NOT NULL,
                company_id TEXT NOT NULL,
                status TEXT NOT NULL,
                last_seen_at TEXT
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE job_skills (
                id TEXT PRIMARY KEY,
                job_listing_id TEXT NOT NULL,
                skill_id TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE job_requirements (
                id TEXT PRIMARY KEY,
                job_listing_id TEXT NOT NULL
            )
            """
        )
        connection.exec_driver_sql("INSERT INTO companies (id) VALUES ('company-1')")
        connection.exec_driver_sql("INSERT INTO skills (id) VALUES ('skill-1')")
        connection.exec_driver_sql(
            """
            INSERT INTO job_listings (
                id,
                source_platform_id,
                external_job_id,
                company_id,
                status,
                last_seen_at
            ) VALUES (
                'listing-1',
                'source-1',
                'dealls-1',
                'company-1',
                'ACTIVE',
                '2026-05-04T02:00:00+00:00'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO job_skills (id, job_listing_id, skill_id)
            VALUES ('js-1', 'listing-1', 'skill-1')
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO job_requirements (id, job_listing_id) VALUES ('jr-1', 'listing-1')"
        )

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> dict[str, object]:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.kwargs = kwargs

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def get(self, path: str, params=None) -> FakeResponse:  # noqa: ANN001
            if path == "/api/v1/jobs":
                return FakeResponse(200, {"data": [{"id": "listing-1"}]})
            if path == "/api/v1/jobs/listing-1":
                return FakeResponse(200, {"data": {"id": "listing-1"}})
            return FakeResponse(404, {})

    monkeypatch.setattr("cli.pipeline.httpx.AsyncClient", FakeAsyncClient)

    assert (
        main(
            [
                "staging-report",
                "--run-id",
                "phase85",
                "--scraper-database-url",
                scraper_url,
                "--backend-database-url",
                backend_url,
                "--backend-base-url",
                "https://backend.example.test",
                "--stage-p95-threshold-ms",
                "5000",
                "--retry-threshold",
                "2",
            ]
        )
        == 0
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert output["check"] == "staging-report"
    assert output["status"] == "ok"
    assert output["stageCounts"]["fetched"] == 1
    assert output["stageCounts"]["syncUpserted"] == 1
    assert output["consistency"]["status"] == "ok"
    assert output["backendDatabaseConsistency"]["status"] == "ok"
    assert output["backendApiReadCheck"]["status"] == "ok"
    assert output["gates"]["failed"] == 0
    assert "must-not-print" not in output_text


def test_pipeline_staging_report_tracks_glints_partial_data_rate(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    apply_env(monkeypatch)
    scraper_path = tmp_path / "scraper-glints.db"
    scraper_url = f"sqlite:///{scraper_path}"
    now = datetime(2026, 5, 4, 2, 0, tzinfo=UTC)

    scraper_engine = create_engine(scraper_url)
    Base.metadata.create_all(scraper_engine)
    with Session(scraper_engine) as session:
        session.add_all(
            [
                ScrapeRun(
                    id="phase86-scrape",
                    source_platform="all",
                    stage="scrape",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                ),
                ScrapeRun(
                    id="phase86-normalize",
                    source_platform="all",
                    stage="normalize",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                ),
                ScrapeRun(
                    id="phase86-enrich",
                    source_platform="all",
                    stage="enrich",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                ),
                ScrapeRun(
                    id="phase86-sync",
                    source_platform="all",
                    stage="sync",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                ),
                ScrapeRun(
                    id="phase86-notify",
                    source_platform="all",
                    stage="notify-handoff",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                ),
            ]
        )
        session.flush()
        raw = RawJob(
            scrape_run_id="phase86-scrape",
            source_platform="glints",
            external_id="glints-1",
            source_url="https://glints.com/id/opportunities/jobs/glints-1",
            raw_payload={"title": "Glints Role"},
        )
        session.add(raw)
        session.flush()
        session.add(
            NormalizedJob(
                raw_job_id=raw.id,
                source_platform="glints",
                external_id="glints-1",
                title="Glints Role",
                company_name="Glints Company",
                source_url="https://glints.com/id/opportunities/jobs/glints-1",
                apply_url="https://glints.com/id/opportunities/jobs/glints-1",
                status="ACTIVE",
                normalized_payload={
                    "presentation": {
                        "source_labels": {
                            "detailCoverage": "unavailable",
                            "detailCompleteness": "partial",
                        }
                    }
                },
                last_seen_at=now,
            )
        )
        session.commit()

    assert (
        main(
            [
                "staging-report",
                "--run-id",
                "phase86",
                "--scraper-database-url",
                scraper_url,
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    glints_partial = output["partialData"]["bySource"]["glints"]
    assert glints_partial["total"] == 1
    assert glints_partial["partial"] == 1
    assert glints_partial["partialRate"] == 1.0
    glints_gate = next(
        check for check in output["gates"]["checks"] if check["name"] == "glintsPartialRate"
    )
    assert glints_gate["passed"] is True


def test_pipeline_staging_report_sets_reason_when_sync_completed_zero_sent(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    apply_env(monkeypatch)
    scraper_path = tmp_path / "scraper-zero-sync.db"
    scraper_url = f"sqlite:///{scraper_path}"
    now = datetime(2026, 5, 4, 2, 0, tzinfo=UTC)

    scraper_engine = create_engine(scraper_url)
    Base.metadata.create_all(scraper_engine)
    with Session(scraper_engine) as session:
        session.add_all(
            [
                ScrapeRun(
                    id="phase90-scrape",
                    source_platform="all",
                    stage="scrape",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"fetched": 1}}},
                ),
                ScrapeRun(
                    id="phase90-normalize",
                    source_platform="all",
                    stage="normalize",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"normalized": 1, "persisted": 1}}},
                ),
                ScrapeRun(
                    id="phase90-enrich",
                    source_platform="all",
                    stage="enrich",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"fetched": 1, "persisted": 0}}},
                ),
                ScrapeRun(
                    id="phase90-sync",
                    source_platform="all",
                    stage="sync",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"fetched": 0, "persisted": 0}}},
                ),
                ScrapeRun(
                    id="phase90-notify",
                    source_platform="all",
                    stage="notify-handoff",
                    status="completed",
                    started_at=now,
                    finished_at=now,
                    metadata_json={"summary": {"counts": {"fetched": 0, "persisted": 0}}},
                ),
            ]
        )
        session.flush()
        raw = RawJob(
            scrape_run_id="phase90-scrape",
            source_platform="dealls",
            external_id="dealls-zero-sync",
            source_url="https://example.test/dealls-zero-sync",
            raw_payload={"title": "Backend Engineer"},
        )
        session.add(raw)
        session.flush()
        session.add(
            NormalizedJob(
                raw_job_id=raw.id,
                source_platform="dealls",
                external_id="dealls-zero-sync",
                title="Backend Engineer",
                company_name="Example Tech",
                source_url="https://example.test/dealls-zero-sync",
                status="ACTIVE",
                normalized_payload={"title": "Backend Engineer"},
                last_seen_at=now,
            )
        )
        session.commit()

    assert (
        main(
            [
                "staging-report",
                "--run-id",
                "phase90",
                "--scraper-database-url",
                scraper_url,
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["syncOutcome"]["zeroSentReason"] == "no eligible jobs for sync"
    sync_check = next(
        check
        for check in output["invariants"]["checks"]
        if check["name"] == "syncZeroSentHasReason"
    )
    assert sync_check["passed"] is True


def apply_env(monkeypatch) -> None:  # noqa: ANN001
    for key, value in valid_env().items():
        monkeypatch.setenv(key, str(value))


def settings_from_env(values: dict[str, object]):
    from config.settings import Settings

    return Settings(**values, _env_file=None)
