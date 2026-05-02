"""Persistence module."""

from modules.persistence.base import Base
from modules.persistence.models import (
    AIRequestLog,
    JobRequirementStaging,
    JobSkillStaging,
    NormalizationQuarantine,
    NormalizedJob,
    NotificationHandoffEvent,
    RawJob,
    ScrapeRun,
    StageJob,
    SyncEvent,
)
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
    "AIRequestLog",
    "JobRequirementStaging",
    "JobSkillStaging",
    "NormalizationQuarantine",
    "NormalizedJob",
    "NotificationHandoffEvent",
    "RawJob",
    "ScrapeRun",
    "StageJob",
    "SyncEvent",
    "JobListFilters",
    "JobPersistenceRepository",
    "NormalizedJobQueryRepository",
    "PaginatedJobs",
    "PersistenceResult",
    "RawJobInput",
    "stable_payload_hash",
]
