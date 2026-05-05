from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from integrations.backend import BackendSyncClient, BackendSyncClientError, BackendSyncServerError
from integrations.backend.payloads import BackendPayloadValidationError, build_backend_job_payload
from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import NormalizedJob, stable_payload_hash
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
    chunks_attempted: int = 0
    chunks_failed: int = 0


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
        batch_size: int | None = None,
    ) -> BackendSyncWorkerResult:
        jobs = self.events.list_resume_candidates(
            eligible_statuses=SYNC_ELIGIBLE_STATUSES,
            limit=limit,
            max_attempts=self.max_attempts,
        )
        chunk_size = batch_size or limit
        sent = 0
        failed = 0
        chunks_attempted = 0
        chunks_failed = 0
        for chunk_index, chunk_jobs in enumerate(chunks(jobs, chunk_size), start=1):
            chunks_attempted += 1
            chunk_sent, chunk_failed = await self._sync_chunk(
                chunk_jobs,
                scrape_run_id=scrape_run_id,
                chunk_id=f"{scrape_run_id or 'manual'}:{chunk_index}",
            )
            sent += chunk_sent
            failed += chunk_failed
            if chunk_failed:
                chunks_failed += 1
        self.session.flush()
        return BackendSyncWorkerResult(
            attempted=len(jobs),
            sent=sent,
            failed=failed,
            chunks_attempted=chunks_attempted,
            chunks_failed=chunks_failed,
        )

    async def _sync_chunk(
        self,
        jobs: list[NormalizedJob],
        *,
        scrape_run_id: str | None,
        chunk_id: str,
    ) -> tuple[int, int]:
        if not jobs:
            return 0, 0

        sent = 0
        failed = 0
        chunk_payload_hash = stable_payload_hash({"jobs": [job.normalized_payload for job in jobs]})
        events = []
        for job in jobs:
            event = self.events.prepare_event(job, scrape_run_id=scrape_run_id)
            self.events.attach_chunk_metadata(
                event,
                chunk_id=chunk_id,
                chunk_payload_hash=chunk_payload_hash,
                chunk_size=len(jobs),
            )
            events.append(event)

        valid_events = []
        payload_jobs: list[dict[str, object]] = []
        for event, job in zip(events, jobs, strict=True):
            try:
                payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
            except BackendPayloadValidationError as exc:
                self.events.record_failure(
                    event,
                    SyncFailure(
                        category="sync_contract_validation_error",
                        message=str(exc),
                        response_summary={"validationErrors": exc.details[:10]},
                    ),
                    max_attempts=1,
                )
                failed += 1
                continue
            valid_events.append(event)
            payload_jobs.append(payload)

        if not payload_jobs:
            return sent, failed

        try:
            result = await self.client.sync_jobs(payload_jobs)
        except BackendSyncClientError as exc:
            category = (
                "backend_endpoint_not_found"
                if exc.status_code == 404
                else "backend_rejected_payload"
            )
            failure_max_attempts = self.max_attempts if exc.status_code == 404 else 1
            for event in valid_events:
                self.events.record_failure(
                    event,
                    SyncFailure(
                        category=category,
                        message=str(exc),
                        response_summary=exc.response_summary
                        or {"statusCode": exc.status_code, "statusClass": "4xx"},
                    ),
                    max_attempts=failure_max_attempts,
                )
                failed += 1
            return sent, failed
        except BackendSyncServerError as exc:
            status_class = f"{exc.status_code // 100}xx" if exc.status_code else "transport"
            for event in valid_events:
                self.events.record_failure(
                    event,
                    SyncFailure(
                        category="backend_retryable_failure",
                        message=str(exc),
                        response_summary=exc.response_summary
                        or {
                            "statusCode": exc.status_code,
                            "statusClass": status_class,
                        },
                    ),
                    max_attempts=self.max_attempts,
                )
                failed += 1
            return sent, failed

        for event in valid_events:
            self.events.record_success(event, SyncSuccess(result.response_summary))
            sent += 1
        return sent, failed


def chunks(values: list[NormalizedJob], size: int) -> Iterable[list[NormalizedJob]]:
    if size <= 0:
        raise ValueError("chunk size must be greater than zero")
    for index in range(0, len(values), size):
        yield values[index : index + size]
