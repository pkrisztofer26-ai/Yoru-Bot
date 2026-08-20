from __future__ import annotations
from .memory_projection_support import *

class ConsequenceMemoryServiceProjectionMixin04:

    async def consume_favor(self, guild_id: int, user_id: int, *, subject_type: str, subject_key: str, memory_key: str, state_key: str='favor_redeemed', direction: str='to_player', value: dict[str, Any] | None=None, occurred_at: str | None=None) -> tuple[MemoryFact, RelationshipState, bool]:
        """Atomically consume exactly one relationship favor.

        ``memory_key`` is the idempotency boundary. Replaying the same redemption
        returns the existing fact without decrementing the counter again. A first
        redemption fails closed when no matching favor exists.
        """
        subject_type = _clean_key(subject_type, label='subject_type')
        subject_key = _clean_key(subject_key, label='subject_key')
        memory_key = _clean_key(memory_key, label='memory_key')
        state_key = _clean_key(state_key, label='state_key')
        direction = _clean_key(direction, label='favor direction')
        if subject_type not in _SUBJECT_TYPES:
            raise ValueError(f'Ismeretlen relationship subject type: {subject_type}')
        if direction not in {'to_player', 'by_player'}:
            raise ValueError(f'Ismeretlen favor direction: {direction}')
        now = _iso()
        occurred = str(occurred_at or now)
        payload = _safe_json_dict(value)
        payload['direction'] = direction
        value_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            relationship_row = await self._get_relationship_row(db, guild_id, user_id, subject_type, subject_key)
            if fact_row is not None:
                existing_identity = (str(fact_row[4]), str(fact_row[5]), str(fact_row[6]), str(fact_row[7]))
                requested_identity = ('favor', subject_type, subject_key, state_key)
                if existing_identity != requested_identity:
                    raise ValueError('A memory_key már más semantic consequence identityhez tartozik; favor retry közben nem írható át új eseménnyé.')
                await db.commit()
                if relationship_row is None:
                    raise RuntimeError('A beváltott favorhoz hiányzik a relationship state.')
                return (self._fact_from_row(fact_row), self._relationship_from_row(relationship_row), False)
            if relationship_row is None:
                raise ValueError('Nincs beváltható szívességed ennél a kapcsolatnál.')
            current = self._relationship_from_row(relationship_row)
            current_count = current.favor_owed_to_player if direction == 'to_player' else current.favor_owed_by_player
            if int(current_count) <= 0:
                raise ValueError('Nincs beváltható szívességed ennél a kapcsolatnál.')
            await db.execute('INSERT INTO character_memory_state(\n                       guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,value_json,\n                       active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (int(guild_id), int(user_id), memory_key, 'favor', subject_type, subject_key, state_key, value_json, 1, None, occurred, None, now, now))
            if direction == 'to_player':
                await db.execute('UPDATE character_relationship_state SET\n                           favor_owed_to_player=favor_owed_to_player-1,last_memory_key=?,updated_at=?\n                       WHERE guild_id=? AND user_id=? AND subject_type=? AND subject_key=?\n                         AND favor_owed_to_player>0', (memory_key, now, int(guild_id), int(user_id), subject_type, subject_key))
            else:
                await db.execute('UPDATE character_relationship_state SET\n                           favor_owed_by_player=favor_owed_by_player-1,last_memory_key=?,updated_at=?\n                       WHERE guild_id=? AND user_id=? AND subject_type=? AND subject_key=?\n                         AND favor_owed_by_player>0', (memory_key, now, int(guild_id), int(user_id), subject_type, subject_key))
            await db.commit()
            fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            relationship_row = await self._get_relationship_row(db, guild_id, user_id, subject_type, subject_key)
        if fact_row is None or relationship_row is None:
            raise RuntimeError('Favor redemption write failed.')
        return (self._fact_from_row(fact_row), self._relationship_from_row(relationship_row), True)

    @staticmethod
    def _favor_effect_state_key(effect_key: str) -> str:
        clean = _clean_key(effect_key, label='favor effect key')
        return _clean_key(f'favor_effect.{clean}', label='favor effect state_key')

    async def active_favor_effect_tx(self, db, guild_id: int, user_id: int, *, effect_key: str, subject_key: str | None=None) -> MemoryFact | None:
        """Return the oldest active redeemed favor voucher inside caller TX.

        This helper does not begin/commit/rollback a transaction.  It exists so
        the owning gameplay domain can decide a final price/state first, then
        consume the voucher in the *same* authoritative transaction.
        """
        state_key = self._favor_effect_state_key(effect_key)
        clauses = ['guild_id=?', 'user_id=?', "category='favor'", 'state_key=?', 'active<>0']
        params: list[Any] = [int(guild_id), int(user_id), state_key]
        if subject_key is not None:
            clean_subject = _clean_key(subject_key, label='favor effect subject_key')
            clauses.append("subject_type='npc'")
            clauses.append('subject_key=?')
            params.append(clean_subject)
        cur = await db.execute(f"SELECT memory_id,guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,\n                       value_json,active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n                FROM character_memory_state\n                WHERE {' AND '.join(clauses)}\n                ORDER BY occurred_at,memory_id LIMIT 1", tuple(params))
        row = await cur.fetchone()
        if row is None:
            return None
        fact = self._fact_from_row(row)
        return None if fact.expired else fact

    async def active_favor_effect(self, guild_id: int, user_id: int, *, effect_key: str, subject_key: str | None=None) -> MemoryFact | None:
        async with aiosqlite.connect(self.database.path) as db:
            return await self.active_favor_effect_tx(db, guild_id, user_id, effect_key=effect_key, subject_key=subject_key)

    async def consume_active_favor_effect_tx(self, db, *, memory_id: int) -> bool:
        """Consume one already-redeemed favor voucher inside caller TX."""
        cursor = await db.execute("UPDATE character_memory_state\n               SET active=0,updated_at=?\n               WHERE memory_id=? AND category='favor' AND active<>0", (_iso(), int(memory_id)))
        return int(cursor.rowcount or 0) == 1

    async def snapshot(self, guild_id: int, user_id: int, *, fact_limit: int=100) -> MemorySnapshot:
        facts = await self.recall(guild_id, user_id, active_only=True, limit=fact_limit)
        async with aiosqlite.connect(self.database.path) as db:
            cur = await db.execute('SELECT guild_id,user_id,subject_type,subject_key,trust_score,favor_owed_to_player,\n                          favor_owed_by_player,rival_state,flags_json,last_memory_key,created_at,updated_at\n                   FROM character_relationship_state\n                   WHERE guild_id=? AND user_id=? ORDER BY updated_at DESC', (int(guild_id), int(user_id)))
            rows = await cur.fetchall()
        return MemorySnapshot(tuple(facts), tuple((self._relationship_from_row(row) for row in rows)))
