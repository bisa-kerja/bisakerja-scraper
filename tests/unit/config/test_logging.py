import json

import structlog

from config.logging import (
    REDACTED,
    bind_job_context,
    clear_log_context,
    configure_logging,
    redact_sensitive,
    request_log_context,
)
from config.settings import AppEnvironment, LogLevel


def test_json_logging_includes_context_and_redacts_secret_fields(capsys) -> None:
    configure_logging(
        service="bisakerja-scraper",
        env=AppEnvironment.TEST,
        level=LogLevel.INFO,
    )

    with request_log_context("req_test"):
        structlog.get_logger("test").info(
            "source_fetch",
            authorization="Bearer real-token",
            nested={"cookie": "sessionid=abc"},
        )

    log = json.loads(capsys.readouterr().out)

    assert log["event"] == "source_fetch"
    assert log["service"] == "bisakerja-scraper"
    assert log["env"] == "test"
    assert log["requestId"] == "req_test"
    assert log["authorization"] == REDACTED
    assert log["nested"]["cookie"] == REDACTED


def test_job_context_binds_run_id(capsys) -> None:
    configure_logging(
        service="bisakerja-scraper",
        env=AppEnvironment.TEST,
        level=LogLevel.INFO,
    )
    clear_log_context()
    bind_job_context("run_test", "source_run_test", stage="scrape")

    structlog.get_logger("test").info("job_started")

    log = json.loads(capsys.readouterr().out)
    clear_log_context()

    assert log["runId"] == "run_test"
    assert log["sourceRunId"] == "source_run_test"
    assert log["stage"] == "scrape"


def test_redact_sensitive_scrubs_secret_like_strings() -> None:
    data = {
        "message": "Authorization: Bearer abc.def",
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/db",
        "openai_base_url": "https://tenant.example.test/v1",
        "safe": ["ok", "sessionid=secret-value"],
    }

    redacted = redact_sensitive(data)

    assert redacted["message"] == f"Authorization: Bearer {REDACTED}"
    assert redacted["database_url"] == REDACTED
    assert redacted["openai_base_url"] == REDACTED
    assert redacted["safe"] == ["ok", f"sessionid={REDACTED}"]
