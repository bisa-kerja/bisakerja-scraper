from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.errors import PersistError
from modules.jobs.schemas import CanonicalJobSchema
from modules.persistence.models import NormalizedJob, RawJob


@dataclass(frozen=True)
class RawJobInput:
    scrape_run_id: str
    source_platform: str
    external_id: str
    source_url: str | None
    raw_payload: dict[str, Any]
    scraped_at: datetime | None = None


@dataclass(frozen=True)
class PersistenceResult:
    raw_job: RawJob
    normalized_job: NormalizedJob
    raw_created: bool
    normalized_created: bool


class JobPersistenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_raw_job(self, job: RawJobInput) -> tuple[RawJob, bool]:
        existing = self.session.scalar(
            select(RawJob).where(
                RawJob.source_platform == job.source_platform,
                RawJob.external_id == job.external_id,
            )
        )
        payload_hash = stable_payload_hash(job.raw_payload)
        scraped_at = job.scraped_at or utc_now()

        if existing is None:
            raw_job = RawJob(
                scrape_run_id=job.scrape_run_id,
                source_platform=job.source_platform,
                external_id=job.external_id,
                source_url=job.source_url,
                raw_payload=job.raw_payload,
                payload_hash=payload_hash,
                scraped_at=scraped_at,
            )
            self.session.add(raw_job)
            self.session.flush()
            return raw_job, True

        existing.scrape_run_id = job.scrape_run_id
        existing.source_url = job.source_url
        existing.raw_payload = job.raw_payload
        existing.payload_hash = payload_hash
        existing.scraped_at = scraped_at
        self.session.flush()
        return existing, False

    def upsert_normalized_job(
        self,
        job: CanonicalJobSchema,
        *,
        raw_job_id: str | None = None,
    ) -> tuple[NormalizedJob, bool]:
        source = job.source
        existing = self.session.scalar(
            select(NormalizedJob).where(
                NormalizedJob.source_platform == source.platform.value,
                NormalizedJob.external_id == source.external_job_id,
            )
        )
        payload = job.model_dump(mode="json")
        status = job.status.value

        if existing is None:
            normalized_job = NormalizedJob(
                raw_job_id=raw_job_id,
                source_platform=source.platform.value,
                external_id=source.external_job_id,
                title=job.title,
                company_name=job.company.name,
                source_url=source.source_url,
                apply_url=source.external_apply_url,
                status=status,
                normalized_payload=payload,
                last_seen_at=job.last_seen_at,
                posted_at=job.posted_at,
            )
            self.session.add(normalized_job)
            self.session.flush()
            return normalized_job, True

        existing.raw_job_id = raw_job_id
        existing.title = job.title
        existing.company_name = job.company.name
        existing.source_url = source.source_url
        existing.apply_url = source.external_apply_url
        existing.status = status
        existing.normalized_payload = payload
        existing.last_seen_at = job.last_seen_at
        existing.posted_at = job.posted_at
        self.session.flush()
        return existing, False

    def write_job(self, raw_input: RawJobInput, job: CanonicalJobSchema) -> PersistenceResult:
        transaction = nullcontext() if self.session.in_transaction() else self.session.begin()
        try:
            with transaction:
                raw_job, raw_created = self.upsert_raw_job(raw_input)
                normalized_job, normalized_created = self.upsert_normalized_job(
                    job,
                    raw_job_id=raw_job.id,
                )
            return PersistenceResult(
                raw_job=raw_job,
                normalized_job=normalized_job,
                raw_created=raw_created,
                normalized_created=normalized_created,
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise PersistError(
                "job persistence write failed",
                source_platform=raw_input.source_platform,
                external_id=raw_input.external_id,
                details={"error": exc.__class__.__name__},
            ) from exc


def stable_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)
