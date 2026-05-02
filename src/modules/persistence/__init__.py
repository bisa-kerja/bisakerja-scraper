"""Persistence module."""

from modules.persistence.base import Base
from modules.persistence.models import NormalizedJob, RawJob, ScrapeRun, SyncEvent
from modules.persistence.repositories import (
    JobPersistenceRepository,
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
    "JobPersistenceRepository",
    "PersistenceResult",
    "RawJobInput",
    "stable_payload_hash",
]
