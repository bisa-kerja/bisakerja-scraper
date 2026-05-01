from enum import StrEnum
from typing import Any


class ErrorStage(StrEnum):
    FETCH = "fetch"
    PARSE = "parse"
    NORMALIZE = "normalize"
    PERSIST = "persist"
    SYNC = "sync"


class ScraperError(Exception):
    stage: ErrorStage
    code = "SCRAPER_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        source_platform: str | None = None,
        external_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.source_platform = source_platform
        self.external_id = external_id
        self.details = details or {}

    def to_log_fields(self) -> dict[str, Any]:
        return {
            "errorCategory": self.code,
            "stage": self.stage.value,
            "sourcePlatform": self.source_platform,
            "externalJobId": self.external_id,
            "retryable": self.retryable,
            "details": self.details,
        }


class FetchError(ScraperError):
    stage = ErrorStage.FETCH
    code = "FETCH_ERROR"
    retryable = True


class ParseError(ScraperError):
    stage = ErrorStage.PARSE
    code = "PARSE_ERROR"


class NormalizeError(ScraperError):
    stage = ErrorStage.NORMALIZE
    code = "NORMALIZE_ERROR"


class PersistError(ScraperError):
    stage = ErrorStage.PERSIST
    code = "PERSIST_ERROR"
    retryable = True


class SyncError(ScraperError):
    stage = ErrorStage.SYNC
    code = "SYNC_ERROR"
    retryable = True
