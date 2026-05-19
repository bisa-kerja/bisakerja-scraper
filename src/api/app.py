from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.readiness import DatabaseReadinessChecker
from api.responses import error_response
from api.routes.health import create_health_router
from api.routes.jobs import JobSessionFactory, create_jobs_router
from config.logging import bind_request_context, clear_log_context, configure_logging
from config.settings import Settings, get_settings
from core.errors import ScraperError

ReadinessCheck = Callable[[], Awaitable[None]]


def create_app(
    *,
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
    job_session_factory: JobSessionFactory | None = None,
) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging(
        service=active_settings.app_name,
        env=active_settings.app_env,
        level=active_settings.log_level,
    )

    app = FastAPI(title=active_settings.app_name)
    app.state.settings = active_settings
    app.state.readiness_check = readiness_check or DatabaseReadinessChecker(
        active_settings.scraper_database_url,
        active_settings.health_check_timeout_seconds,
    )
    app.state.job_session_factory = job_session_factory

    register_request_id_middleware(app, active_settings)
    register_exception_handlers(app)
    app.include_router(create_health_router())
    app.include_router(create_jobs_router(), prefix=active_settings.api_prefix)
    return app


def register_request_id_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> object:
        request_id = request.headers.get(settings.request_id_header)
        active_request_id = bind_request_context(request_id)
        request.state.request_id = active_request_id
        try:
            response = await call_next(request)
        except Exception:
            structlog.get_logger(__name__).exception("unhandled_api_error")
            response = error_response(
                message="Unexpected server error",
                code="INTERNAL_SERVER_ERROR",
                status_code=500,
                details=None,
                request_id=active_request_id,
            )
        finally:
            clear_log_context()
        response.headers[settings.request_id_header] = active_request_id
        return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ScraperError)
    async def scraper_error_handler(request: Request, exc: ScraperError) -> object:
        structlog.get_logger(__name__).warning("scraper_api_error", **exc.to_log_fields())
        return error_response(
            message=exc.message,
            code=exc.code,
            status_code=500,
            details=exc.details or None,
            request_id=request.state.request_id,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> object:
        return error_response(
            message=str(exc.detail),
            code=code_for_status(exc.status_code),
            status_code=exc.status_code,
            details=None,
            request_id=request.state.request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> object:
        return error_response(
            message="Validation failed",
            code="VALIDATION_ERROR",
            status_code=422,
            details=[
                {
                    "path": ".".join(str(part) for part in error["loc"]),
                    "message": error["msg"],
                    "code": error["type"],
                }
                for error in exc.errors()
            ],
            request_id=request.state.request_id,
        )


def code_for_status(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_SERVER_ERROR",
        502: "DOWNSTREAM_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "INTERNAL_SERVER_ERROR")
