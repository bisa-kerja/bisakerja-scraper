from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from modules.persistence.base import Base


def new_id() -> str:
    return str(uuid4())


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_records_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    normalized_records_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_category: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    raw_jobs: Mapped[list[RawJob]] = relationship(back_populates="scrape_run")
    sync_events: Mapped[list[SyncEvent]] = relationship(back_populates="scrape_run")
    notification_handoff_events: Mapped[list[NotificationHandoffEvent]] = relationship(
        back_populates="scrape_run"
    )
    ai_request_logs: Mapped[list[AIRequestLog]] = relationship(back_populates="scrape_run")
    stage_jobs: Mapped[list[StageJob]] = relationship(back_populates="scrape_run")
    quarantine_records: Mapped[list[NormalizationQuarantine]] = relationship(
        back_populates="scrape_run"
    )

    __table_args__ = (
        Index(
            "scrape_runs_source_status_started_at_idx", "source_platform", "status", "started_at"
        ),
    )


class RawJob(Base):
    __tablename__ = "raw_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scrape_run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(128))
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="raw_jobs")
    normalized_jobs: Mapped[list[NormalizedJob]] = relationship(back_populates="raw_job")
    quarantine_records: Mapped[list[NormalizationQuarantine]] = relationship(
        back_populates="raw_job"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_platform", "external_id", name="raw_jobs_source_external_id_unique"
        ),
        Index("raw_jobs_scrape_run_id_idx", "scrape_run_id"),
    )


class NormalizedJob(Base):
    __tablename__ = "normalized_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    raw_job_id: Mapped[str | None] = mapped_column(ForeignKey("raw_jobs.id"))
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    raw_job: Mapped[RawJob | None] = relationship(back_populates="normalized_jobs")
    sync_events: Mapped[list[SyncEvent]] = relationship(back_populates="normalized_job")
    notification_handoff_events: Mapped[list[NotificationHandoffEvent]] = relationship(
        back_populates="normalized_job"
    )
    ai_request_logs: Mapped[list[AIRequestLog]] = relationship(back_populates="normalized_job")
    skills_staging: Mapped[list[JobSkillStaging]] = relationship(back_populates="normalized_job")
    requirements_staging: Mapped[list[JobRequirementStaging]] = relationship(
        back_populates="normalized_job"
    )
    stage_jobs: Mapped[list[StageJob]] = relationship(back_populates="normalized_job")

    __table_args__ = (
        UniqueConstraint(
            "source_platform",
            "external_id",
            name="normalized_jobs_source_external_id_unique",
        ),
        Index("normalized_jobs_status_last_seen_at_idx", "status", "last_seen_at"),
        Index("normalized_jobs_source_platform_idx", "source_platform"),
    )


class SyncEvent(Base):
    __tablename__ = "sync_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scrape_run_id: Mapped[str | None] = mapped_column(ForeignKey("scrape_runs.id"))
    normalized_job_id: Mapped[str | None] = mapped_column(ForeignKey("normalized_jobs.id"))
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(64), nullable=False, default="backend")
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="sync_events")
    normalized_job: Mapped[NormalizedJob | None] = relationship(back_populates="sync_events")

    __table_args__ = (
        Index("sync_events_status_attempted_at_idx", "status", "attempted_at"),
        Index("sync_events_source_external_id_idx", "source_platform", "external_id"),
        UniqueConstraint(
            "target",
            "normalized_job_id",
            "payload_hash",
            name="sync_events_target_job_payload_unique",
        ),
    )


class NotificationHandoffEvent(Base):
    __tablename__ = "notification_handoff_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scrape_run_id: Mapped[str] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    normalized_job_id: Mapped[str] = mapped_column(ForeignKey("normalized_jobs.id"), nullable=False)
    sync_event_id: Mapped[str] = mapped_column(ForeignKey("sync_events.id"), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str] = mapped_column(String(64), nullable=False, default="backend-notifications")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="notification_handoff_events")
    normalized_job: Mapped[NormalizedJob] = relationship(
        back_populates="notification_handoff_events"
    )

    __table_args__ = (
        UniqueConstraint(
            "scrape_run_id",
            "source_platform",
            "external_id",
            "target",
            name="notification_handoff_run_source_external_target_unique",
        ),
        Index("notification_handoff_status_attempted_at_idx", "status", "attempted_at"),
        Index("notification_handoff_sync_event_id_idx", "sync_event_id"),
    )


class AIRequestLog(Base):
    __tablename__ = "ai_request_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scrape_run_id: Mapped[str | None] = mapped_column(ForeignKey("scrape_runs.id"))
    normalized_job_id: Mapped[str | None] = mapped_column(ForeignKey("normalized_jobs.id"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url_alias: Mapped[str | None] = mapped_column(String(255))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_category: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="ai_request_logs")
    normalized_job: Mapped[NormalizedJob | None] = relationship(back_populates="ai_request_logs")
    skills_staging: Mapped[list[JobSkillStaging]] = relationship(back_populates="ai_request_log")
    requirements_staging: Mapped[list[JobRequirementStaging]] = relationship(
        back_populates="ai_request_log"
    )

    __table_args__ = (
        Index("ai_request_logs_job_created_at_idx", "normalized_job_id", "created_at"),
        Index("ai_request_logs_status_created_at_idx", "status", "created_at"),
    )


class JobSkillStaging(Base):
    __tablename__ = "job_skills_staging"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    normalized_job_id: Mapped[str] = mapped_column(ForeignKey("normalized_jobs.id"), nullable=False)
    ai_request_log_id: Mapped[str | None] = mapped_column(ForeignKey("ai_request_logs.id"))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    normalized_job: Mapped[NormalizedJob] = relationship(back_populates="skills_staging")
    ai_request_log: Mapped[AIRequestLog | None] = relationship(back_populates="skills_staging")

    __table_args__ = (
        UniqueConstraint(
            "normalized_job_id",
            "normalized_value",
            name="job_skills_staging_job_value_unique",
        ),
        Index("job_skills_staging_job_idx", "normalized_job_id"),
    )


class JobRequirementStaging(Base):
    __tablename__ = "job_requirements_staging"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    normalized_job_id: Mapped[str] = mapped_column(ForeignKey("normalized_jobs.id"), nullable=False)
    ai_request_log_id: Mapped[str | None] = mapped_column(ForeignKey("ai_request_logs.id"))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    normalized_job: Mapped[NormalizedJob] = relationship(back_populates="requirements_staging")
    ai_request_log: Mapped[AIRequestLog | None] = relationship(
        back_populates="requirements_staging"
    )

    __table_args__ = (
        UniqueConstraint(
            "normalized_job_id",
            "requirement_type",
            "normalized_value",
            name="job_requirements_staging_job_type_value_unique",
        ),
        Index("job_requirements_staging_job_idx", "normalized_job_id"),
    )


class StageJob(Base):
    __tablename__ = "stage_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scrape_run_id: Mapped[str | None] = mapped_column(ForeignKey("scrape_runs.id"))
    normalized_job_id: Mapped[str | None] = mapped_column(ForeignKey("normalized_jobs.id"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="stage_jobs")
    normalized_job: Mapped[NormalizedJob | None] = relationship(back_populates="stage_jobs")

    __table_args__ = (
        Index("stage_jobs_status_available_at_idx", "status", "available_at"),
        Index("stage_jobs_correlation_id_idx", "correlation_id"),
        Index("stage_jobs_scrape_run_id_idx", "scrape_run_id"),
    )


class NormalizationQuarantine(Base):
    __tablename__ = "normalization_quarantine"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scrape_run_id: Mapped[str | None] = mapped_column(ForeignKey("scrape_runs.id"))
    raw_job_id: Mapped[str | None] = mapped_column(ForeignKey("raw_jobs.id"))
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    payload_hash: Mapped[str | None] = mapped_column(String(128))
    error_category: Mapped[str] = mapped_column(String(128), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    source_field_path: Mapped[str | None] = mapped_column(String(255))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="quarantine_records")
    raw_job: Mapped[RawJob | None] = relationship(back_populates="quarantine_records")

    __table_args__ = (
        Index("normalization_quarantine_status_source_idx", "status", "source_platform"),
        Index("normalization_quarantine_raw_job_id_idx", "raw_job_id"),
    )
