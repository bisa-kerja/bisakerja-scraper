from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.deploy import db_preflight


def test_preflight_reads_env_file_and_hides_password(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=staging",
                "SCRAPER_DATABASE_URL=sqlite:///:memory:",
            ]
        ),
        encoding="utf-8",
    )

    result = db_preflight.run_preflight(env_file)

    assert result[0].status == "ok"
    assert result[0].url == "sqlite:///:memory:"


def test_preflight_reports_missing_env_without_secret_values() -> None:
    result = db_preflight.run_preflight_values({"APP_ENV": "staging"})

    assert result == [
        db_preflight.PreflightResult(
            name="config",
            status="fail",
            category="missing_env",
            message="missing required env: SCRAPER_DATABASE_URL",
        )
    ]


def test_preflight_invalid_database_url_does_not_leak_password() -> None:
    result = db_preflight.check_database(
        "scraper",
        "postgresql+psycopg://neondb_owner:super-secret@127.0.0.1:1/neondb",
    )

    body = json.dumps(result.model_dump())
    assert result.status == "fail"
    assert "super-secret" not in body
    assert "***" in body


def test_preflight_sync_url_conversion_preserves_runtime_password() -> None:
    assert (
        db_preflight.to_sync_url("postgresql+asyncpg://neondb_owner:super-secret@host/db")
        == "postgresql+psycopg://neondb_owner:super-secret@host/db"
    )
    assert (
        db_preflight.safe_url("postgresql+asyncpg://neondb_owner:super-secret@host/db")
        == "postgresql+asyncpg://neondb_owner:***@host/db"
    )


@pytest.mark.parametrize(
    ("message", "category", "safe_message"),
    [
        (
            "password authentication failed for user 'neondb_owner'",
            "auth_failed",
            "database authentication failed; rotate or redeploy the database secret",
        ),
        (
            "Network is unreachable",
            "network_failed",
            "database network is unreachable from deploy host",
        ),
        (
            "password authentication failed; Network is unreachable",
            "auth_failed",
            "database authentication failed; IPv6 reachability is secondary in this trace",
        ),
    ],
)
def test_preflight_classifies_common_deploy_errors(
    message: str,
    category: str,
    safe_message: str,
) -> None:
    error = RuntimeError(message)

    assert db_preflight.classify_error(error) == category
    assert db_preflight.safe_error_message(error) == safe_message
