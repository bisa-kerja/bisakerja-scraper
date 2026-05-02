"""Persistence module."""

from modules.persistence.base import Base
from modules.persistence.models import NormalizedJob, RawJob, ScrapeRun, SyncEvent
from modules.persistence.repositories import (
    JobListFilters,
    JobPersistenceRepository,
    NormalizedJobQueryRepository,
    PaginatedJobs,
    PersistenceResult,
    RawJobInput,
    stable_payload_hash,
)

__all__ = [
    "Base",
    "NormalizedJob",
    "RawJob",
    "ScrapeRun",
    "SyncEvent",
    "JobListFilters",
    "JobPersistenceRepository",
    "NormalizedJobQueryRepository",
    "PaginatedJobs",
    "PersistenceResult",
    "RawJobInput",
    "stable_payload_hash",
]
