from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        validate_default=True,
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
    backend_sync_batch_size: int = Field(validation_alias="BACKEND_SYNC_BATCH_SIZE", ge=1)

    dealls_base_url: NonEmptyStr = Field(validation_alias="DEALLS_BASE_URL")
    dealls_rate_limit_per_minute: int = Field(
        validation_alias="DEALLS_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    glints_graphql_url: NonEmptyStr = Field(validation_alias="GLINTS_GRAPHQL_URL")
    glints_country_code: NonEmptyStr = Field(validation_alias="GLINTS_COUNTRY_CODE")
    glints_rate_limit_per_minute: int = Field(
        validation_alias="GLINTS_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    jobstreet_graphql_url: NonEmptyStr = Field(validation_alias="JOBSTREET_GRAPHQL_URL")
    jobstreet_enabled: bool = Field(validation_alias="JOBSTREET_ENABLED")
    jobstreet_bearer_token: SecretStr | None = Field(
        default=None,
        validation_alias="JOBSTREET_BEARER_TOKEN",
    )
    jobstreet_rate_limit_per_minute: int = Field(
        validation_alias="JOBSTREET_RATE_LIMIT_PER_MINUTE",
        ge=1,
    )
    kalibrr_base_url: NonEmptyStr = Field(validation_alias="KALIBRR_BASE_URL")
    kalibrr_build_id_refresh_enabled: bool = Field(
        validation_alias="KALIBRR_BUILD_ID_REFRESH_ENABLED",
    )
    kalibrr_rate_limit_per_minute: int = Field(
        validation_alias="KALIBRR_RATE_LIMIT_PER_MINUTE",
        ge=1,
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
        if not value.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("database URL must use postgresql or postgresql+asyncpg")
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

    @field_validator(
        "backend_sync_service_token",
        "jobstreet_bearer_token",
        "scraper_internal_service_token",
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

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
