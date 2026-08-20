from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0  # current holder + queued waiters


class KeyedLockPool(Generic[K]):
    """Race-safe keyed asyncio locks that remove idle entries automatically.

    A plain ``dict[key, asyncio.Lock]`` grows forever when keys are user/channel
    IDs.  This pool counts holders + waiters and deletes a lock as soon as the
    last user leaves it, while an internal guard prevents cleanup/acquire races.
    """

    def __init__(self) -> None:
        self._entries: dict[K, _LockEntry] = {}
        self._guard = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def size(self) -> int:
        return len(self._entries)

    @asynccontextmanager
    async def hold(self, key: K) -> AsyncIterator[None]:
        async with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _LockEntry(asyncio.Lock())
                self._entries[key] = entry
            entry.users += 1

        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            async with self._guard:
                entry.users -= 1
                if entry.users <= 0 and not entry.lock.locked():
                    current = self._entries.get(key)
                    if current is entry:
                        self._entries.pop(key, None)

    @asynccontextmanager
    async def try_hold(self, key: K) -> AsyncIterator[bool]:
        """Acquire only when the key is currently idle; never queue behind it."""
        async with self._guard:
            entry = self._entries.get(key)
            if entry is not None and (entry.users > 0 or entry.lock.locked()):
                accepted = False
            else:
                if entry is None:
                    entry = _LockEntry(asyncio.Lock())
                    self._entries[key] = entry
                entry.users += 1
                accepted = True

        if not accepted:
            yield False
            return

        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield True
        finally:
            if acquired:
                entry.lock.release()
            async with self._guard:
                entry.users -= 1
                if entry.users <= 0 and not entry.lock.locked():
                    current = self._entries.get(key)
                    if current is entry:
                        self._entries.pop(key, None)

    async def clear_idle(self) -> int:
        """Remove entries that have no holder/waiter. Primarily diagnostic."""
        async with self._guard:
            keys = [key for key, entry in self._entries.items() if entry.users <= 0 and not entry.lock.locked()]
            for key in keys:
                self._entries.pop(key, None)
            return len(keys)
