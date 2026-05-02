from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
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
