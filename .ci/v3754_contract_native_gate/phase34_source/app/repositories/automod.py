from __future__ import annotations

"""AutoMod persistence boundary."""

from app import db_backend


class AutomodRepository:
    """Own AutoMod rule, exemption, domain and word-list persistence."""

    def __init__(self, path: str) -> None:
        self.path = path

    async def get_rule(self, guild_id: int, rule: str) -> tuple[bool, str, int, int] | None:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT enabled,action,threshold,timeout_seconds FROM automod_rules WHERE guild_id=? AND rule=?",
                (guild_id, rule),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return bool(row[0]), str(row[1]), int(row[2]), int(row[3])

    async def set_rule(
        self,
        guild_id: int,
        rule: str,
        enabled: bool,
        action: str,
        threshold: int,
        timeout_seconds: int,
    ) -> None:
        async with db_backend.connect(self.path) as db:
            await db.execute(
                """INSERT INTO automod_rules (guild_id,rule,enabled,action,threshold,timeout_seconds)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(guild_id,rule) DO UPDATE SET
                     enabled=excluded.enabled, action=excluded.action,
                     threshold=excluded.threshold, timeout_seconds=excluded.timeout_seconds""",
                (guild_id, rule, int(enabled), action, int(threshold), int(timeout_seconds)),
            )
            await db.commit()

    async def list_rules(self, guild_id: int) -> dict[str, tuple[bool, str, int, int]]:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT rule,enabled,action,threshold,timeout_seconds FROM automod_rules WHERE guild_id=?",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return {
            str(row[0]): (bool(row[1]), str(row[2]), int(row[3]), int(row[4]))
            for row in rows
        }

    async def add_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> None:
        async with db_backend.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO automod_exemptions (guild_id,rule,scope_type,scope_id) VALUES (?,?,?,?)",
                (guild_id, rule, scope_type, scope_id),
            )
            await db.commit()

    async def remove_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> bool:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM automod_exemptions WHERE guild_id=? AND rule=? AND scope_type=? AND scope_id=?",
                (guild_id, rule, scope_type, scope_id),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def list_exemptions(self, guild_id: int, rule: str | None = None) -> list[tuple[str, str, int]]:
        async with db_backend.connect(self.path) as db:
            if rule is None:
                cursor = await db.execute(
                    "SELECT rule,scope_type,scope_id FROM automod_exemptions WHERE guild_id=? ORDER BY rule,scope_type,scope_id",
                    (guild_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT rule,scope_type,scope_id FROM automod_exemptions "
                    "WHERE guild_id=? AND rule IN (?, 'all') ORDER BY rule,scope_type,scope_id",
                    (guild_id, rule),
                )
            rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1]), int(row[2])) for row in rows]

    async def set_domain(self, guild_id: int, mode: str, domain: str) -> None:
        async with db_backend.connect(self.path) as db:
            # A domain cannot be both explicitly allowed and blocked.
            await db.execute(
                "DELETE FROM automod_domains WHERE guild_id=? AND domain=?",
                (guild_id, domain),
            )
            await db.execute(
                "INSERT OR REPLACE INTO automod_domains (guild_id,mode,domain) VALUES (?,?,?)",
                (guild_id, mode, domain),
            )
            await db.commit()

    async def remove_domain(self, guild_id: int, domain: str) -> bool:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM automod_domains WHERE guild_id=? AND domain=?",
                (guild_id, domain),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def list_domains(self, guild_id: int, mode: str | None = None) -> list[tuple[str, str]]:
        async with db_backend.connect(self.path) as db:
            if mode is None:
                cursor = await db.execute(
                    "SELECT mode,domain FROM automod_domains WHERE guild_id=? ORDER BY mode,domain",
                    (guild_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT mode,domain FROM automod_domains WHERE guild_id=? AND mode=? ORDER BY domain",
                    (guild_id, mode),
                )
            rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    async def add_word(self, guild_id: int, word: str) -> None:
        async with db_backend.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO automod_words (guild_id,word) VALUES (?,?)",
                (guild_id, word),
            )
            await db.commit()

    async def remove_word(self, guild_id: int, word: str) -> bool:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM automod_words WHERE guild_id=? AND word=?",
                (guild_id, word),
            )
            await db.commit()
            return bool(cursor.rowcount)

    async def list_words(self, guild_id: int) -> list[str]:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT word FROM automod_words WHERE guild_id=? ORDER BY word",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]
