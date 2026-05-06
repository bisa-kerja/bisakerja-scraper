from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from modules.enrichment.repositories import (
    AIRequestLogInput,
    AIRequestLogRepository,
    AIRequestStatus,
    EnrichmentStagingRepository,
    response_summary_from_output,
)
from modules.enrichment.schemas import EnrichmentJobInput, EnrichmentOutput
from modules.persistence import NormalizedJob


class EnrichmentClient(Protocol):
    model: str
    max_retries: int

    async def enrich_job(self, job: EnrichmentJobInput) -> EnrichmentOutput:
        """Return structured enrichment output for one normalized job."""


@dataclass(frozen=True)
class EnrichmentServiceConfig:
    provider: str = "openai-compatible"
    model: str = "unknown"
    base_url: str | None = None
    batch_size: int = 10
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass
class EnrichmentJobResult:
    normalized_job_id: str
    status: str
    ai_request_log_id: str | None = None
    error_category: str | None = None
    error_message: str | None = None


@dataclass
class EnrichmentBatchResult:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[EnrichmentJobResult] = field(default_factory=list)


class EnrichmentService:
    def __init__(
        self,
        *,
        session: Session,
        client: EnrichmentClient,
        config: EnrichmentServiceConfig,
    ) -> None:
        self.session = session
        self.client = client
        self.config = config
        self.logs = AIRequestLogRepository(session)
        self.staging = EnrichmentStagingRepository(session)

    async def enrich_pending_batch(
        self,
        *,
        scrape_run_id: str | None = None,
    ) -> EnrichmentBatchResult:
        jobs = self.staging.list_unenriched_jobs(limit=self.config.batch_size)
        result = EnrichmentBatchResult()
        for job in jobs:
            item = await self.enrich_one(job, scrape_run_id=scrape_run_id)
            result.results.append(item)
            result.processed += 1
            if item.status == "success":
                result.succeeded += 1
            else:
                result.failed += 1
        self.session.flush()
        return result

    async def enrich_one(
        self,
        job: NormalizedJob,
        *,
        scrape_run_id: str | None = None,
    ) -> EnrichmentJobResult:
        try:
            request = enrichment_input_from_job(job)
        except Exception as exc:  # noqa: BLE001
            fallback_request = failed_request_input()
            log = self.logs.create(
                AIRequestLogInput(
                    normalized_job_id=job.id,
                    scrape_run_id=scrape_run_id,
                    provider=self.config.provider,
                    model=self.config.model or getattr(self.client, "model", "unknown"),
                    base_url=self.config.base_url,
                    latency_ms=0,
                    status=AIRequestStatus.FAILED,
                    retry_count=0,
                    request=fallback_request,
                    response_summary={"errorCategory": error_category(exc)},
                    error_category=error_category(exc),
                    error_message=str(exc),
                )
            )
            return EnrichmentJobResult(
                normalized_job_id=job.id,
                status="failed",
                ai_request_log_id=log.id,
                error_category=error_category(exc),
                error_message=str(exc),
            )

        started = time.perf_counter()
        retry_count = 0
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                output = await self.client.enrich_job(request)
                latency_ms = elapsed_ms(started)
                log = self.logs.create(
                    AIRequestLogInput(
                        normalized_job_id=job.id,
                        scrape_run_id=scrape_run_id,
                        provider=self.config.provider,
                        model=selected_model_for_log(
                            self.client,
                            fallback=self.config.model or getattr(self.client, "model", "unknown"),
                        ),
                        base_url=self.config.base_url,
                        latency_ms=latency_ms,
                        status=AIRequestStatus.SUCCESS,
                        retry_count=retry_count,
                        request=request,
                        response_summary=response_summary_from_output(output),
                    )
                )
                self.staging.upsert_output(job=job, output=output, ai_request_log_id=log.id)
                return EnrichmentJobResult(
                    normalized_job_id=job.id,
                    status="success",
                    ai_request_log_id=log.id,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not is_retryable(exc) or attempt >= self.config.max_attempts:
                    break
                retry_count += 1

        latency_ms = elapsed_ms(started)
        error = last_error or RuntimeError("unknown enrichment failure")
        log = self.logs.create(
            AIRequestLogInput(
                normalized_job_id=job.id,
                scrape_run_id=scrape_run_id,
                provider=self.config.provider,
                model=selected_model_for_log(
                    self.client,
                    fallback=self.config.model or getattr(self.client, "model", "unknown"),
                ),
                base_url=self.config.base_url,
                latency_ms=latency_ms,
                status=AIRequestStatus.FAILED,
                retry_count=retry_count,
                request=request,
                response_summary={"errorCategory": error_category(error)},
                error_category=error_category(error),
                error_message=str(error),
            )
        )
        return EnrichmentJobResult(
            normalized_job_id=job.id,
            status="failed",
            ai_request_log_id=log.id,
            error_category=error_category(error),
            error_message=str(error),
        )


def enrichment_input_from_job(job: NormalizedJob) -> EnrichmentJobInput:
    payload = job.normalized_payload or {}
    company = payload.get("company")
    if isinstance(company, dict):
        company_name = company.get("name") or job.company_name
    else:
        company_name = job.company_name
    source = payload.get("source")
    source_name = job.source_platform
    if isinstance(source, dict):
        source_name = source.get("platform") or source_name

    return EnrichmentJobInput(
        title=job.title,
        description=as_optional_text(payload.get("description")),
        requirements=as_optional_text(payload.get("requirements")),
        company=str(company_name),
        source=str(source_name),
    )


def as_optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def is_retryable(exc: Exception) -> bool:
    return bool(getattr(exc, "retryable", False))


def error_category(exc: Exception) -> str:
    return str(getattr(exc, "code", exc.__class__.__name__))


def failed_request_input() -> EnrichmentJobInput:
    return EnrichmentJobInput(
        title="unavailable title",
        description=None,
        requirements=None,
        company="unavailable company",
        source="unavailable source",
    )


def selected_model_for_log(client: EnrichmentClient, *, fallback: str) -> str:
    selected = getattr(client, "last_model", None)
    if isinstance(selected, str) and selected.strip():
        return selected
    return fallback
