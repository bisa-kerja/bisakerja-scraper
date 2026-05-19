from cli.pipeline import stop_reason_from_exception
from core.errors import FetchError, ParseError


def test_stop_reason_maps_cloudflare_blocker() -> None:
    reason = stop_reason_from_exception(
        FetchError(
            "blocked",
            source_platform="jobstreet",
            details={"statusCode": 403, "blocker": "cloudflare_challenge"},
            retryable=False,
        )
    )

    assert reason == "cloudflare_challenge"


def test_stop_reason_maps_auth_required_for_401() -> None:
    reason = stop_reason_from_exception(
        FetchError(
            "unauthorized",
            source_platform="jobstreet",
            details={"statusCode": 401},
            retryable=False,
        )
    )

    assert reason == "auth_required"


def test_stop_reason_maps_invalid_request_for_400() -> None:
    reason = stop_reason_from_exception(
        FetchError(
            "bad request",
            source_platform="dealls",
            details={"statusCode": 400},
            retryable=False,
        )
    )

    assert reason == "invalid_request"


def test_stop_reason_maps_parse_error() -> None:
    reason = stop_reason_from_exception(ParseError("invalid payload", source_platform="jobstreet"))

    assert reason == "parse_error"
