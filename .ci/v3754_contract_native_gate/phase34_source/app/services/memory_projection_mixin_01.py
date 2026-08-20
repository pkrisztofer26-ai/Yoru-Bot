from __future__ import annotations
from .memory_projection_support import *

class ConsequenceMemoryServiceProjectionMixin01:

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _fact_from_row(row) -> MemoryFact:
        return MemoryFact(memory_id=int(row[0]), guild_id=int(row[1]), user_id=int(row[2]), memory_key=str(row[3]), category=str(row[4]), subject_type=str(row[5]), subject_key=str(row[6]), state_key=str(row[7]), value=_loads_dict(row[8]), active=bool(int(row[9])), source_history_event_id=int(row[10]) if row[10] is not None else None, occurred_at=str(row[11]), expires_at=str(row[12]) if row[12] else None, created_at=str(row[13]), updated_at=str(row[14]))

    @staticmethod
    def _relationship_from_row(row) -> RelationshipState:
        return RelationshipState(guild_id=int(row[0]), user_id=int(row[1]), subject_type=str(row[2]), subject_key=str(row[3]), trust_score=int(row[4]), favor_owed_to_player=int(row[5]), favor_owed_by_player=int(row[6]), rival_state=str(row[7]), flags=_loads_dict(row[8]), last_memory_key=str(row[9]) if row[9] else None, created_at=str(row[10]), updated_at=str(row[11]))

    @staticmethod
    async def _get_fact_row(db, guild_id: int, user_id: int, memory_key: str):
        cur = await db.execute('SELECT memory_id,guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,\n                      value_json,active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n               FROM character_memory_state\n               WHERE guild_id=? AND user_id=? AND memory_key=?', (int(guild_id), int(user_id), memory_key))
        return await cur.fetchone()

    @staticmethod
    async def _get_relationship_row(db, guild_id: int, user_id: int, subject_type: str, subject_key: str):
        cur = await db.execute('SELECT guild_id,user_id,subject_type,subject_key,trust_score,favor_owed_to_player,\n                      favor_owed_by_player,rival_state,flags_json,last_memory_key,created_at,updated_at\n               FROM character_relationship_state\n               WHERE guild_id=? AND user_id=? AND subject_type=? AND subject_key=?', (int(guild_id), int(user_id), subject_type, subject_key))
        return await cur.fetchone()

    async def remember(self, guild_id: int, user_id: int, *, memory_key: str, category: str, subject_type: str, subject_key: str, state_key: str, value: dict[str, Any] | None=None, occurred_at: str | None=None, expires_at: str | None=None, source_history_event_id: int | None=None, active: bool=True) -> MemoryFact:
        memory_key = _clean_key(memory_key, label='memory_key')
        category = _clean_key(category, label='category')
        subject_type = _clean_key(subject_type, label='subject_type')
        subject_key = _clean_key(subject_key, label='subject_key')
        state_key = _clean_key(state_key, label='state_key')
        if category not in _MEMORY_CATEGORIES:
            raise ValueError(f'Ismeretlen memory category: {category}')
        if subject_type not in _SUBJECT_TYPES:
            raise ValueError(f'Ismeretlen memory subject type: {subject_type}')
        now = _iso()
        occurred = str(occurred_at or now)
        expires = str(expires_at) if expires_at else None
        value_json = json.dumps(_safe_json_dict(value), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            if row is None:
                cursor = await db.execute('INSERT INTO character_memory_state(\n                           guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,value_json,\n                           active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (int(guild_id), int(user_id), memory_key, category, subject_type, subject_key, state_key, value_json, 1 if active else 0, source_history_event_id, occurred, expires, now, now))
                memory_id = int(cursor.lastrowid or 0)
            else:
                memory_id = int(row[0])
                await db.execute('UPDATE character_memory_state SET\n                           category=?,subject_type=?,subject_key=?,state_key=?,value_json=?,active=?,\n                           source_history_event_id=?,occurred_at=?,expires_at=?,updated_at=?\n                       WHERE guild_id=? AND user_id=? AND memory_key=?', (category, subject_type, subject_key, state_key, value_json, 1 if active else 0, source_history_event_id, occurred, expires, now, int(guild_id), int(user_id), memory_key))
            await db.commit()
            row = await self._get_fact_row(db, guild_id, user_id, memory_key)
        if row is None:
            raise RuntimeError(f'Memory fact write failed: {memory_id}')
        return self._fact_from_row(row)

    async def deactivate(self, guild_id: int, user_id: int, memory_key: str) -> bool:
        memory_key = _clean_key(memory_key, label='memory_key')
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute('UPDATE character_memory_state SET active=0,updated_at=? WHERE guild_id=? AND user_id=? AND memory_key=? AND active<>0', (_iso(), int(guild_id), int(user_id), memory_key))
            await db.commit()
            return int(cursor.rowcount or 0) > 0

    async def recall(self, guild_id: int, user_id: int, *, category: str | None=None, subject_type: str | None=None, subject_key: str | None=None, active_only: bool=True, limit: int=50) -> list[MemoryFact]:
        clauses = ['guild_id=?', 'user_id=?']
        params: list[Any] = [int(guild_id), int(user_id)]
        if category is not None:
            value = _clean_key(category, label='category')
            clauses.append('category=?')
            params.append(value)
        if subject_type is not None:
            value = _clean_key(subject_type, label='subject_type')
            clauses.append('subject_type=?')
            params.append(value)
        if subject_key is not None:
            value = _clean_key(subject_key, label='subject_key')
            clauses.append('subject_key=?')
            params.append(value)
        if active_only:
            clauses.append('active<>0')
        params.append(max(1, min(200, int(limit))))
        async with aiosqlite.connect(self.database.path) as db:
            cur = await db.execute(f"SELECT memory_id,guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,\n                            value_json,active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n                     FROM character_memory_state\n                     WHERE {' AND '.join(clauses)}\n                     ORDER BY occurred_at DESC,memory_id DESC LIMIT ?", tuple(params))
            rows = await cur.fetchall()
        facts = [self._fact_from_row(row) for row in rows]
        if active_only:
            facts = [item for item in facts if not item.expired]
        return facts

    async def relationship(self, guild_id: int, user_id: int, subject_type: str, subject_key: str) -> RelationshipState:
        subject_type = _clean_key(subject_type, label='subject_type')
        subject_key = _clean_key(subject_key, label='subject_key')
        if subject_type not in _SUBJECT_TYPES:
            raise ValueError(f'Ismeretlen relationship subject type: {subject_type}')
        async with aiosqlite.connect(self.database.path) as db:
            row = await self._get_relationship_row(db, guild_id, user_id, subject_type, subject_key)
        if row is None:
            now = _iso()
            return RelationshipState(int(guild_id), int(user_id), subject_type, subject_key, 0, 0, 0, 'none', {}, None, now, now)
        return self._relationship_from_row(row)
