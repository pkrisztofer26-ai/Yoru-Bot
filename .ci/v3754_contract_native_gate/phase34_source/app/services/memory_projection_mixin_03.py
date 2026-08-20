from __future__ import annotations
from .memory_projection_support import *

class ConsequenceMemoryServiceProjectionMixin03:

    async def record_consequence(self, guild_id: int, user_id: int, *, memory_key: str, category: str, subject_type: str, subject_key: str, state_key: str, value: dict[str, Any] | None=None, trust_delta: int=0, favor_to_player_delta: int=0, favor_by_player_delta: int=0, rival_state: str | None=None, relationship_flags: dict[str, Any] | None=None, source_history_event_id: int | None=None, occurred_at: str | None=None, expires_at: str | None=None) -> tuple[MemoryFact, RelationshipState | None]:
        """Atomically persist semantic memory and its relationship effect.

        ``memory_key`` is the idempotency boundary.  A retry may refresh the
        structured fact, but relationship deltas are applied only when the key
        is first inserted, so reconnect/retry cannot double-count trust/favors.
        """
        memory_key = _clean_key(memory_key, label='memory_key')
        category = _clean_key(category, label='category')
        subject_type = _clean_key(subject_type, label='subject_type')
        subject_key = _clean_key(subject_key, label='subject_key')
        state_key = _clean_key(state_key, label='state_key')
        if category not in _MEMORY_CATEGORIES:
            raise ValueError(f'Ismeretlen memory category: {category}')
        if subject_type not in _SUBJECT_TYPES:
            raise ValueError(f'Ismeretlen memory subject type: {subject_type}')
        if rival_state is not None:
            rival_state = _clean_key(rival_state, label='rival_state')
            if rival_state not in _RIVAL_STATES:
                raise ValueError(f'Ismeretlen rival state: {rival_state}')
        now = _iso()
        occurred = str(occurred_at or now)
        expires = str(expires_at) if expires_at else None
        value_json = json.dumps(_safe_json_dict(value), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        relationship_change = any((trust_delta, favor_to_player_delta, favor_by_player_delta)) or rival_state is not None or bool(relationship_flags)
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            was_known = fact_row is not None
            if fact_row is not None:
                existing_identity = (str(fact_row[4]), str(fact_row[5]), str(fact_row[6]), str(fact_row[7]))
                requested_identity = (category, subject_type, subject_key, state_key)
                if existing_identity != requested_identity:
                    raise ValueError('A memory_key már más semantic consequence identityhez tartozik; retry közben nem írható át új eseménnyé.')
            if fact_row is None:
                await db.execute('INSERT INTO character_memory_state(\n                           guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,value_json,\n                           active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (int(guild_id), int(user_id), memory_key, category, subject_type, subject_key, state_key, value_json, 1, source_history_event_id, occurred, expires, now, now))
            else:
                await db.execute('UPDATE character_memory_state SET\n                           category=?,subject_type=?,subject_key=?,state_key=?,value_json=?,active=1,\n                           source_history_event_id=?,occurred_at=?,expires_at=?,updated_at=?\n                       WHERE guild_id=? AND user_id=? AND memory_key=?', (category, subject_type, subject_key, state_key, value_json, source_history_event_id, occurred, expires, now, int(guild_id), int(user_id), memory_key))
            relationship_row = await self._get_relationship_row(db, guild_id, user_id, subject_type, subject_key)
            if relationship_change and (not was_known):
                if relationship_row is None:
                    current_trust = current_to = current_by = 0
                    current_rival = 'none'
                    current_flags: dict[str, Any] = {}
                    created_at = now
                else:
                    current = self._relationship_from_row(relationship_row)
                    current_trust = current.trust_score
                    current_to = current.favor_owed_to_player
                    current_by = current.favor_owed_by_player
                    current_rival = current.rival_state
                    current_flags = dict(current.flags)
                    created_at = current.created_at
                next_trust = max(-100, min(100, current_trust + int(trust_delta)))
                next_to = max(0, min(99, current_to + int(favor_to_player_delta)))
                next_by = max(0, min(99, current_by + int(favor_by_player_delta)))
                next_rival = rival_state or current_rival
                if relationship_flags:
                    current_flags.update(_safe_json_dict(relationship_flags))
                flags_json = json.dumps(current_flags, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
                if relationship_row is None:
                    await db.execute('INSERT INTO character_relationship_state(\n                               guild_id,user_id,subject_type,subject_key,trust_score,favor_owed_to_player,\n                               favor_owed_by_player,rival_state,flags_json,last_memory_key,created_at,updated_at\n                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (int(guild_id), int(user_id), subject_type, subject_key, next_trust, next_to, next_by, next_rival, flags_json, memory_key, created_at, now))
                else:
                    await db.execute('UPDATE character_relationship_state SET\n                               trust_score=?,favor_owed_to_player=?,favor_owed_by_player=?,rival_state=?,\n                               flags_json=?,last_memory_key=?,updated_at=?\n                           WHERE guild_id=? AND user_id=? AND subject_type=? AND subject_key=?', (next_trust, next_to, next_by, next_rival, flags_json, memory_key, now, int(guild_id), int(user_id), subject_type, subject_key))
            await db.commit()
            fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            relationship_row = await self._get_relationship_row(db, guild_id, user_id, subject_type, subject_key)
        if fact_row is None:
            raise RuntimeError('Consequence memory write failed.')
        fact = self._fact_from_row(fact_row)
        relationship = self._relationship_from_row(relationship_row) if relationship_row is not None else None
        return (fact, relationship)
