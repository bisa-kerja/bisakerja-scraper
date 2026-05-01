"""Dealls source adapter."""

from integrations.sources.dealls.list import (
    DEALLS_DEFAULT_HEADERS,
    DEALLS_LIST_PATH,
    DEALLS_SOURCE_PLATFORM,
    DeallsListAdapter,
    DeallsListQuery,
    DeallsListResult,
    DeallsPagination,
    RawSourceJob,
    build_dealls_http_client,
    build_dealls_source_url,
    parse_dealls_list_payload,
)

__all__ = [
    "DEALLS_DEFAULT_HEADERS",
    "DEALLS_LIST_PATH",
    "DEALLS_SOURCE_PLATFORM",
    "DeallsListAdapter",
    "DeallsListQuery",
    "DeallsListResult",
    "DeallsPagination",
    "RawSourceJob",
    "build_dealls_http_client",
    "build_dealls_source_url",
    "parse_dealls_list_payload",
]
