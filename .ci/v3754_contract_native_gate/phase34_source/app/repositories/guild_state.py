from __future__ import annotations

"""Narrow persistence boundary for per-guild key/value runtime configuration."""

import time
from collections import OrderedDict

from app import db_backend as aiosqlite


# Shared process-local cache because several services own separate
# GuildStateRepository instances but all read/write the same canonical table.
# A short TTL keeps external/manual DB edits eventually visible, while set()
# writes update the cache immediately for every repository instance.
_CACHE_TTL_SECONDS = 5.0
_CACHE_MAX_ENTRIES = 8192
_CACHE: OrderedDict[tuple[str, int, str], tuple[float, str | None]] = OrderedDict()
_CACHE_STATS: dict[str, int] = {"hits": 0, "misses": 0, "writes": 0, "evictions": 0}


def _cache_key(path: str, guild_id: int, key: str) -> tuple[str, int, str]:
    return (str(path), int(guild_id), str(key))


def _cache_get(path: str, guild_id: int, key: str) -> tuple[bool, str | None]:
    cache_key = _cache_key(path, guild_id, key)
    item = _CACHE.get(cache_key)
    if item is None:
        _CACHE_STATS["misses"] += 1
        return False, None
    expires_at, value = item
    if expires_at <= time.monotonic():
        _CACHE.pop(cache_key, None)
        _CACHE_STATS["misses"] += 1
        return False, None
    _CACHE.move_to_end(cache_key)
    _CACHE_STATS["hits"] += 1
    return True, value


def _cache_set(path: str, guild_id: int, key: str, value: str | None) -> None:
    cache_key = _cache_key(path, guild_id, key)
    _CACHE[cache_key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)
    _CACHE_STATS["writes"] += 1
    _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)
        _CACHE_STATS["evictions"] += 1


def guild_state_cache_metrics() -> dict[str, int | float]:
    hits = int(_CACHE_STATS["hits"])
    misses = int(_CACHE_STATS["misses"])
    lookups = hits + misses
    return {
        "entries": len(_CACHE),
        "max_entries": _CACHE_MAX_ENTRIES,
        "ttl_seconds": _CACHE_TTL_SECONDS,
        "hits": hits,
        "misses": misses,
        "writes": int(_CACHE_STATS["writes"]),
        "evictions": int(_CACHE_STATS["evictions"]),
        "hit_rate": (hits / lookups) if lookups else 0.0,
    }




def invalidate_guild_state_cache(path: str, guild_id: int, key: str | None = None) -> None:
    if key is not None:
        _CACHE.pop(_cache_key(path, guild_id, key), None)
        return
    prefix_path = str(path)
    gid = int(guild_id)
    stale = [cache_key for cache_key in _CACHE if cache_key[0] == prefix_path and cache_key[1] == gid]
    for cache_key in stale:
        _CACHE.pop(cache_key, None)

def clear_guild_state_cache() -> None:
    """Test/diagnostic helper; normal runtime invalidation happens on set()."""
    _CACHE.clear()
    for key in _CACHE_STATS:
        _CACHE_STATS[key] = 0


class GuildStateRepository:
    """Canonical storage access for the shared ``guild_state`` table."""

    def __init__(self, path: str) -> None:
        self.path = path

    async def set(self, guild_id: int, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO guild_state (guild_id,`key`,`value`) VALUES (?,?,?)
                   ON CONFLICT(guild_id,`key`) DO UPDATE SET `value`=excluded.`value`""",
                (guild_id, key, value),
            )
            await db.commit()
        _cache_set(self.path, guild_id, key, str(value))

    async def get(
        self,
        guild_id: int,
        key: str,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> str | None:
        # Explicit transaction connections bypass the process cache so callers
        # always observe the transaction's own isolation/uncommitted state.
        if connection is not None:
            cursor = await connection.execute(
                "SELECT `value` FROM guild_state WHERE guild_id=? AND `key`=?",
                (guild_id, key),
            )
            row = await cursor.fetchone()
            return str(row[0]) if row else None

        hit, cached = _cache_get(self.path, guild_id, key)
        if hit:
            return cached

        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT `value` FROM guild_state WHERE guild_id=? AND `key`=?",
                (guild_id, key),
            )
            row = await cursor.fetchone()
        value = str(row[0]) if row else None
        _cache_set(self.path, guild_id, key, value)
        return value

    async def get_many(
        self,
        guild_id: int,
        keys: list[str] | tuple[str, ...],
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> dict[str, str]:
        """Fetch multiple guild-state values in one round trip.

        High-frequency runtime paths get process-local cache hits across service
        instances. Missing keys are negative-cached too, avoiding repeated DB
        round trips for settings that intentionally use defaults.
        """
        ordered = [str(key) for key in dict.fromkeys(keys) if str(key)]
        if not ordered:
            return {}

        async def _read(db: aiosqlite.Connection, wanted: list[str]) -> dict[str, str]:
            placeholders = ",".join("?" for _ in wanted)
            sql = f"SELECT `key`,`value` FROM guild_state WHERE guild_id=? AND `key` IN ({placeholders})"
            cursor = await db.execute(sql, (guild_id, *wanted))
            rows = await cursor.fetchall()
            return {str(row[0]): str(row[1]) for row in rows}

        if connection is not None:
            return await _read(connection, ordered)

        result: dict[str, str] = {}
        missing: list[str] = []
        for key in ordered:
            hit, value = _cache_get(self.path, guild_id, key)
            if not hit:
                missing.append(key)
            elif value is not None:
                result[key] = value

        if missing:
            async with aiosqlite.connect(self.path) as db:
                fetched = await _read(db, missing)
            for key in missing:
                value = fetched.get(key)
                _cache_set(self.path, guild_id, key, value)
                if value is not None:
                    result[key] = value
        return result
