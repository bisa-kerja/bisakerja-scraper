from __future__ import annotations

from collections.abc import Callable, Iterator
from math import ceil
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.responses import success_response
from config.settings import Settings
from modules.jobs.schemas import SourcePlatform
from modules.persistence import JobListFilters, NormalizedJob, NormalizedJobQueryRepository

JobSessionFactory = Callable[[], Iterator[Session]]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    source_platform: str = Field(serialization_alias="sourcePlatform")
    external_job_id: str = Field(serialization_alias="externalJobId")
    title: str
    company_name: str = Field(serialization_alias="companyName")
    source_url: str = Field(serialization_alias="sourceUrl")
    apply_url: str | None = Field(serialization_alias="applyUrl")
    status: str
    last_seen_at: str = Field(serialization_alias="lastSeenAt")
    posted_at: str | None = Field(serialization_alias="postedAt")
    payload: dict[str, Any]


def create_jobs_router() -> APIRouter:
    router = APIRouter(prefix="/jobs", tags=["jobs"])

    @router.get("", dependencies=[Depends(require_internal_service_token)])
    def list_jobs(
        session: Annotated[Session, Depends(get_job_session)],
        source_platform: Annotated[SourcePlatform | None, Query(alias="sourcePlatform")] = None,
        freshness: Annotated[
            str | None, Query(pattern="^(active|inactive|expired|unknown)$")
        ] = None,
        location: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        keyword: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> object:
        filters = JobListFilters(
            source_platform=source_platform.value if source_platform else None,
            freshness=freshness,
            location=location,
            keyword=keyword,
        )
        result = NormalizedJobQueryRepository(session).list_jobs(
            filters=filters,
            page=page,
            limit=limit,
        )
        return success_response(
            message="Jobs retrieved",
            data=[serialize_job(job) for job in result.jobs],
            meta={
                "pagination": pagination_meta(page=page, limit=limit, total=result.total),
                "filters": {
                    "sourcePlatform": filters.source_platform,
                    "freshness": filters.freshness,
                    "location": filters.location,
                    "keyword": filters.keyword,
                },
                "sort": "last_seen_desc",
            },
        )

    @router.get("/{job_id}", dependencies=[Depends(require_internal_service_token)])
    def get_job(
        job_id: str,
        session: Annotated[Session, Depends(get_job_session)],
    ) -> object:
        job = NormalizedJobQueryRepository(session).get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return success_response(message="Job retrieved", data=serialize_job(job))

    return router


def get_job_session(request: Request) -> Iterator[Session]:
    factory = getattr(request.app.state, "job_session_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="Job store is unavailable")
    yield from factory()


def require_internal_service_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings: Settings = request.app.state.settings
    expected = settings.scraper_internal_service_token.get_secret_value()
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid internal credential")


def serialize_job(job: NormalizedJob) -> dict[str, Any]:
    return JobResponse(
        id=job.id,
        source_platform=job.source_platform,
        external_job_id=job.external_id,
        title=job.title,
        company_name=job.company_name,
        source_url=job.source_url,
        apply_url=job.apply_url,
        status=job.status,
        last_seen_at=job.last_seen_at.isoformat(),
        posted_at=job.posted_at.isoformat() if job.posted_at else None,
        payload=job.normalized_payload,
    ).model_dump(mode="json", by_alias=True)


def pagination_meta(*, page: int, limit: int, total: int) -> dict[str, Any]:
    total_pages = ceil(total / limit) if total else 0
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "hasNextPage": page < total_pages,
        "hasPrevPage": page > 1 and total_pages > 0,
    }
