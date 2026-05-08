from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from math import ceil

from sqlalchemy.orm import Session

from integrations.backend import BackendSyncClient, BackendSyncClientError, BackendSyncServerError
from integrations.backend.payloads import BackendPayloadValidationError, build_backend_job_payload
from modules.jobs.schemas import CanonicalJobStatus
from modules.persistence import NormalizedJob, stable_payload_hash
from modules.sync.events import SyncEventRepository, SyncFailure, SyncSuccess, is_retryable_event

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
    adaptive_batch_reductions: int = 0
    chunk_latency_ms_p50: int | None = None
    chunk_latency_ms_p95: int | None = None
    status_class_counts: dict[str, int] = field(default_factory=dict)
    zero_sent_reason: str | None = None


@dataclass(frozen=True)
class ChunkSyncResult:
    sent: int
    failed: int
    status_class: str
    retryable_failure: bool = False
    latency_ms: int | None = None


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
        source_platforms: Iterable[str] | None = None,
        min_batch_size: int = 1,
        adaptive_batching: bool = True,
    ) -> BackendSyncWorkerResult:
        jobs = self._list_backend_payload_candidates(
            scrape_run_id=scrape_run_id,
            limit=limit,
            source_platforms=set(source_platforms) if source_platforms is not None else None,
        )
        if min_batch_size <= 0:
            raise ValueError("min batch size must be greater than zero")
        chunk_size = min(max(batch_size or limit, 1), 100)
        sent = 0
        failed = 0
        chunks_attempted = 0
        chunks_failed = 0
        adaptive_batch_reductions = 0
        chunk_latencies: list[int] = []
        status_class_counts: dict[str, int] = {}
        cursor = 0
        chunk_index = 0
        while cursor < len(jobs):
            current_chunk_size = min(chunk_size, len(jobs) - cursor)
            chunk_jobs = jobs[cursor : cursor + current_chunk_size]
            while True:
                chunk_index += 1
                chunk_id = f"{scrape_run_id or 'manual'}:{chunk_index}"
                started = time.perf_counter()
                chunk_result = await self._sync_chunk(
                    chunk_jobs,
                    scrape_run_id=scrape_run_id,
                    chunk_id=chunk_id,
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                chunk_result = ChunkSyncResult(
                    sent=chunk_result.sent,
                    failed=chunk_result.failed,
                    status_class=chunk_result.status_class,
                    retryable_failure=chunk_result.retryable_failure,
                    latency_ms=latency_ms,
                )
                chunk_latencies.append(latency_ms)
                status_class_counts[chunk_result.status_class] = (
                    status_class_counts.get(chunk_result.status_class, 0) + 1
                )
                chunks_attempted += 1
                should_retry_with_smaller_batch = (
                    adaptive_batching
                    and chunk_result.retryable_failure
                    and chunk_result.sent == 0
                    and len(chunk_jobs) > min_batch_size
                )
                if should_retry_with_smaller_batch:
                    chunks_failed += 1
                else:
                    sent += chunk_result.sent
                    failed += chunk_result.failed
                    if chunk_result.failed:
                        chunks_failed += 1
                if should_retry_with_smaller_batch:
                    next_size = max(min_batch_size, ceil(len(chunk_jobs) / 2))
                    if next_size == len(chunk_jobs):
                        break
                    adaptive_batch_reductions += 1
                    chunk_size = max(next_size, min_batch_size)
                    chunk_jobs = chunk_jobs[:chunk_size]
                    continue
                break
            cursor += len(chunk_jobs)
        self.session.flush()
        zero_sent_reason = self._infer_zero_sent_reason(
            attempted=len(jobs),
            sent=sent,
            failed=failed,
        )
        return BackendSyncWorkerResult(
            attempted=len(jobs),
            sent=sent,
            failed=failed,
            chunks_attempted=chunks_attempted,
            chunks_failed=chunks_failed,
            adaptive_batch_reductions=adaptive_batch_reductions,
            chunk_latency_ms_p50=percentile_nearest_rank(chunk_latencies, 50),
            chunk_latency_ms_p95=percentile_nearest_rank(chunk_latencies, 95),
            status_class_counts=status_class_counts,
            zero_sent_reason=zero_sent_reason,
        )

    def _list_backend_payload_candidates(
        self,
        *,
        scrape_run_id: str | None,
        limit: int,
        source_platforms: set[str] | None,
    ) -> list[NormalizedJob]:
        candidates: list[NormalizedJob] = []
        for job in self.events.list_eligible_jobs(
            eligible_statuses=SYNC_ELIGIBLE_STATUSES,
            source_platforms=source_platforms,
            scrape_run_id=scrape_run_id,
        ):
            try:
                payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
            except BackendPayloadValidationError:
                candidates.append(job)
            else:
                event = self.events.find_event(
                    job,
                    payload_hash=stable_payload_hash(payload),
                )
                if event is None or is_retryable_event(event, max_attempts=self.max_attempts):
                    candidates.append(job)
            if len(candidates) >= limit:
                break
        return candidates

    async def _sync_chunk(
        self,
        jobs: list[NormalizedJob],
        *,
        scrape_run_id: str | None,
        chunk_id: str,
    ) -> ChunkSyncResult:
        if not jobs:
            return ChunkSyncResult(sent=0, failed=0, status_class="empty")

        sent = 0
        failed = 0
        valid_events = []
        payload_jobs: list[dict[str, object]] = []
        for job in jobs:
            try:
                payload = build_backend_job_payload(job).model_dump(mode="json", by_alias=True)
            except BackendPayloadValidationError as exc:
                event = self.events.prepare_event(job, scrape_run_id=scrape_run_id)
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
            event = self.events.prepare_event(
                job,
                scrape_run_id=scrape_run_id,
                payload_hash=stable_payload_hash(payload),
            )
            valid_events.append(event)
            payload_jobs.append(payload)

        if not payload_jobs:
            return ChunkSyncResult(
                sent=sent,
                failed=failed,
                status_class="contract",
            )

        chunk_payload_hash = stable_payload_hash({"jobs": payload_jobs})
        for event in valid_events:
            self.events.attach_chunk_metadata(
                event,
                chunk_id=chunk_id,
                chunk_payload_hash=chunk_payload_hash,
                chunk_size=len(payload_jobs),
            )

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
            return ChunkSyncResult(
                sent=sent,
                failed=failed,
                status_class="4xx",
                retryable_failure=exc.status_code == 404,
            )
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
            return ChunkSyncResult(
                sent=sent,
                failed=failed,
                status_class=status_class,
                retryable_failure=True,
            )

        for event in valid_events:
            self.events.record_success(event, SyncSuccess(result.response_summary))
            sent += 1
        return ChunkSyncResult(
            sent=sent,
            failed=failed,
            status_class=f"{result.status_code // 100}xx",
        )

    def _infer_zero_sent_reason(self, *, attempted: int, sent: int, failed: int) -> str | None:
        if sent > 0:
            return None
        if attempted == 0:
            return "no eligible jobs for sync"
        if failed >= attempted:
            return "all candidate jobs failed sync attempts"
        return "no sync candidates were sent"


def chunks(values: list[NormalizedJob], size: int) -> Iterable[list[NormalizedJob]]:
    if size <= 0:
        raise ValueError("chunk size must be greater than zero")
    for index in range(0, len(values), size):
        yield values[index : index + size]


def percentile_nearest_rank(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = ceil((percentile / 100) * len(ordered))
    rank = min(max(rank, 1), len(ordered))
    return ordered[rank - 1]
