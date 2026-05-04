from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import URL, make_url

_POSTGRES_SYNC_DRIVERS = {
    "postgresql",
    "postgresql+asyncpg",
    "postgresql+psycopg_async",
}
_POSTGRES_ASYNC_DRIVERS = {
    "postgresql",
    "postgresql+psycopg",
    "postgresql+psycopg_async",
}
_NEON_HOST_SUFFIX = ".neon.tech"


def to_sync_postgres_url(database_url: str) -> str:
    return _normalize_postgres_url(
        database_url,
        sync=True,
    )


def to_async_postgres_url(database_url: str) -> str:
    return _normalize_postgres_url(
        database_url,
        sync=False,
    )


def _normalize_postgres_url(database_url: str, *, sync: bool) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        return database_url

    normalized = _set_driver(url, sync=sync)
    if _is_neon_host(normalized):
        normalized = _normalize_neon_query(normalized, sync=sync)
    return normalized.render_as_string(hide_password=False)


def _set_driver(url: URL, *, sync: bool) -> URL:
    if sync and url.drivername in _POSTGRES_SYNC_DRIVERS:
        return url.set(drivername="postgresql+psycopg")
    if (not sync) and url.drivername in _POSTGRES_ASYNC_DRIVERS:
        return url.set(drivername="postgresql+asyncpg")
    return url


def _normalize_neon_query(url: URL, *, sync: bool) -> URL:
    query = dict(url.query)
    lowered_map = {key.lower(): key for key in query}

    if not sync:
        # asyncpg does not support libpq's channel_binding URL parameter.
        _drop_query_key(query, lowered_map, "channel_binding")

    if "sslmode" not in lowered_map:
        query["sslmode"] = "require"

    return url.set(query=query)


def _drop_query_key(
    query: dict[str, Any],
    lowered_map: Mapping[str, str],
    key: str,
) -> None:
    original_key = lowered_map.get(key)
    if original_key is not None:
        query.pop(original_key, None)


def _is_neon_host(url: URL) -> bool:
    host = url.host or ""
    return host.endswith(_NEON_HOST_SUFFIX)
