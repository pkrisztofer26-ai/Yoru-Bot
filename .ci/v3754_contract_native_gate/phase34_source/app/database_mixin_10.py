from __future__ import annotations
from app.database_support import *

class DatabaseMixin10:
        async def set_crew_member_role(self, guild_id: int, crew_id: int, user_id: int, role: str) -> None:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("UPDATE crew_members SET `role`=? WHERE guild_id=? AND crew_id=? AND user_id=? AND `role`!='leader'", (role, guild_id, crew_id, user_id))
                await db.commit()
            if cursor.rowcount <= 0:
                raise ValueError('A Szervezet rang nem módosítható.')

        async def transfer_crew_ownership(self, guild_id: int, crew_id: int, old_owner_id: int, new_owner_id: int) -> None:
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT `role` FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?', (guild_id, crew_id, old_owner_id))
                    old = await cursor.fetchone()
                    cursor = await db.execute('SELECT `role` FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?', (guild_id, crew_id, new_owner_id))
                    new = await cursor.fetchone()
                    if not old or str(old[0]) != 'leader' or (not new):
                        raise ValueError('A vezetés átadása nem lehetséges.')
                    await db.execute("UPDATE crew_members SET `role`='member' WHERE guild_id=? AND crew_id=? AND user_id=?", (guild_id, crew_id, old_owner_id))
                    await db.execute("UPDATE crew_members SET `role`='leader' WHERE guild_id=? AND crew_id=? AND user_id=?", (guild_id, crew_id, new_owner_id))
                    await db.execute('UPDATE crews SET owner_id=? WHERE guild_id=? AND crew_id=?', (new_owner_id, guild_id, crew_id))
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        async def deposit_to_crew_audited(self, guild_id: int, crew_id: int, user_id: int, amount: int) -> tuple[int, int, int]:
            if amount <= 0:
                raise ValueError('Az összegnek pozitívnak kell lennie.')
            await self.ensure_user(guild_id, user_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT 1 FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?', (guild_id, crew_id, user_id))
                    if await cursor.fetchone() is None:
                        raise ValueError('Nem vagy ennek a Crew-nak a tagja.')
                    cursor = await db.execute('SELECT wallet FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    wallet = int((await cursor.fetchone())[0])
                    if wallet < amount:
                        raise ValueError('Nincs ennyi pénz a tárcádban.')
                    await db.execute('UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=?', (amount, guild_id, user_id))
                    await db.execute('UPDATE crews SET bank=bank+?, total_contributed=total_contributed+? WHERE guild_id=? AND crew_id=?', (amount, amount, guild_id, crew_id))
                    await db.execute('UPDATE crew_members SET contributed=contributed+? WHERE guild_id=? AND crew_id=? AND user_id=?', (amount, guild_id, crew_id, user_id))
                    tx_cur = await db.execute('INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)', (guild_id, user_id, -amount, f'crew_deposit:{crew_id}', now))
                    transaction_id = int(tx_cur.lastrowid or 0)
                    cursor = await db.execute('SELECT bank FROM crews WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    crew_bank = int((await cursor.fetchone())[0])
                    await db.commit()
                    return (wallet - amount, crew_bank, transaction_id)
                except Exception:
                    await db.rollback()
                    raise

        async def withdraw_from_crew(self, guild_id: int, crew_id: int, user_id: int, amount: int) -> tuple[int, int]:
            if amount <= 0:
                raise ValueError('Az összegnek pozitívnak kell lennie.')
            await self.ensure_user(guild_id, user_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT 1 FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=?', (guild_id, crew_id, user_id))
                    member = await cursor.fetchone()
                    if member is None:
                        raise ValueError('Nem vagy ennek a Szervezetnak a tagja.')
                    cursor = await db.execute('SELECT bank FROM crews WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    row = await cursor.fetchone()
                    crew_bank = int(row[0]) if row else 0
                    if crew_bank < amount:
                        raise ValueError('Nincs ennyi pénz a Közös kasszaban.')
                    await db.execute('UPDATE crews SET bank=bank-? WHERE guild_id=? AND crew_id=?', (amount, guild_id, crew_id))
                    await db.execute('UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?', (amount, guild_id, user_id))
                    await db.execute('INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)', (guild_id, user_id, amount, f'crew_withdraw:{crew_id}', now))
                    cursor = await db.execute('SELECT wallet FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    wallet = int((await cursor.fetchone())[0])
                    await db.commit()
                    return (wallet, crew_bank - amount)
                except Exception:
                    await db.rollback()
                    raise

        async def upgrade_crew(self, guild_id: int, crew_id: int, expected_level: int, cost: int) -> None:
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT level,bank FROM crews WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    row = await cursor.fetchone()
                    if row is None:
                        raise ValueError('A Szervezet nem található.')
                    level, bank = (int(row[0]), int(row[1]))
                    if level != int(expected_level):
                        raise ValueError('A Szervezet működési háttere időközben megváltozott. Nyisd meg újra a panelt.')
                    if bank < int(cost):
                        raise ValueError(f'A fejlesztéshez ${int(cost):,} kell a Közös kasszaban.'.replace(',', ' '))
                    await db.execute('UPDATE crews SET bank=bank-?, level=level+1 WHERE guild_id=? AND crew_id=? AND level=?', (int(cost), guild_id, crew_id, level))
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        async def set_crew_description(self, guild_id: int, crew_id: int, description: str) -> None:
            async with aiosqlite.connect(self.path) as db:
                await db.execute('UPDATE crews SET description=? WHERE guild_id=? AND crew_id=?', (description, guild_id, crew_id))
                await db.commit()

        async def disband_crew(self, guild_id: int, crew_id: int, owner_id: int) -> tuple[str, int]:
            await self.ensure_user(guild_id, owner_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT name,owner_id,bank FROM crews WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    row = await cursor.fetchone()
                    if row is None or int(row[1]) != owner_id:
                        raise ValueError('Csak a Szervezet vezetője oszlathatja fel a Szervezetet.')
                    name, bank = (str(row[0]), int(row[2]))
                    if bank:
                        await db.execute('UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?', (bank, guild_id, owner_id))
                        await db.execute('INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)', (guild_id, owner_id, bank, f'crew_disband_refund:{crew_id}', now))
                    await db.execute('DELETE FROM crew_invites WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    await db.execute('DELETE FROM crew_member_custom_ranks WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    await db.execute('DELETE FROM crew_custom_ranks WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    await db.execute('DELETE FROM crew_perks WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    await db.execute('DELETE FROM crew_wars WHERE guild_id=? AND (challenger_crew_id=? OR target_crew_id=?)', (guild_id, crew_id, crew_id))
                    await db.execute('DELETE FROM crew_members WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    await db.execute('DELETE FROM crews WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    await db.commit()
                    return (name, bank)
                except Exception:
                    await db.rollback()
                    raise

        async def crew_leaderboard(self, guild_id: int, limit: int=10) -> list[dict[str, int | str]]:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT c.crew_id,c.guild_id,c.name,c.owner_id,c.bank,c.level,c.total_contributed,\n                          c.description,c.created_at,c.discord_role_id,\n                          (SELECT COUNT(*) FROM crew_members m WHERE m.guild_id=c.guild_id AND m.crew_id=c.crew_id)\n                   FROM crews c WHERE c.guild_id=?\n                   ORDER BY c.level DESC,c.total_contributed DESC,c.bank DESC,c.created_at ASC LIMIT ?', (guild_id, max(1, int(limit))))
                rows = await cursor.fetchall()
            return [self._crew_dict(row) for row in rows]

