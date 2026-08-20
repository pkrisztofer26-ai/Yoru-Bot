from __future__ import annotations
from .jobs_projection_support import *

class JobsServiceProjectionMixin02:

    async def active_session(self, guild_id: int, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM job_sessions WHERE guild_id=? AND user_id=? AND status='active' ORDER BY created_at DESC LIMIT 1", (guild_id, user_id))
            row = await cur.fetchone()
        if row is None:
            return None
        data = dict(row)
        data['data'] = json.loads(data.pop('data_json') or '{}')
        return data

    async def history(self, guild_id: int, user_id: int, limit: int=10) -> list[dict]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute('SELECT * FROM job_history WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?', (guild_id, user_id, max(1, min(25, int(limit)))))
            return [dict(r) for r in await cur.fetchall()]
