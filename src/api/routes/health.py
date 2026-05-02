from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request

from api.readiness import ReadinessError
from api.responses import error_response, success_response

ReadinessCheck = Callable[[], Awaitable[None]]


def create_health_router(readiness_check: ReadinessCheck | None = None) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health/live")
    async def live() -> object:
        return success_response(
            message="Service is live",
            data={"status": "live"},
        )

    @router.get("/health/ready")
    async def ready(request: Request) -> object:
        check = readiness_check or getattr(request.app.state, "readiness_check", None)
        if check is None:
            return error_response(
                message="Readiness check is not configured",
                code="SERVICE_UNAVAILABLE",
                status_code=503,
                details={"dependency": "scraper-db"},
                request_id=request.state.request_id,
            )

        try:
            await check()
        except ReadinessError as exc:
            return error_response(
                message="Service dependency is unavailable",
                code="SERVICE_UNAVAILABLE",
                status_code=503,
                details={"dependency": exc.dependency},
                request_id=request.state.request_id,
            )

        return success_response(
            message="Service is ready",
            data={"status": "ready"},
        )

    return router
