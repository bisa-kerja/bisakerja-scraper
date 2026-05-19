from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config.database_urls import to_sync_postgres_url


@dataclass(frozen=True)
class BackendIdentity:
    source_platform: str
    external_id: str
    job_id: str


class BackendIdentityLookupError(RuntimeError):
    pass


class BackendIdentityLookup:
    def __init__(self, *, database_url: str) -> None:
        sync_url = to_sync_postgres_url(database_url)
        self.engine: Engine = create_engine(sync_url, pool_pre_ping=True)

    def find_existing(
        self,
        *,
        identities: set[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        if not identities:
            return {}

        sources = sorted({source for source, _ in identities if source})
        external_ids = sorted({external_id for _, external_id in identities if external_id})
        if not sources or not external_ids:
            return {}

        try:
            with self.engine.connect() as connection:
                source_rows = connection.execute(
                    text(
                        """
                        SELECT id, slug
                        FROM source_platforms
                        WHERE slug = ANY(:slugs)
                        """
                    ),
                    {"slugs": sources},
                ).mappings()
                source_id_by_slug = {
                    str(row["slug"]).strip().lower(): str(row["id"])
                    for row in source_rows
                    if row.get("slug") and row.get("id")
                }
                if not source_id_by_slug:
                    return {}

                job_rows = connection.execute(
                    text(
                        """
                        SELECT id, source_platform_id, external_job_id, updated_at
                        FROM job_listings
                        WHERE source_platform_id = ANY(:source_ids)
                          AND external_job_id = ANY(:external_ids)
                        """
                    ),
                    {
                        "source_ids": list(source_id_by_slug.values()),
                        "external_ids": external_ids,
                    },
                ).mappings()
        except Exception as exc:  # noqa: BLE001
            raise BackendIdentityLookupError("backend identity lookup failed") from exc

        slug_by_source_id = {source_id: slug for slug, source_id in source_id_by_slug.items()}
        existing: dict[tuple[str, str], dict[str, Any]] = {}
        for row in job_rows:
            source_id = str(row["source_platform_id"])
            source_slug = slug_by_source_id.get(source_id)
            external_id = str(row["external_job_id"]).strip().lower()
            if source_slug is None or not external_id:
                continue
            key = (source_slug, external_id)
            if key not in identities:
                continue
            existing[key] = {
                "jobId": str(row["id"]),
                "updatedAt": row.get("updated_at"),
            }
        return existing
