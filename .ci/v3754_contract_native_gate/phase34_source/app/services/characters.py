from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Any
from app import character_config as cfg
from app import db_backend as aiosqlite
from app.database import Database

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _iso(value: datetime | None=None) -> str:
    return (value or _utcnow()).isoformat()

def _clean_spaces(value: str) -> str:
    return re.sub('\\s+', ' ', str(value).strip())

@dataclass(frozen=True, slots=True)
class Character:
    guild_id: int
    user_id: int
    name: str
    age: int
    birthplace: str
    background_key: str
    home_city_key: str
    current_city_key: str
    status: str
    schema_version: int
    created_at: str
    updated_at: str
    finalized_at: str

@dataclass(frozen=True, slots=True)
class CharacterDraft:
    guild_id: int
    user_id: int
    name: str | None
    age: int | None
    birthplace: str | None
    background_key: str | None
    start_city_key: str | None
    step_key: str
    created_at: str
    updated_at: str
    expires_at: str

    @property
    def basic_complete(self) -> bool:
        return self.name is not None and self.age is not None and (self.birthplace is not None)

    @property
    def complete(self) -> bool:
        return self.basic_complete and self.start_city_key is not None and (self.background_key is not None)

@dataclass(frozen=True, slots=True)
class HistoryEvent:
    event_id: int
    guild_id: int
    user_id: int
    event_key: str
    title: str
    description: str
    metadata: dict[str, Any]
    created_at: str

class CharacterService:
    """RP identity layer.

    Money and legacy assets deliberately remain in their existing tables. This
    service only owns character identity, creation drafts and major life-history
    milestones.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self._active_character_cache_max = 32768
        self._active_character_ids: OrderedDict[tuple[int, int], None] = OrderedDict()

    def _remember_active(self, guild_id: int, user_id: int) -> None:
        key = (int(guild_id), int(user_id))
        if key in self._active_character_ids:
            self._active_character_ids.move_to_end(key)
            return
        if len(self._active_character_ids) >= self._active_character_cache_max:
            self._active_character_ids.popitem(last=False)
        self._active_character_ids[key] = None

    @staticmethod
    def _character_from_row(row: Any) -> Character:
        return Character(guild_id=int(row[0]), user_id=int(row[1]), name=str(row[2]), age=int(row[3]), birthplace=str(row[4]), background_key=str(row[5]), home_city_key=str(row[6]), current_city_key=str(row[7]), status=str(row[8]), schema_version=int(row[9]), created_at=str(row[10]), updated_at=str(row[11]), finalized_at=str(row[12]))

    async def get(self, guild_id: int, user_id: int) -> Character | None:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute("SELECT guild_id,user_id,character_name,age,birthplace,background_key,\n                          home_city_key,current_city_key,status,schema_version,created_at,updated_at,finalized_at\n                   FROM characters WHERE guild_id=? AND user_id=? AND status='active'", (guild_id, user_id))
            row = await cursor.fetchone()
        if row is None:
            return None
        character = self._character_from_row(row)
        self._remember_active(guild_id, user_id)
        return character

    async def require(self, guild_id: int, user_id: int) -> Character:
        character = await self.get(guild_id, user_id)
        if character is None:
            raise ValueError('Még nincs karaktered. Nyisd meg a /karakter panelt a létrehozásához.')
        return character

    async def add_history(self, guild_id: int, user_id: int, *, event_key: str, title: str, description: str, metadata: dict[str, Any] | None=None) -> int:
        await self.require(guild_id, user_id)
        now = _iso()
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute('INSERT INTO character_history\n                   (guild_id,user_id,event_key,title,description,metadata_json,created_at)\n                   VALUES (?,?,?,?,?,?,?)', (guild_id, user_id, str(event_key)[:64], str(title)[:128], str(description), json.dumps(metadata or {}, ensure_ascii=False, separators=(',', ':')), now))
            await db.commit()
            return int(cursor.lastrowid or 0)

    async def history(self, guild_id: int, user_id: int, *, limit: int=10) -> list[HistoryEvent]:
        limit = max(1, min(25, int(limit)))
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute('SELECT event_id,guild_id,user_id,event_key,title,description,metadata_json,created_at\n                   FROM character_history\n                   WHERE guild_id=? AND user_id=?\n                   ORDER BY event_id DESC LIMIT ?', (guild_id, user_id, limit))
            rows = await cursor.fetchall()
        events: list[HistoryEvent] = []
        for row in rows:
            try:
                metadata = json.loads(str(row[6] or '{}'))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            events.append(HistoryEvent(event_id=int(row[0]), guild_id=int(row[1]), user_id=int(row[2]), event_key=str(row[3]), title=str(row[4]), description=str(row[5]), metadata=metadata if isinstance(metadata, dict) else {}, created_at=str(row[7])))
        return events
