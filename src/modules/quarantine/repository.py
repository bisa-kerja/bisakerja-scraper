from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.persistence import NormalizationQuarantine, RawJob


class QuarantineStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class QuarantineInput:
    source_platform: str
    error_category: str
    error_message: str
    scrape_run_id: str | None = None
    raw_job_id: str | None = None
    external_id: str | None = None
    payload_hash: str | None = None
    source_field_path: str | None = None
    retryable: bool = False


class QuarantineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, item: QuarantineInput) -> NormalizationQuarantine:
        row = NormalizationQuarantine(
            scrape_run_id=item.scrape_run_id,
            raw_job_id=item.raw_job_id,
            source_platform=item.source_platform,
            external_id=item.external_id,
            status=QuarantineStatus.OPEN.value,
            payload_hash=item.payload_hash,
            error_category=item.error_category,
            error_message=item.error_message[:500],
            source_field_path=item.source_field_path,
            retryable=item.retryable,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def record_raw_job_failure(
        self,
        raw_job: RawJob,
        *,
        error_category: str,
        error_message: str,
        source_field_path: str | None = None,
        retryable: bool = False,
    ) -> NormalizationQuarantine:
        return self.record(
            QuarantineInput(
                scrape_run_id=raw_job.scrape_run_id,
                raw_job_id=raw_job.id,
                source_platform=raw_job.source_platform,
                external_id=raw_job.external_id,
                payload_hash=raw_job.payload_hash,
                error_category=error_category,
                error_message=error_message,
                source_field_path=source_field_path,
                retryable=retryable,
            )
        )

    def list_open(self, *, source_platform: str | None = None) -> list[NormalizationQuarantine]:
        statement = select(NormalizationQuarantine).where(
            NormalizationQuarantine.status == QuarantineStatus.OPEN.value
        )
        if source_platform is not None:
            statement = statement.where(NormalizationQuarantine.source_platform == source_platform)
        return list(
            self.session.scalars(statement.order_by(NormalizationQuarantine.created_at.asc())).all()
        )

    def resolve_for_raw_job(self, raw_job_id: str) -> int:
        rows = self.session.scalars(
            select(NormalizationQuarantine).where(
                NormalizationQuarantine.raw_job_id == raw_job_id,
                NormalizationQuarantine.status == QuarantineStatus.OPEN.value,
            )
        ).all()
        now = datetime.now(UTC)
        for row in rows:
            row.status = QuarantineStatus.RESOLVED.value
            row.resolved_at = now
        self.session.flush()
        return len(rows)
