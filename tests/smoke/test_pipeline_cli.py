from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cli.pipeline import live_platforms, main, to_sync_url
from modules.persistence import Base, RawJob, ScrapeRun
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

    assert main(["run", "--stage", "scrape", "--source", "dealls", "--limit", "2"]) == 0

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

    assert main(["run", "--stage", "full", "--source", "dealls", "--limit", "1"]) == 0

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
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["keywords"] == ["Developer", "ui/ux"]
    assert output["counts"]["fetched"] == 2


def test_pipeline_rejects_invalid_stage(monkeypatch) -> None:
    apply_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        main(["run", "--stage", "invalid"])

    assert exc.value.code == 2


def test_pipeline_execute_url_conversion_preserves_runtime_password() -> None:
    assert (
        to_sync_url("postgresql+asyncpg://scraper_user:secret@db.example/scraper")
        == "postgresql+psycopg://scraper_user:secret@db.example/scraper"
    )


def test_live_all_respects_jobstreet_enabled_flag() -> None:
    settings = valid_env(JOBSTREET_ENABLED="false")

    assert live_platforms("all", settings_from_env(settings)) == ("dealls", "glints", "kalibrr")


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
                ),
            ]
        )
        session.flush()
        session.add(
            RawJob(
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
    assert "must-not-print" not in output_text


def apply_env(monkeypatch) -> None:  # noqa: ANN001
    for key, value in valid_env().items():
        monkeypatch.setenv(key, str(value))


def settings_from_env(values: dict[str, object]):
    from config.settings import Settings

    return Settings(**values, _env_file=None)
