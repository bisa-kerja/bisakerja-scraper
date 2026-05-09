from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import AnyUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

NonEmptyStr = Annotated[str, Field(min_length=1)]


class AppEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    SILENT = "silent"


class ScraperRecencyMode(StrEnum):
    LATEST = "latest"
    NATIVE = "native"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        validate_default=True,
        enable_decoding=False,
    )

    app_name: NonEmptyStr = Field(validation_alias="APP_NAME")
    app_env: AppEnvironment = Field(validation_alias="APP_ENV")
    port: int = Field(validation_alias="PORT", gt=0, le=65535)
    api_prefix: NonEmptyStr = Field(validation_alias="API_PREFIX")

    scraper_database_url: NonEmptyStr = Field(validation_alias="SCRAPER_DATABASE_URL")
    backend_database_url: NonEmptyStr | None = Field(
        default=None,
        validation_alias="BACKEND_DATABASE_URL",
    )
    backend_sync_enabled: bool = Field(validation_alias="BACKEND_SYNC_ENABLED")
    run_database_tests: bool = Field(validation_alias="RUN_DATABASE_TESTS")

    scrape_schedule_cron: NonEmptyStr = Field(validation_alias="SCRAPE_SCHEDULE_CRON")
    normalize_schedule_cron: NonEmptyStr = Field(validation_alias="NORMALIZE_SCHEDULE_CRON")
    enrich_schedule_cron: NonEmptyStr = Field(validation_alias="ENRICH_SCHEDULE_CRON")
    sync_schedule_cron: NonEmptyStr = Field(validation_alias="SYNC_SCHEDULE_CRON")
    notify_handoff_schedule_cron: NonEmptyStr = Field(
        validation_alias="NOTIFY_HANDOFF_SCHEDULE_CRON"
    )
    worker_concurrency: int = Field(validation_alias="WORKER_CONCURRENCY", ge=1, le=32)
    scraper_run_lock_ttl_seconds: int = Field(
        validation_alias="SCRAPER_RUN_LOCK_TTL_SECONDS",
        ge=60,
    )

    http_timeout_seconds: float = Field(validation_alias="HTTP_TIMEOUT_SECONDS", gt=0)
    http_max_retries: int = Field(validation_alias="HTTP_MAX_RETRIES", ge=0, le=10)
    http_response_max_bytes: int = Field(validation_alias="HTTP_RESPONSE_MAX_BYTES", ge=1024)
    default_rate_limit_per_minute: int = Field(
        validation_alias="DEFAULT_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    scraper_keywords: tuple[str, ...] = Field(validation_alias="SCRAPER_KEYWORDS")
    scraper_max_items_per_keyword: int = Field(
        validation_alias="SCRAPER_MAX_ITEMS_PER_KEYWORD",
        ge=1,
        le=1000,
    )
    scraper_max_items_per_source_run: int = Field(
        default=2000,
        validation_alias="SCRAPER_MAX_ITEMS_PER_SOURCE_RUN",
        ge=1,
        le=10000,
    )
    scraper_max_pages_per_keyword: int = Field(
        default=50,
        validation_alias="SCRAPER_MAX_PAGES_PER_KEYWORD",
        ge=1,
        le=500,
    )
    scraper_target_total_jobs_per_run: int = Field(
        default=1000,
        validation_alias="SCRAPER_TARGET_TOTAL_JOBS_PER_RUN",
        ge=1,
        le=50000,
    )
    scraper_detail_fetch_concurrency: int = Field(
        default=4,
        validation_alias="SCRAPER_DETAIL_FETCH_CONCURRENCY",
        ge=1,
        le=32,
    )
    scraper_recency_mode: ScraperRecencyMode = Field(validation_alias="SCRAPER_RECENCY_MODE")
    scraper_recency_days: int = Field(
        validation_alias="SCRAPER_RECENCY_DAYS",
        ge=1,
        le=365,
    )

    backend_sync_base_url: NonEmptyStr | None = Field(
        default=None,
        validation_alias="BACKEND_SYNC_BASE_URL",
    )
    backend_sync_service_token: SecretStr | None = Field(
        default=None,
        validation_alias="BACKEND_SYNC_SERVICE_TOKEN",
    )
    backend_sync_timeout_seconds: float = Field(
        validation_alias="BACKEND_SYNC_TIMEOUT_SECONDS",
        gt=0,
    )
    backend_sync_batch_size: int = Field(
        validation_alias="BACKEND_SYNC_BATCH_SIZE",
        ge=1,
        le=100,
    )
    freshness_stale_after_hours: int = Field(
        validation_alias="FRESHNESS_STALE_AFTER_HOURS",
        ge=1,
    )
    freshness_expired_after_hours: int = Field(
        validation_alias="FRESHNESS_EXPIRED_AFTER_HOURS",
        ge=1,
    )

    ai_enrichment_enabled: bool = Field(validation_alias="AI_ENRICHMENT_ENABLED")
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    openai_base_url: AnyUrl | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: NonEmptyStr | None = Field(default=None, validation_alias="OPENAI_MODEL")
    openai_models: tuple[NonEmptyStr, ...] = ()
    openai_timeout_seconds: float = Field(validation_alias="OPENAI_TIMEOUT_SECONDS", gt=0)
    openai_max_retries: int = Field(validation_alias="OPENAI_MAX_RETRIES", ge=0, le=10)
    openai_batch_size: int = Field(validation_alias="OPENAI_BATCH_SIZE", ge=1, le=100)
    openai_normalization_batch_size: int = Field(
        validation_alias="OPENAI_NORMALIZATION_BATCH_SIZE",
        ge=1,
        le=50,
    )
    openai_normalization_inter_batch_delay_ms: int = Field(
        validation_alias="OPENAI_NORMALIZATION_INTER_BATCH_DELAY_MS",
        ge=0,
        le=60000,
    )

    dealls_enabled: bool = Field(validation_alias="DEALLS_ENABLED")
    dealls_base_url: NonEmptyStr = Field(validation_alias="DEALLS_BASE_URL")
    dealls_rate_limit_per_minute: int = Field(
        validation_alias="DEALLS_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    dealls_page_size: int = Field(default=20, validation_alias="DEALLS_PAGE_SIZE", ge=1, le=20)
    glints_enabled: bool = Field(validation_alias="GLINTS_ENABLED")
    glints_graphql_url: NonEmptyStr = Field(validation_alias="GLINTS_GRAPHQL_URL")
    glints_country_code: NonEmptyStr = Field(validation_alias="GLINTS_COUNTRY_CODE")
    glints_rate_limit_per_minute: int = Field(
        validation_alias="GLINTS_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    glints_page_size: int = Field(default=30, validation_alias="GLINTS_PAGE_SIZE", ge=1, le=30)
    jobstreet_graphql_url: NonEmptyStr = Field(validation_alias="JOBSTREET_GRAPHQL_URL")
    jobstreet_enabled: bool = Field(validation_alias="JOBSTREET_ENABLED")
    jobstreet_bearer_token: SecretStr | None = Field(
        default=None,
        validation_alias="JOBSTREET_BEARER_TOKEN",
    )
    jobstreet_cookie: SecretStr | None = Field(
        default=None,
        validation_alias="JOBSTREET_COOKIE",
    )
    jobstreet_rate_limit_per_minute: int = Field(
        validation_alias="JOBSTREET_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    jobstreet_page_size: int = Field(
        default=32,
        validation_alias="JOBSTREET_PAGE_SIZE",
        ge=1,
        le=100,
    )
    kalibrr_enabled: bool = Field(validation_alias="KALIBRR_ENABLED")
    kalibrr_base_url: NonEmptyStr = Field(validation_alias="KALIBRR_BASE_URL")
    kalibrr_build_id_refresh_enabled: bool = Field(
        validation_alias="KALIBRR_BUILD_ID_REFRESH_ENABLED",
    )
    kalibrr_rate_limit_per_minute: int = Field(
        validation_alias="KALIBRR_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    kalibrr_page_size: int = Field(
        default=30,
        validation_alias="KALIBRR_PAGE_SIZE",
        ge=1,
        le=100,
    )
    kitalulus_enabled: bool = Field(validation_alias="KITALULUS_ENABLED")
    kitalulus_graphql_url: NonEmptyStr = Field(validation_alias="KITALULUS_GRAPHQL_URL")
    kitalulus_rate_limit_per_minute: int = Field(
        validation_alias="KITALULUS_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    kitalulus_page_size: int = Field(
        default=30,
        validation_alias="KITALULUS_PAGE_SIZE",
        ge=1,
        le=100,
    )

    scraper_internal_service_token: SecretStr = Field(
        validation_alias="SCRAPER_INTERNAL_SERVICE_TOKEN",
    )
    cors_origins: NonEmptyStr | None = Field(default=None, validation_alias="CORS_ORIGINS")
    request_body_limit: NonEmptyStr = Field(validation_alias="REQUEST_BODY_LIMIT")
    rate_limit_window_ms: int = Field(validation_alias="RATE_LIMIT_WINDOW_MS", ge=1)
    rate_limit_max: int = Field(validation_alias="RATE_LIMIT_MAX", ge=1)

    log_level: LogLevel = Field(validation_alias="LOG_LEVEL")
    request_id_header: NonEmptyStr = Field(validation_alias="REQUEST_ID_HEADER")
    enable_request_logging: bool = Field(validation_alias="ENABLE_REQUEST_LOGGING")
    health_check_timeout_seconds: float = Field(validation_alias="HEALTH_CHECK_TIMEOUT_MS", gt=0)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("API_PREFIX must start with '/'")
        return value.rstrip("/") or "/"

    @field_validator(
        "scraper_database_url",
        "backend_database_url",
        mode="after",
    )
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = make_url(value)
        except Exception as exc:  # pragma: no cover - parser detail already tested upstream
            raise ValueError("database URL must be a valid SQLAlchemy URL") from exc
        if parsed.get_backend_name() not in {"postgresql", "postgres"}:
            raise ValueError("database URL must use postgres or postgresql scheme")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str | None) -> str | None:
        if value is None:
            return value
        origins = [origin.strip() for origin in value.split(",")]
        if any(not origin for origin in origins):
            raise ValueError("CORS_ORIGINS must not contain empty entries")
        return ",".join(origins)

    @field_validator("scraper_keywords", mode="before")
    @classmethod
    def parse_scraper_keywords(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            raw_keywords = value.split(",")
        elif isinstance(value, list | tuple):
            raw_keywords = list(value)
        else:
            raise ValueError("SCRAPER_KEYWORDS must be a comma-separated list")

        keywords: list[str] = []
        seen: set[str] = set()
        for raw_keyword in raw_keywords:
            if not isinstance(raw_keyword, str):
                raise ValueError("SCRAPER_KEYWORDS entries must be strings")
            keyword = raw_keyword.strip()
            if not keyword:
                raise ValueError("SCRAPER_KEYWORDS must not contain empty entries")
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(keyword)

        if not keywords:
            raise ValueError("SCRAPER_KEYWORDS must contain at least one keyword")
        return tuple(keywords)

    @field_validator("openai_model")
    @classmethod
    def validate_openai_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        models = [item.strip() for item in value.split(",")]
        if any(not item for item in models):
            raise ValueError("OPENAI_MODEL must not contain empty entries")
        if not models:
            raise ValueError("OPENAI_MODEL must contain at least one model")
        return ",".join(models)

    @field_validator(
        "backend_sync_service_token",
        "jobstreet_bearer_token",
        "jobstreet_cookie",
        "scraper_internal_service_token",
        "openai_api_key",
    )
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        if not value.get_secret_value():
            raise ValueError("secret values must be non-empty")
        return value

    @model_validator(mode="after")
    def validate_conditional_secrets(self) -> "Settings":
        self.openai_models = tuple(model for model in (self.openai_model or "").split(",") if model)
        if self.backend_sync_enabled:
            if self.backend_database_url is None:
                raise ValueError("BACKEND_DATABASE_URL is required when backend sync is enabled")
            if self.backend_sync_base_url is None:
                raise ValueError("BACKEND_SYNC_BASE_URL is required when backend sync is enabled")
            if self.backend_sync_service_token is None:
                raise ValueError(
                    "BACKEND_SYNC_SERVICE_TOKEN is required when backend sync is enabled"
                )

        if self.jobstreet_enabled and self.jobstreet_bearer_token is None:
            raise ValueError("JOBSTREET_BEARER_TOKEN is required when JobStreet is enabled")

        if self.ai_enrichment_enabled:
            if self.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY is required when AI enrichment is enabled")
            if self.openai_base_url is None:
                raise ValueError("OPENAI_BASE_URL is required when AI enrichment is enabled")
            if self.openai_model is None:
                raise ValueError("OPENAI_MODEL is required when AI enrichment is enabled")

        if self.freshness_expired_after_hours <= self.freshness_stale_after_hours:
            raise ValueError("FRESHNESS_EXPIRED_AFTER_HOURS must be greater than stale threshold")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
