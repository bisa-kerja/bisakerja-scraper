from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

from config.settings import AppEnvironment, LogLevel

REDACTED = "<redacted>"

SECRET_KEY_PATTERN = re.compile(
    r"(authorization|bearer|cookie|csrf|token|secret|credential|password|session|"
    r"visitor|device|database_url|db_url|openai.*base.?url|ai.*base.?url)",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
COOKIE_PAIR_PATTERN = re.compile(
    r"(?i)(^|;\s*)([^=;\s]*(session|token|csrf|visitor|device)[^=;\s]*)=[^;]+"
)
POSTGRES_URL_PATTERN = re.compile(
    r"postgres(?:ql)?(?:\+[a-z0-9_]+)?://[^@\s]+@[^\s]+",
    re.IGNORECASE,
)


def new_correlation_id(prefix: str = "req") -> str:
    return f"{prefix}_{uuid4().hex}"


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if SECRET_KEY_PATTERN.search(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if isinstance(value, str):
        redacted = BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
        redacted = POSTGRES_URL_PATTERN.sub(f"postgresql://{REDACTED}", redacted)
        redacted = COOKIE_PAIR_PATTERN.sub(
            lambda match: f"{match.group(1)}{match.group(2)}={REDACTED}", redacted
        )
        return redacted
    return value


def add_service_context(
    service: str,
    env: AppEnvironment,
) -> structlog.typing.Processor:
    def processor(
        _logger: logging.Logger,
        _method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        event_dict.setdefault("service", service)
        event_dict.setdefault("env", env.value)
        return event_dict

    return processor


def redact_event(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return redact_sensitive(event_dict)


def configure_logging(
    *,
    service: str,
    env: AppEnvironment,
    level: LogLevel,
) -> None:
    if level is LogLevel.SILENT:
        logging.disable(logging.CRITICAL)
        min_level = logging.CRITICAL
    else:
        logging.disable(logging.NOTSET)
        min_level = getattr(logging, level.value.upper())

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=min_level, force=True)
    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            add_service_context(service, env),
            redact_event,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def bind_request_context(request_id: str | None = None, **extra: Any) -> str:
    active_request_id = request_id or new_correlation_id("req")
    bind_contextvars(requestId=active_request_id, **extra)
    return active_request_id


def bind_job_context(
    run_id: str | None = None, source_run_id: str | None = None, **extra: Any
) -> str:
    active_run_id = run_id or new_correlation_id("run")
    context = {"runId": active_run_id, **extra}
    if source_run_id is not None:
        context["sourceRunId"] = source_run_id
    bind_contextvars(**context)
    return active_run_id


def clear_log_context() -> None:
    clear_contextvars()


@contextmanager
def request_log_context(request_id: str | None = None, **extra: Any):
    clear_contextvars()
    active_request_id = bind_request_context(request_id, **extra)
    try:
        yield active_request_id
    finally:
        clear_contextvars()


@contextmanager
def job_log_context(run_id: str | None = None, source_run_id: str | None = None, **extra: Any):
    clear_contextvars()
    active_run_id = bind_job_context(run_id, source_run_id, **extra)
    try:
        yield active_run_id
    finally:
        clear_contextvars()
