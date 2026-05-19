from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def success_response(
    *,
    message: str,
    data: Any,
    meta: dict[str, Any] | None = None,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": True, "message": message, "data": data, "meta": meta},
    )


def error_response(
    *,
    message: str,
    code: str,
    request_id: str,
    status_code: int,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": message,
            "data": None,
            "error": {"code": code, "details": details, "requestId": request_id},
        },
    )
