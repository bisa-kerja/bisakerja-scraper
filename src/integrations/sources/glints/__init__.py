"""Glints source adapter."""

from integrations.sources.glints.fallback import (
    GlintsDetailFallbackResult,
    build_glints_detail_fallback,
)
from integrations.sources.glints.list import (
    GLINTS_DEFAULT_HEADERS,
    GLINTS_GRAPHQL_OPERATION,
    GLINTS_GRAPHQL_PATH,
    GLINTS_PUBLIC_JOB_BASE_URL,
    GLINTS_SEARCH_JOBS_QUERY,
    GLINTS_SOURCE_PLATFORM,
    GlintsListAdapter,
    GlintsListQuery,
    GlintsListResult,
    GlintsPagination,
    RawSourceJob,
    build_glints_http_client,
    build_glints_list_request_body,
    build_glints_source_url,
    extract_glints_source_timestamp,
    parse_glints_list_payload,
)
from integrations.sources.glints.mapper import map_glints_job

__all__ = [
    "GLINTS_DEFAULT_HEADERS",
    "GLINTS_GRAPHQL_OPERATION",
    "GLINTS_GRAPHQL_PATH",
    "GLINTS_PUBLIC_JOB_BASE_URL",
    "GLINTS_SEARCH_JOBS_QUERY",
    "GLINTS_SOURCE_PLATFORM",
    "GlintsDetailFallbackResult",
    "GlintsListAdapter",
    "GlintsListQuery",
    "GlintsListResult",
    "GlintsPagination",
    "RawSourceJob",
    "build_glints_detail_fallback",
    "build_glints_http_client",
    "build_glints_list_request_body",
    "build_glints_source_url",
    "extract_glints_source_timestamp",
    "map_glints_job",
    "parse_glints_list_payload",
]
