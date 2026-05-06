from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import not_, or_, select
from sqlalchemy.orm import Session

from modules.enrichment.schemas import EnrichmentJobInput, EnrichmentOutput, RequirementType
from modules.persistence import (
    AIRequestLog,
    JobRequirementStaging,
    JobSkillStaging,
    NormalizedJob,
    stable_payload_hash,
)


class AIRequestStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class EnrichmentSource(StrEnum):
    AI = "ai"
    SOURCE = "source"


SECRET_KEY_PATTERN = re.compile(
    r"(authorization|bearer|cookie|csrf|token|secret|credential|password|session|"
    r"visitor|device|raw_payload|raw payload|database_url|db_url|prompt)",
    re.IGNORECASE,
)
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class AIRequestLogInput:
    normalized_job_id: str
    scrape_run_id: str | None
    provider: str
    model: str
    base_url: str | None
    latency_ms: int | None
    status: AIRequestStatus
    retry_count: int
    request: EnrichmentJobInput
    response_summary: dict[str, Any] | None = None
    error_category: str | None = None
    error_message: str | None = None


class AIRequestLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, item: AIRequestLogInput) -> AIRequestLog:
        log = AIRequestLog(
            scrape_run_id=item.scrape_run_id,
            normalized_job_id=item.normalized_job_id,
            provider=item.provider,
            model=item.model,
            base_url_alias=safe_base_url_alias(item.base_url),
            latency_ms=item.latency_ms,
            status=item.status.value,
            retry_count=item.retry_count,
            request_hash=stable_payload_hash(item.request.model_dump(mode="json")),
            response_summary=sanitize_summary(item.response_summary),
            error_category=item.error_category,
            error_message=safe_message(item.error_message),
        )
        self.session.add(log)
        self.session.flush()
        return log


class EnrichmentStagingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_unenriched_jobs(self, *, limit: int) -> list[NormalizedJob]:
        successful_enrichment_exists = (
            select(AIRequestLog.id)
            .where(
                AIRequestLog.normalized_job_id == NormalizedJob.id,
                AIRequestLog.status == AIRequestStatus.SUCCESS.value,
            )
            .exists()
        )
        statement = (
            select(NormalizedJob)
            .outerjoin(JobSkillStaging, JobSkillStaging.normalized_job_id == NormalizedJob.id)
            .outerjoin(
                JobRequirementStaging,
                JobRequirementStaging.normalized_job_id == NormalizedJob.id,
            )
            .where(
                not_(successful_enrichment_exists),
                or_(JobSkillStaging.id.is_(None), JobRequirementStaging.id.is_(None)),
            )
            .distinct()
            .order_by(NormalizedJob.last_seen_at.desc(), NormalizedJob.id.asc())
            .limit(limit)
        )
        return list(self.session.scalars(statement).all())

    def upsert_output(
        self,
        *,
        job: NormalizedJob,
        output: EnrichmentOutput,
        ai_request_log_id: str | None,
        source: EnrichmentSource = EnrichmentSource.AI,
    ) -> tuple[list[JobSkillStaging], list[JobRequirementStaging]]:
        skills = [
            self.upsert_skill(
                job,
                value=skill.name,
                confidence=skill.confidence,
                ai_request_log_id=ai_request_log_id,
                source=source,
            )
            for skill in output.skills
        ]
        requirements = [
            self.upsert_requirement(
                job,
                requirement_type=requirement.type,
                value=requirement.value,
                confidence=requirement.confidence,
                ai_request_log_id=ai_request_log_id,
                source=source,
            )
            for requirement in output.requirements
        ]
        self.session.flush()
        return skills, requirements

    def upsert_skill(
        self,
        job: NormalizedJob,
        *,
        value: str,
        confidence: float | None,
        ai_request_log_id: str | None,
        source: EnrichmentSource,
    ) -> JobSkillStaging:
        normalized_value = normalize_value(value)
        existing = self.session.scalar(
            select(JobSkillStaging).where(
                JobSkillStaging.normalized_job_id == job.id,
                JobSkillStaging.normalized_value == normalized_value,
            )
        )
        if existing is not None:
            existing.ai_request_log_id = ai_request_log_id
            existing.source = source.value
            existing.confidence = confidence
            self.session.flush()
            return existing

        row = JobSkillStaging(
            normalized_job_id=job.id,
            ai_request_log_id=ai_request_log_id,
            source=source.value,
            normalized_value=normalized_value,
            confidence=confidence,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def upsert_requirement(
        self,
        job: NormalizedJob,
        *,
        requirement_type: RequirementType,
        value: str,
        confidence: float | None,
        ai_request_log_id: str | None,
        source: EnrichmentSource,
    ) -> JobRequirementStaging:
        normalized_value = normalize_value(value)
        existing = self.session.scalar(
            select(JobRequirementStaging).where(
                JobRequirementStaging.normalized_job_id == job.id,
                JobRequirementStaging.requirement_type == requirement_type.value,
                JobRequirementStaging.normalized_value == normalized_value,
            )
        )
        if existing is not None:
            existing.ai_request_log_id = ai_request_log_id
            existing.source = source.value
            existing.confidence = confidence
            self.session.flush()
            return existing

        row = JobRequirementStaging(
            normalized_job_id=job.id,
            ai_request_log_id=ai_request_log_id,
            source=source.value,
            requirement_type=requirement_type.value,
            normalized_value=normalized_value,
            confidence=confidence,
        )
        self.session.add(row)
        self.session.flush()
        return row


def response_summary_from_output(output: EnrichmentOutput) -> dict[str, Any]:
    return {
        "skillsCount": len(output.skills),
        "requirementsCount": len(output.requirements),
        "confidence": output.confidence,
        "warningsCount": len(output.warnings),
    }


def safe_base_url_alias(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    parsed = urlparse(base_url)
    if not parsed.hostname:
        return None
    return parsed.hostname


def sanitize_summary(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        key: "[REDACTED]" if SECRET_KEY_PATTERN.search(key) else safe_summary_value(item)
        for key, item in value.items()
    }


def safe_summary_value(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_summary(value)
    if isinstance(value, list):
        return [safe_summary_value(item) for item in value[:20]]
    if isinstance(value, str):
        return safe_message(value)
    return value


def safe_message(value: str | None) -> str | None:
    if value is None:
        return None
    if SECRET_KEY_PATTERN.search(value):
        return "[REDACTED]"
    return value[:500]


def normalize_value(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value.strip())
