"""Normalized jobs module."""

from modules.jobs.dates import NormalizedPostedDate, normalize_posted_date, parse_absolute_datetime
from modules.jobs.salary import NormalizedSalary, normalize_salary
from modules.jobs.schemas import (
    CanonicalJobSchema,
    CanonicalJobStatus,
    CompanySchema,
    EmploymentType,
    LocationSchema,
    PresentationMetadataSchema,
    SalaryPeriod,
    SalarySchema,
    SourceMetadataSchema,
    SourcePlatform,
    WorkType,
)

__all__ = [
    "CanonicalJobSchema",
    "CanonicalJobStatus",
    "CompanySchema",
    "EmploymentType",
    "LocationSchema",
    "PresentationMetadataSchema",
    "SalaryPeriod",
    "SalarySchema",
    "SourceMetadataSchema",
    "SourcePlatform",
    "WorkType",
    "NormalizedSalary",
    "normalize_salary",
    "NormalizedPostedDate",
    "normalize_posted_date",
    "parse_absolute_datetime",
]
