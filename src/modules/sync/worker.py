from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from integrations.backend import BackendSyncClient, BackendSyncClientError, BackendSyncServerError
from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import NormalizedJob
from modules.sync.events import SyncEventRepository, SyncFailure, SyncSuccess

SYNC_ELIGIBLE_STATUSES = {
    CanonicalJobStatus.ACTIVE.value,
    CanonicalJobStatus.STALE.value,
    CanonicalJobStatus.EXPIRED.value,
}


@dataclass(frozen=True)
class BackendSyncWorkerResult:
    attempted: int
    sent: int
    failed: int


class BackendSyncWorker:
    def __init__(
        self,
        *,
        session: Session,
        client: BackendSyncClient,
        events: SyncEventRepository,
        max_attempts: int = 3,
    ) -> None:
        self.session = session
        self.client = client
        self.events = events
        self.max_attempts = max_attempts

    async def sync_eligible_jobs(
        self,
        *,
        scrape_run_id: str | None,
        limit: int,
    ) -> BackendSyncWorkerResult:
        jobs = list(
            self.session.scalars(
                select(NormalizedJob)
                .options(
                    selectinload(NormalizedJob.skills_staging),
                    selectinload(NormalizedJob.requirements_staging),
                )
                .where(NormalizedJob.status.in_(SYNC_ELIGIBLE_STATUSES))
                .order_by(NormalizedJob.last_seen_at.desc(), NormalizedJob.id.asc())
                .limit(limit)
            ).all()
        )
        sent = 0
        failed = 0
        for job in jobs:
            event = self.events.prepare_event(job, scrape_run_id=scrape_run_id)
            try:
                result = await self.client.sync_normalized_jobs([job])
            except BackendSyncClientError as exc:
                self.events.record_failure(
                    event,
                    SyncFailure(
                        category="backend_rejected_payload",
                        message=str(exc),
                        response_summary={"statusCode": exc.status_code, "statusClass": "4xx"},
                    ),
                    max_attempts=1,
                )
                failed += 1
                continue
            except BackendSyncServerError as exc:
                status_class = f"{exc.status_code // 100}xx" if exc.status_code else "transport"
                self.events.record_failure(
                    event,
                    SyncFailure(
                        category="backend_retryable_failure",
                        message=str(exc),
                        response_summary={
                            "statusCode": exc.status_code,
                            "statusClass": status_class,
                        },
                    ),
                    max_attempts=self.max_attempts,
                )
                failed += 1
                continue

            self.events.record_success(event, SyncSuccess(result.response_summary))
            sent += 1

        self.session.flush()
        return BackendSyncWorkerResult(attempted=len(jobs), sent=sent, failed=failed)
