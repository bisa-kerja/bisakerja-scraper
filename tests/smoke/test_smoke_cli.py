from __future__ import annotations

import json

from cli.smoke import main
from tests.integration.helpers import valid_env


def test_config_check_prints_deterministic_json(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert main(["config"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "app": "bisakerja-scraper",
        "backendSyncEnabled": False,
        "check": "config",
        "env": "test",
        "status": "ok",
    }


def test_health_check_uses_local_app_without_network(monkeypatch, capsys) -> None:
    apply_env(monkeypatch)

    assert main(["health"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "check": "health",
        "httpStatus": 200,
        "serviceStatus": "live",
        "status": "ok",
    }


def test_dry_run_maps_one_dealls_fixture_job(capsys) -> None:
    assert main(["dry-run", "--source", "dealls"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["check"] == "dry-run"
    assert output["status"] == "ok"
    assert output["source"] == "dealls"
    assert output["inputJobs"] == 2
    assert output["mappedJobs"] == 1
    assert output["firstExternalJobId"] == "69f30ce4b9f8ed001233b47c"


def test_dry_run_maps_one_fixture_job_for_all_supported_sources(capsys) -> None:
    expected_external_ids = {
        "dealls": "69f30ce4b9f8ed001233b47c",
        "glints": "aaed8a7f-de12-479c-8df8-56f26b35bed9",
        "jobstreet": "91789576",
        "kalibrr": "265196",
    }
    for source, external_id in expected_external_ids.items():
        assert main(["dry-run", "--source", source]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["check"] == "dry-run"
        assert output["status"] == "ok"
        assert output["source"] == source
        assert output["mappedJobs"] == 1
        assert output["firstExternalJobId"] == external_id


def apply_env(monkeypatch) -> None:  # noqa: ANN001
    for key, value in valid_env().items():
        monkeypatch.setenv(key, str(value))
