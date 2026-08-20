from __future__ import annotations
from .memory_projection_support import *

class ConsequenceMemoryServiceProjectionMixin02:

    async def record_first_contact(self, guild_id: int, user_id: int, *, npc_key: str, source_key: str, occurred_at: str | None=None, value: dict[str, Any] | None=None) -> tuple[MemoryFact, RelationshipState, bool]:
        """Persist one immutable first-contact fact and unlock the relationship.

        The stable ``npc.<key>:first_contact`` fact is insert-once. A retry or a
        second valid encounter source returns the original fact unchanged, so
        the first source/timestamp cannot be rewritten by later gameplay.
        Relationship state is semantic only: no trust, favor, payout or domain
        settlement is modified here.
        """
        npc_key = _clean_key(npc_key, label='npc_key')
        source_key = _clean_key(source_key, label='first contact source')
        memory_key = _clean_key(f'npc.{npc_key}:first_contact', label='memory_key')
        now = _iso()
        occurred = str(occurred_at or now)
        payload = {'npc_key': npc_key, 'source_key': source_key}
        payload.update(_safe_json_dict(value))
        value_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            newly_unlocked = fact_row is None
            if fact_row is None:
                await db.execute('INSERT INTO character_memory_state(\n                           guild_id,user_id,memory_key,category,subject_type,subject_key,state_key,value_json,\n                           active,source_history_event_id,occurred_at,expires_at,created_at,updated_at\n                       ) VALUES(?,?,?,?,?,?,?,?,1,NULL,?,NULL,?,?)', (int(guild_id), int(user_id), memory_key, 'relationship', 'npc', npc_key, 'contact_unlocked', value_json, occurred, now, now))
                fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            if fact_row is None:
                await db.rollback()
                raise RuntimeError('First-contact memory write failed.')
            fact = self._fact_from_row(fact_row)
            first_payload = dict(fact.value)
            first_source = str(first_payload.get('source_key') or source_key)
            first_at = str(fact.occurred_at or occurred)
            relationship_row = await self._get_relationship_row(db, guild_id, user_id, 'npc', npc_key)
            if relationship_row is None:
                flags = {'contact_unlocked': True, 'contact_source': first_source, 'contact_unlocked_at': first_at}
                await db.execute("INSERT INTO character_relationship_state(\n                           guild_id,user_id,subject_type,subject_key,trust_score,favor_owed_to_player,\n                           favor_owed_by_player,rival_state,flags_json,last_memory_key,created_at,updated_at\n                       ) VALUES(?,?,?,?,0,0,0,'none',?,?,?,?)", (int(guild_id), int(user_id), 'npc', npc_key, json.dumps(flags, ensure_ascii=False, separators=(',', ':'), sort_keys=True), memory_key, now, now))
            else:
                current = self._relationship_from_row(relationship_row)
                flags = dict(current.flags)
                changed = not bool(flags.get('contact_unlocked'))
                flags['contact_unlocked'] = True
                flags.setdefault('contact_source', first_source)
                flags.setdefault('contact_unlocked_at', first_at)
                if changed:
                    await db.execute("UPDATE character_relationship_state\n                           SET flags_json=?,last_memory_key=COALESCE(last_memory_key,?),updated_at=?\n                           WHERE guild_id=? AND user_id=? AND subject_type='npc' AND subject_key=?", (json.dumps(flags, ensure_ascii=False, separators=(',', ':'), sort_keys=True), memory_key, now, int(guild_id), int(user_id), npc_key))
            await db.commit()
            fact_row = await self._get_fact_row(db, guild_id, user_id, memory_key)
            relationship_row = await self._get_relationship_row(db, guild_id, user_id, 'npc', npc_key)
        if fact_row is None or relationship_row is None:
            raise RuntimeError('First-contact relationship write failed.')
        return (self._fact_from_row(fact_row), self._relationship_from_row(relationship_row), newly_unlocked)

    async def age_resolved_relationships(self, guild_id: int, user_id: int, *, older_than_hours: int=72) -> int:
        """Age temporary ``resolved`` rival state back to neutral conflict state.

        Historical memory/flags remain intact; only the transient conflict state
        is normalized. Tension and persistent rival states never auto-disappear.
        """
        hours = max(1, min(24 * 90, int(older_than_hours)))
        now = _utcnow()
        cutoff = _iso(now - timedelta(hours=hours))
        now_s = _iso(now)
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute("UPDATE character_relationship_state\n                   SET rival_state='none',updated_at=?\n                   WHERE guild_id=? AND user_id=? AND subject_type='npc'\n                     AND rival_state='resolved' AND updated_at<=?", (now_s, int(guild_id), int(user_id), cutoff))
            await db.commit()
            return int(cursor.rowcount or 0)
