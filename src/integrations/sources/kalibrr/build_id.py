from __future__ import annotations

import json
from typing import Any, Protocol

from core.errors import FetchError, ParseError
from shared.http import JsonHttpClient

KALIBRR_SOURCE_PLATFORM = "kalibrr"
KALIBRR_HOME_PATH = "/id-ID/home"
NEXT_DATA_MARKER = '<script id="__NEXT_DATA__" type="application/json">'


class HtmlHttpClient(Protocol):
    async def request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Return response text or raise FetchError."""


class KalibrrBuildIdResolver:
    def __init__(self, html_client: HtmlHttpClient) -> None:
        self.html_client = html_client
        self._cached_build_id: str | None = None

    async def resolve(self, *, force_refresh: bool = False) -> str:
        if self._cached_build_id is not None and not force_refresh:
            return self._cached_build_id

        html = await self.html_client.request_text(
            "GET",
            KALIBRR_HOME_PATH,
            headers={"accept": "text/html"},
        )
        build_id = parse_kalibrr_build_id_from_html(html)
        self._cached_build_id = build_id
        return build_id

    async def refresh_after_stale_response(self, error: FetchError) -> str:
        if error.details.get("statusCode") != 404:
            raise error
        return await self.resolve(force_refresh=True)


def parse_kalibrr_build_id_from_html(html: str) -> str:
    next_data = _extract_next_data(html)
    build_id = next_data.get("buildId")
    if not isinstance(build_id, str) or not build_id:
        raise ParseError(
            "Kalibrr page data missing buildId",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )
    return build_id


async def request_kalibrr_data_with_build_refresh(
    *,
    json_client: JsonHttpClient,
    resolver: KalibrrBuildIdResolver,
    path_template: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    build_id = await resolver.resolve()
    try:
        return await json_client.request_json(
            "GET",
            path_template.format(build_id=build_id),
            params=params,
            headers={"x-nextjs-data": "1"},
        )
    except FetchError as exc:
        refreshed_build_id = await resolver.refresh_after_stale_response(exc)
        return await json_client.request_json(
            "GET",
            path_template.format(build_id=refreshed_build_id),
            params=params,
            headers={"x-nextjs-data": "1"},
        )


def _extract_next_data(html: str) -> dict[str, Any]:
    marker_start = html.find(NEXT_DATA_MARKER)
    if marker_start == -1:
        raise ParseError(
            "Kalibrr page missing __NEXT_DATA__ script",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    json_start = marker_start + len(NEXT_DATA_MARKER)
    json_end = html.find("</script>", json_start)
    if json_end == -1:
        raise ParseError(
            "Kalibrr page has unterminated __NEXT_DATA__ script",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )

    try:
        decoded = json.loads(html[json_start:json_end])
    except json.JSONDecodeError as exc:
        raise ParseError(
            "Kalibrr page data is not valid JSON",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        ) from exc

    if not isinstance(decoded, dict):
        raise ParseError(
            "Kalibrr page data root must be an object",
            source_platform=KALIBRR_SOURCE_PLATFORM,
        )
    return decoded
