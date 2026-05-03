from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cli.pipeline import main, to_sync_url
from modules.persistence import Base, ScrapeRun
from tests.integration.helpers import valid_env


def test_pipeline_full_dry_run_uses_fixture_flow(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert main(["run", "--stage", "full", "--source", "all", "--limit", "1"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["mode"] == "dry-run"
    assert output["stage"] == "full"
    assert output["source"] == "all"
    assert output["counts"]["persisted"] == 4
    assert {item["source"] for item in output["sources"]} == {
        "dealls",
        "glints",
        "jobstreet",
        "kalibrr",
    }
    assert "password" not in json.dumps(output).lower()


def test_pipeline_stage_dry_run_limits_source(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert main(["run", "--stage", "scrape", "--source", "dealls", "--limit", "2"]) == 0

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
            "source": "dealls",
            "status": "completed",
        }
    ]


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


def apply_env(monkeypatch) -> None:  # noqa: ANN001
    for key, value in valid_env().items():
        monkeypatch.setenv(key, str(value))
