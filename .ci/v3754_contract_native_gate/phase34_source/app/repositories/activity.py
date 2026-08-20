from __future__ import annotations

"""High-volume Community XP persistence boundary.

This repository deliberately keeps Discord concerns and XP/rule calculation out
of persistence.  It also collapses the legacy multi-connection activity write
paths so a counted chat/voice event uses one leased DB connection for ensure,
mutation and the returned projection.
"""

from datetime import datetime, timezone

from app import db_backend


_PROFILE_KEYS = (
    "total_xp",
    "chat_xp",
    "voice_xp",
    "message_count",
    "voice_seconds",
    "level",
    "last_chat_xp_at",
    "last_message_at",
    "last_message_hash",
)


class ActivityRepository:
    """Canonical storage access for ``activity_users`` and message hashes."""

    def __init__(self, path: str) -> None:
        self.path = path

    @staticmethod
    def _profile_dict(row) -> dict[str, int | str | None]:
        if row is None:
            raise RuntimeError("Az Activity profil létrehozása sikertelen volt.")
        return dict(zip(_PROFILE_KEYS, row, strict=True))

    @staticmethod
    async def _ensure_user_on_connection(db, guild_id: int, user_id: int, now: str) -> None:
        await db.execute(
            """INSERT OR IGNORE INTO activity_users
               (guild_id,user_id,total_xp,chat_xp,voice_xp,message_count,voice_seconds,level,updated_at)
               VALUES (?,?,0,0,0,0,0,0,?)""",
            (guild_id, user_id, now),
        )

    @staticmethod
    async def _select_profile_on_connection(db, guild_id: int, user_id: int):
        cursor = await db.execute(
            """SELECT total_xp,chat_xp,voice_xp,message_count,voice_seconds,level,
                      last_chat_xp_at,last_message_at,last_message_hash
               FROM activity_users WHERE guild_id=? AND user_id=?""",
            (guild_id, user_id),
        )
        return await cursor.fetchone()

    async def get_profile(self, guild_id: int, user_id: int) -> dict[str, int | str | None]:
        """Read an existing profile without taking a write lock on the hot path.

        The legacy facade executed ``INSERT OR IGNORE`` before every profile
        read.  Existing users now stay read-only; only a missing profile performs
        the idempotent insert.
        """
        async with db_backend.connect(self.path) as db:
            row = await self._select_profile_on_connection(db, guild_id, user_id)
            if row is None:
                now = datetime.now(timezone.utc).isoformat()
                await self._ensure_user_on_connection(db, guild_id, user_id, now)
                await db.commit()
                row = await self._select_profile_on_connection(db, guild_id, user_id)
        return self._profile_dict(row)

    async def message_hash_seen_since(
        self,
        guild_id: int,
        user_id: int,
        message_hash: str,
        since: str,
    ) -> bool:
        """Check duplicate protection without a standalone write transaction.

        Stale-row pruning is folded into the next accepted message transaction,
        which removes one write/commit from the normal accepted-message path.
        """
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT 1 FROM activity_message_hashes
                   WHERE guild_id=? AND user_id=? AND message_hash=? AND last_seen>=? LIMIT 1""",
                (guild_id, user_id, message_hash, since),
            )
            row = await cursor.fetchone()
        return row is not None

    async def record_message(
        self,
        guild_id: int,
        user_id: int,
        *,
        xp_award: int,
        new_level: int,
        message_hash: str,
        now: str,
        prune_before: str | None = None,
    ) -> dict[str, int | str | None]:
        xp_award = max(0, int(xp_award))
        async with db_backend.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._ensure_user_on_connection(db, guild_id, user_id, now)
            if xp_award > 0:
                await db.execute(
                    """UPDATE activity_users SET
                           total_xp=total_xp+?,chat_xp=chat_xp+?,message_count=message_count+1,
                           level=?,last_chat_xp_at=?,last_message_at=?,last_message_hash=?,updated_at=?
                       WHERE guild_id=? AND user_id=?""",
                    (xp_award, xp_award, new_level, now, now, message_hash, now, guild_id, user_id),
                )
            else:
                await db.execute(
                    """UPDATE activity_users SET
                           message_count=message_count+1,level=?,last_message_at=?,last_message_hash=?,updated_at=?
                       WHERE guild_id=? AND user_id=?""",
                    (new_level, now, message_hash, now, guild_id, user_id),
                )
            if prune_before is not None:
                await db.execute(
                    "DELETE FROM activity_message_hashes WHERE guild_id=? AND user_id=? AND last_seen<?",
                    (guild_id, user_id, prune_before),
                )
            await db.execute(
                """INSERT INTO activity_message_hashes(guild_id,user_id,message_hash,last_seen) VALUES (?,?,?,?)
                   ON CONFLICT(guild_id,user_id,message_hash) DO UPDATE SET last_seen=excluded.last_seen""",
                (guild_id, user_id, message_hash, now),
            )
            row = await self._select_profile_on_connection(db, guild_id, user_id)
            await db.commit()
        return self._profile_dict(row)

    async def record_voice(
        self,
        guild_id: int,
        user_id: int,
        *,
        seconds: int,
        xp_award: int,
        new_level: int,
        now: str,
    ) -> dict[str, int | str | None]:
        seconds = max(0, int(seconds))
        xp_award = max(0, int(xp_award))
        async with db_backend.connect(self.path) as db:
            await self._ensure_user_on_connection(db, guild_id, user_id, now)
            await db.execute(
                """UPDATE activity_users SET
                       total_xp=total_xp+?,voice_xp=voice_xp+?,voice_seconds=voice_seconds+?,
                       level=?,updated_at=?
                   WHERE guild_id=? AND user_id=?""",
                (xp_award, xp_award, seconds, new_level, now, guild_id, user_id),
            )
            row = await self._select_profile_on_connection(db, guild_id, user_id)
            await db.commit()
        return self._profile_dict(row)

    async def list_user_ids(self, guild_id: int) -> list[int]:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT user_id FROM activity_users "
                "WHERE guild_id=? AND (total_xp>0 OR message_count>0 OR voice_seconds>0)",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]

    async def leaderboard(self, guild_id: int, category: str, limit: int = 10) -> list[tuple[int, int, int, int]]:
        columns = {
            "activity": ("level", "total_xp", "message_count"),
            "activity_xp": ("total_xp", "level", "message_count"),
            "chat": ("message_count", "chat_xp", "level"),
            "chatxp": ("chat_xp", "message_count", "level"),
            "voice": ("voice_seconds", "voice_xp", "level"),
        }
        primary, secondary, tertiary = columns.get(category, columns["activity"])
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                f"SELECT user_id,{secondary},{tertiary},{primary} AS score FROM activity_users "
                "WHERE guild_id=? ORDER BY score DESC,total_xp DESC LIMIT ?",
                (guild_id, max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rows]
