# STATIC_CONTRACT: police_street_incident
# STATIC_CONTRACT: police_robbery_incident
# STATIC_CONTRACT: police_heist_incident
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from app import db_backend as aiosqlite
from app import police_config as cfg
from app.database import Database
from app.services.characters import CharacterService
from app.services.memory_adapters import MemoryAdapterService
logger = logging.getLogger('vaultbot.police')

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _iso(value: datetime | None=None) -> str:
    return (value or _utcnow()).isoformat()

def _parse(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

@dataclass(frozen=True, slots=True)
class PoliceState:
    guild_id: int
    user_id: int
    points: int
    status_key: str
    status_name: str
    emoji: str
    description: str
    updated_at: str

class PoliceService:
    """Hidden police-attention state with natural player-facing statuses.

    Legacy crime counters are deliberately not imported as current attention.
    Every RP character starts neutral; only post-RP actions modify this state.
    """

    def __init__(self, database: Database, characters: CharacterService, world=None, memory_adapters: MemoryAdapterService | None=None) -> None:
        self.database = database
        self.characters = characters
        self.world = world
        self.memory_adapters = memory_adapters

    async def _legal_contact_after_incident(self, guild_id: int, user_id: int, *, source_key: str, occurred_at: str) -> None:
        if self.memory_adapters is None:
            return
        try:
            await self.memory_adapters.police_incident(guild_id, user_id, source_key=source_key, occurred_at=occurred_at)
        except Exception:
            logger.exception('Police first-contact memory failed guild=%s user=%s source=%s', guild_id, user_id, source_key)

    async def _world_illegal_bonus(self, guild_id: int, user_id: int) -> int:
        if self.world is None:
            return 0
        try:
            character = await self.characters.require(guild_id, user_id)
            return int(await self.world.illegal_attention_bonus(guild_id, character.current_city_key))
        except Exception:
            return 0

    @staticmethod
    def _state(guild_id: int, user_id: int, points: int, updated_at: str) -> PoliceState:
        status = cfg.status_for(points)
        return PoliceState(int(guild_id), int(user_id), int(points), status.key, status.name, status.emoji, status.description, str(updated_at))

    async def get(self, guild_id: int, user_id: int) -> PoliceState:
        await self.characters.require(guild_id, user_id)
        now = _utcnow()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            cursor = await db.execute('SELECT attention_points,last_decay_at,updated_at FROM character_police_state WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            row = await cursor.fetchone()
            if row is None:
                now_s = _iso(now)
                await db.execute('INSERT INTO character_police_state(guild_id,user_id,attention_points,last_decay_at,updated_at) VALUES(?,?,?,?,?)', (guild_id, user_id, 0, now_s, now_s))
                await db.commit()
                return self._state(guild_id, user_id, 0, now_s)
            points = max(0, min(cfg.MAX_ATTENTION, int(row[0])))
            last_decay = _parse(str(row[1]) if row[1] is not None else None, now)
            elapsed_hours = max(0, int((now - last_decay).total_seconds() // 3600))
            if elapsed_hours > 0:
                decay = elapsed_hours * cfg.DECAY_POINTS_PER_HOUR
                points = max(0, points - decay)
                new_decay = last_decay + timedelta(hours=elapsed_hours)
                updated = _iso(now)
                await db.execute('UPDATE character_police_state SET attention_points=?,last_decay_at=?,updated_at=? WHERE guild_id=? AND user_id=?', (points, _iso(new_decay), updated, guild_id, user_id))
                await db.commit()
                return self._state(guild_id, user_id, points, updated)
            await db.commit()
            return self._state(guild_id, user_id, points, str(row[2]))

    async def add_attention(self, guild_id: int, user_id: int, amount: int) -> PoliceState:
        current = await self.get(guild_id, user_id)
        delta = max(0, int(amount))
        if delta <= 0:
            return current
        now = _iso()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            cursor = await db.execute('SELECT attention_points FROM character_police_state WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            row = await cursor.fetchone()
            base = int(row[0]) if row is not None else current.points
            points = min(cfg.MAX_ATTENTION, max(0, base) + delta)
            await db.execute('UPDATE character_police_state SET attention_points=?,updated_at=? WHERE guild_id=? AND user_id=?', (points, now, guild_id, user_id))
            await db.commit()
        return self._state(guild_id, user_id, points, now)

    async def crime_result(self, guild_id: int, user_id: int, *, success: bool, jailed: bool) -> PoliceState:
        if success:
            delta = 5
        else:
            delta = 15
        if jailed:
            delta += 10
        delta += await self._world_illegal_bonus(guild_id, user_id)
        state = await self.add_attention(guild_id, user_id, delta)
        if not success or jailed:
            await self._legal_contact_after_incident(guild_id, user_id, source_key='police_crime_incident', occurred_at=state.updated_at)
        return state
