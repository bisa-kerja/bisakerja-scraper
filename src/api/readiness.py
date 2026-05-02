from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class ReadinessError(Exception):
    def __init__(self, dependency: str, message: str = "dependency unavailable") -> None:
        super().__init__(message)
        self.dependency = dependency
        self.message = message


@dataclass(frozen=True)
class DatabaseReadinessChecker:
    database_url: str
    timeout_seconds: float

    async def __call__(self) -> None:
        engine = create_async_engine(self.database_url, pool_pre_ping=True)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise ReadinessError("scraper-db") from exc
        finally:
            await engine.dispose()
