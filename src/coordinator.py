import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Tuple


class FolioBusy(Exception):
    """Raised when an SII operation cannot enter the configured queue in time."""


@dataclass
class _CompanyEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class FolioCoordinator:
    """Limits global SII traffic and serializes work for each company."""

    def __init__(self, max_concurrent: int = 4, queue_timeout: float = 30.0):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if queue_timeout < 0:
            raise ValueError("queue_timeout cannot be negative")

        self._capacity = asyncio.Semaphore(max_concurrent)
        self._queue_timeout = queue_timeout
        self._registry: Dict[Tuple[str, str], _CompanyEntry] = {}
        self._registry_lock = asyncio.Lock()

    @property
    def lock_count(self) -> int:
        return len(self._registry)

    async def _retain(self, key: Tuple[str, str]) -> _CompanyEntry:
        async with self._registry_lock:
            entry = self._registry.get(key)
            if entry is None:
                entry = _CompanyEntry()
                self._registry[key] = entry
            entry.users += 1
            return entry

    async def _release_reference(
        self, key: Tuple[str, str], entry: _CompanyEntry
    ) -> None:
        async with self._registry_lock:
            entry.users -= 1
            if entry.users == 0 and self._registry.get(key) is entry:
                self._registry.pop(key, None)

    async def _acquire(self, entry: _CompanyEntry) -> None:
        await entry.lock.acquire()
        try:
            await self._capacity.acquire()
        except BaseException:
            entry.lock.release()
            raise

    @asynccontextmanager
    async def slot(self, environment: str, company: str) -> AsyncIterator[None]:
        key = (environment.strip().lower(), company.strip().upper())
        entry = await self._retain(key)
        acquired = False

        try:
            try:
                await asyncio.wait_for(
                    self._acquire(entry), timeout=self._queue_timeout
                )
            except asyncio.TimeoutError as exc:
                raise FolioBusy(
                    "SII request capacity is currently exhausted."
                ) from exc

            acquired = True
            yield
        finally:
            if acquired:
                self._capacity.release()
                entry.lock.release()
            await self._release_reference(key, entry)
