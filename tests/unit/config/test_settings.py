from pathlib import Path

import pytest
from pydantic import ValidationError

from config.settings import AppEnvironment, Settings

SETTINGS_ENV_KEYS = {
    field.validation_alias
    for field in Settings.model_fields.values()
    if isinstance(field.validation_alias, str)
}


@pytest.fixture(autouse=True)
def isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def valid_env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "APP_NAME": "bisakerja-scraper",
        "APP_ENV": "test",
        "PORT": "8000",
        "API_PREFIX": "/api/v1",
        "SCRAPER_DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/scraper_test",
        "BACKEND_SYNC_ENABLED": "false",
        "RUN_DATABASE_TESTS": "false",
        "SCRAPE_SCHEDULE_CRON": "0 0 * * *",
        "NORMALIZE_SCHEDULE_CRON": "0 2 * * *",
        "ENRICH_SCHEDULE_CRON": "0 4 * * *",
        "SYNC_SCHEDULE_CRON": "0 6 * * *",
        "NOTIFY_HANDOFF_SCHEDULE_CRON": "0 8 * * *",
        "WORKER_CONCURRENCY": "4",
        "SCRAPER_RUN_LOCK_TTL_SECONDS": "7200",
        "HTTP_TIMEOUT_SECONDS": "20",
        "HTTP_MAX_RETRIES": "2",
        "HTTP_RESPONSE_MAX_BYTES": "5242880",
        "DEFAULT_RATE_LIMIT_PER_MINUTE": "60",
        "SCRAPER_KEYWORDS": "developer,intern,ui/ux",
        "SCRAPER_MAX_ITEMS_PER_KEYWORD": "50",
        "SCRAPER_RECENCY_MODE": "latest",
        "SCRAPER_RECENCY_DAYS": "7",
        "BACKEND_SYNC_TIMEOUT_SECONDS": "20",
        "BACKEND_SYNC_BATCH_SIZE": "100",
        "FRESHNESS_STALE_AFTER_HOURS": "72",
        "FRESHNESS_EXPIRED_AFTER_HOURS": "336",
        "AI_ENRICHMENT_ENABLED": "false",
        "OPENAI_TIMEOUT_SECONDS": "30",
        "OPENAI_MAX_RETRIES": "2",
        "OPENAI_BATCH_SIZE": "10",
        "OPENAI_NORMALIZATION_BATCH_SIZE": "5",
        "OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS": "1000",
        "DEALLS_BASE_URL": "https://dealls.com",
        "DEALLS_RATE_LIMIT_PER_MINUTE": "30",
        "GLINTS_GRAPHQL_URL": "https://glints.com/graphql",
        "GLINTS_COUNTRY_CODE": "ID",
        "GLINTS_RATE_LIMIT_PER_MINUTE": "30",
        "JOBSTREET_GRAPHQL_URL": "https://id.jobstreet.com/graphql",
        "JOBSTREET_ENABLED": "false",
        "JOBSTREET_RATE_LIMIT_PER_MINUTE": "20",
        "KALIBRR_BASE_URL": "https://www.kalibrr.com",
        "KALIBRR_BUILD_ID_REFRESH_ENABLED": "true",
        "KALIBRR_RATE_LIMIT_PER_MINUTE": "30",
        "SCRAPER_INTERNAL_SERVICE_TOKEN": "test-service-token",
        "REQUEST_BODY_LIMIT": "1mb",
        "RATE_LIMIT_WINDOW_MS": "60000",
        "RATE_LIMIT_MAX": "120",
        "LOG_LEVEL": "silent",
        "REQUEST_ID_HEADER": "x-request-id",
        "ENABLE_REQUEST_LOGGING": "false",
        "HEALTH_CHECK_TIMEOUT_MS": "2",
    }
    values.update(overrides)
    return values


def test_settings_load_required_values() -> None:
    settings = Settings(**valid_env(), _env_file=None)

    assert settings.app_name == "bisakerja-scraper"
    assert settings.app_env is AppEnvironment.TEST
    assert settings.backend_database_url is None
    assert settings.cors_origins is None
    assert settings.openai_normalization_batch_size == 5
    assert settings.openai_normalization_inter_batch_delay_ms == 1000


def test_settings_accept_postgres_scheme_alias() -> None:
    settings = Settings(
        **valid_env(SCRAPER_DATABASE_URL="postgres://user:pass@localhost:5432/scraper_test"),
        _env_file=None,
    )

    assert settings.scraper_database_url.startswith("postgres://")


def test_missing_required_env_fails_fast() -> None:
    env = valid_env()
    del env["SCRAPER_DATABASE_URL"]

    with pytest.raises(ValidationError, match="SCRAPER_DATABASE_URL"):
        Settings(**env, _env_file=None)


def test_empty_required_env_fails_fast() -> None:
    env = valid_env(APP_NAME="")

    with pytest.raises(ValidationError, match="APP_NAME"):
        Settings(**env, _env_file=None)


def test_backend_sync_requires_target_and_token() -> None:
    env = valid_env(BACKEND_SYNC_ENABLED="true")

    with pytest.raises(ValidationError, match="BACKEND_DATABASE_URL"):
        Settings(**env, _env_file=None)


def test_backend_sync_batch_size_matches_backend_endpoint_limit() -> None:
    env = valid_env(BACKEND_SYNC_BATCH_SIZE="101")

    with pytest.raises(ValidationError, match="BACKEND_SYNC_BATCH_SIZE"):
        Settings(**env, _env_file=None)


def test_jobstreet_token_required_when_enabled() -> None:
    env = valid_env(JOBSTREET_ENABLED="true")

    with pytest.raises(ValidationError, match="JOBSTREET_BEARER_TOKEN"):
        Settings(**env, _env_file=None)


def test_ai_enrichment_disabled_does_not_require_openai_secrets() -> None:
    settings = Settings(**valid_env(), _env_file=None)

    assert settings.ai_enrichment_enabled is False
    assert settings.openai_api_key is None
    assert settings.openai_base_url is None
    assert settings.openai_model is None
    assert settings.openai_models == ()


def test_ai_enrichment_requires_openai_key_base_url_and_model() -> None:
    env = valid_env(AI_ENRICHMENT_ENABLED="true")

    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(**env, _env_file=None)


def test_ai_enrichment_accepts_custom_absolute_base_url() -> None:
    env = valid_env(
        AI_ENRICHMENT_ENABLED="true",
        OPENAI_API_KEY="test-openai-key",
        OPENAI_BASE_URL="https://openai-compatible.example.test/v1",
        OPENAI_MODEL="gpt-4o-mini",
    )

    settings = Settings(**env, _env_file=None)

    assert str(settings.openai_base_url) == "https://openai-compatible.example.test/v1"
    assert settings.openai_models == ("gpt-4o-mini",)


def test_openai_model_parses_csv_and_trims_each_item() -> None:
    settings = Settings(
        **valid_env(
            AI_ENRICHMENT_ENABLED="true",
            OPENAI_API_KEY="test-openai-key",
            OPENAI_BASE_URL="https://api.openai.com/v1",
            OPENAI_MODEL=" gpt-4o-mini , gpt-4.1-mini , o4-mini ",
        ),
        _env_file=None,
    )

    assert settings.openai_model == "gpt-4o-mini,gpt-4.1-mini,o4-mini"
    assert settings.openai_models == ("gpt-4o-mini", "gpt-4.1-mini", "o4-mini")


def test_ai_enrichment_rejects_relative_base_url() -> None:
    env = valid_env(
        AI_ENRICHMENT_ENABLED="true",
        OPENAI_API_KEY="test-openai-key",
        OPENAI_BASE_URL="/v1",
        OPENAI_MODEL="gpt-4o-mini",
    )

    with pytest.raises(ValidationError, match="OPENAI_BASE_URL"):
        Settings(**env, _env_file=None)


def test_openai_model_rejects_empty_csv_entries() -> None:
    env = valid_env(
        AI_ENRICHMENT_ENABLED="true",
        OPENAI_API_KEY="test-openai-key",
        OPENAI_BASE_URL="https://api.openai.com/v1",
        OPENAI_MODEL="gpt-4o-mini,,gpt-4.1-mini",
    )

    with pytest.raises(ValidationError, match="OPENAI_MODEL"):
        Settings(**env, _env_file=None)


def test_scraper_keywords_trim_deduplicate_and_preserve_symbols() -> None:
    env = valid_env(SCRAPER_KEYWORDS=" Developer , developer, ui/ux, c++, full stack ")

    settings = Settings(**env, _env_file=None)

    assert settings.scraper_keywords == ("Developer", "ui/ux", "c++", "full stack")


def test_scraper_keywords_reject_empty_entries() -> None:
    env = valid_env(SCRAPER_KEYWORDS="developer,,intern")

    with pytest.raises(ValidationError, match="SCRAPER_KEYWORDS"):
        Settings(**env, _env_file=None)


def test_scraper_limit_rejects_unsafe_values() -> None:
    env = valid_env(SCRAPER_MAX_ITEMS_PER_KEYWORD="101")

    with pytest.raises(ValidationError, match="SCRAPER_MAX_ITEMS_PER_KEYWORD"):
        Settings(**env, _env_file=None)


def test_scraper_recency_days_rejects_invalid_values() -> None:
    env = valid_env(SCRAPER_RECENCY_DAYS="0")

    with pytest.raises(ValidationError, match="SCRAPER_RECENCY_DAYS"):
        Settings(**env, _env_file=None)


def test_env_example_is_valid() -> None:
    env_example = Path(__file__).parents[3] / ".env.example"

    settings = Settings(_env_file=env_example)

    assert settings.app_name == "bisakerja-scraper"
