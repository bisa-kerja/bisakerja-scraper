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
    assert output == {
        "check": "dry-run",
        "firstExternalJobId": "69f30ce4b9f8ed001233b47c",
        "inputJobs": 2,
        "mappedJobs": 1,
        "source": "dealls",
        "status": "ok",
    }


def apply_env(monkeypatch) -> None:  # noqa: ANN001
    for key, value in valid_env().items():
        monkeypatch.setenv(key, str(value))
