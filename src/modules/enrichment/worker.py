from __future__ import annotations

from dataclasses import dataclass

from modules.enrichment.service import EnrichmentBatchResult, EnrichmentService
from modules.queue import QueueFailure, StageJobRepository


@dataclass(frozen=True)
class EnrichmentWorker:
    service: EnrichmentService

    async def run_batch(self, *, scrape_run_id: str | None = None) -> EnrichmentBatchResult:
        return await self.service.enrich_pending_batch(scrape_run_id=scrape_run_id)


async def run_enrichment_stage_job(
    *,
    queue: StageJobRepository,
    worker: EnrichmentWorker,
    job_id: str,
) -> EnrichmentBatchResult:
    job = queue.session.get(queue_model(), job_id)
    if job is None:
        raise ValueError("stage job not found")
    try:
        result = await worker.run_batch(scrape_run_id=job.scrape_run_id)
    except Exception as exc:
        queue.fail(job, QueueFailure(category=exc.__class__.__name__, message=str(exc)))
        raise
    queue.complete(job)
    return result


def queue_model():
    from modules.persistence import StageJob

    return StageJob
