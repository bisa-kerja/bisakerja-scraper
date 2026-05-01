"""Dealls source adapter."""

from integrations.sources.dealls.detail import (
    DEALLS_DETAIL_DEFAULT_PARAMS,
    DEALLS_DETAIL_SLUG_PATH_TEMPLATE,
    DeallsDetailAdapter,
    DeallsDetailResult,
    merge_dealls_list_and_detail,
    parse_dealls_detail_payload,
)
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
from integrations.sources.dealls.mapper import map_dealls_job

__all__ = [
    "DEALLS_DETAIL_DEFAULT_PARAMS",
    "DEALLS_DETAIL_SLUG_PATH_TEMPLATE",
    "DEALLS_DEFAULT_HEADERS",
    "DEALLS_LIST_PATH",
    "DEALLS_SOURCE_PLATFORM",
    "DeallsDetailAdapter",
    "DeallsDetailResult",
    "DeallsListAdapter",
    "DeallsListQuery",
    "DeallsListResult",
    "DeallsPagination",
    "RawSourceJob",
    "build_dealls_http_client",
    "build_dealls_source_url",
    "merge_dealls_list_and_detail",
    "map_dealls_job",
    "parse_dealls_detail_payload",
    "parse_dealls_list_payload",
]
