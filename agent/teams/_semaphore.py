"""System-wide concurrency semaphore for department invocations."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 2


class DepartmentSemaphore:
    """Asyncio semaphore with department tracking for observability."""

    def __init__(self, limit: int = DEFAULT_LIMIT) -> None:
        self._limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active_count(self) -> int:
        return sum(self._active.values())

    def active_departments(self) -> set[str]:
        return {d for d, count in self._active.items() if count > 0}

    @asynccontextmanager
    async def acquire(self, department: str) -> AsyncIterator[None]:
        await self._semaphore.acquire()
        try:
            async with self._lock:
                self._active[department] = self._active.get(department, 0) + 1
            log.debug("semaphore.acquire department=%s active_count=%d", department, self.active_count)
            yield
        finally:
            async with self._lock:
                self._active[department] = max(0, self._active.get(department, 0) - 1)
                if self._active[department] == 0:
                    del self._active[department]
            self._semaphore.release()
            log.debug("semaphore.release department=%s active_count=%d", department, self.active_count)
