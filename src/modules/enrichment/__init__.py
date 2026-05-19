"""AI enrichment contracts."""

from modules.enrichment.prompts import build_enrichment_messages
from modules.enrichment.repositories import (
    AIRequestLogRepository,
    EnrichmentStagingRepository,
)
from modules.enrichment.schemas import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentJobInput,
    EnrichmentOutput,
    EnrichmentValidationError,
    RequirementType,
    validate_enrichment_output,
)
from modules.enrichment.service import EnrichmentService, EnrichmentServiceConfig

__all__ = [
    "EnrichedRequirement",
    "EnrichedSkill",
    "EnrichmentJobInput",
    "EnrichmentOutput",
    "EnrichmentService",
    "EnrichmentServiceConfig",
    "EnrichmentValidationError",
    "AIRequestLogRepository",
    "EnrichmentStagingRepository",
    "RequirementType",
    "build_enrichment_messages",
    "validate_enrichment_output",
]
