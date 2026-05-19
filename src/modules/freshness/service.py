from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import NormalizedJob


@dataclass(frozen=True)
class FreshnessPolicy:
    stale_after_hours: int
    expired_after_hours: int

    def __post_init__(self) -> None:
        if self.stale_after_hours < 1:
            raise ValueError("stale_after_hours must be positive")
        if self.expired_after_hours <= self.stale_after_hours:
            raise ValueError("expired_after_hours must be greater than stale_after_hours")


@dataclass
class FreshnessSweepSummary:
    source_platform: str
    active_count: int = 0
    stale_count: int = 0
    expired_count: int = 0
    reactivated_count: int = 0
    unchanged_count: int = 0
    metadata: dict[str, int] = field(default_factory=dict)


class FreshnessService:
    def __init__(self, session: Session, *, policy: FreshnessPolicy) -> None:
        self.session = session
        self.policy = policy

    def sweep_source(
        self,
        *,
        source_platform: str,
        seen_external_ids: set[str],
        source_run_successful: bool,
        now: datetime | None = None,
    ) -> FreshnessSweepSummary:
        current_time = now or datetime.now(UTC)
        summary = FreshnessSweepSummary(source_platform=source_platform)
        jobs = list(
            self.session.scalars(
                select(NormalizedJob)
                .where(NormalizedJob.source_platform == source_platform)
                .order_by(NormalizedJob.external_id.asc())
            ).all()
        )

        for job in jobs:
            if job.external_id in seen_external_ids:
                if job.status != CanonicalJobStatus.ACTIVE.value:
                    summary.reactivated_count += 1
                else:
                    summary.unchanged_count += 1
                job.status = CanonicalJobStatus.ACTIVE.value
                job.last_seen_at = current_time
                continue

            if not source_run_successful:
                summary.unchanged_count += 1
                continue

            age = current_time - job.last_seen_at
            if age >= timedelta(hours=self.policy.expired_after_hours):
                if job.status != CanonicalJobStatus.EXPIRED.value:
                    summary.expired_count += 1
                else:
                    summary.unchanged_count += 1
                job.status = CanonicalJobStatus.EXPIRED.value
            elif age >= timedelta(hours=self.policy.stale_after_hours):
                if job.status != CanonicalJobStatus.STALE.value:
                    summary.stale_count += 1
                else:
                    summary.unchanged_count += 1
                job.status = CanonicalJobStatus.STALE.value
            else:
                summary.unchanged_count += 1

        summary.active_count = sum(
            1 for job in jobs if job.status == CanonicalJobStatus.ACTIVE.value
        )
        summary.metadata = {
            "seen": len(seen_external_ids),
            "total": len(jobs),
        }
        self.session.flush()
        return summary
