"""Error placeholders for scraper pipeline stages."""

from enum import StrEnum


class ErrorStage(StrEnum):
    FETCH = "fetch"
    PARSE = "parse"
    NORMALIZE = "normalize"
    PERSIST = "persist"
    SYNC = "sync"
