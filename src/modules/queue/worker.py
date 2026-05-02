from __future__ import annotations

from collections.abc import Awaitable, Callable

from modules.persistence import StageJob
from modules.queue.jobs import QueueFailure, StageJobRepository, StageJobType

StageJobHandler = Callable[[StageJob], Awaitable[None]]


async def process_next_stage_job(
    *,
    repository: StageJobRepository,
    job_type: StageJobType,
    handlers: dict[StageJobType, StageJobHandler],
) -> StageJob | None:
    job = repository.claim_next(job_type=job_type)
    if job is None:
        return None
    handler = handlers[job_type]
    try:
        await handler(job)
    except Exception as exc:
        repository.fail(job, QueueFailure(category=exc.__class__.__name__, message=str(exc)))
        return job
    repository.complete(job)
    return job
