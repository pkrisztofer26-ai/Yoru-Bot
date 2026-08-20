from __future__ import annotations
from app.database_support import *

class DatabaseMixin9:
        async def _transfer_item_tx(self, db: aiosqlite.Connection, guild_id: int, sender_id: int, receiver_id: int, item_id: str, quantity: int) -> tuple[str, str, int]:
            if sender_id == receiver_id:
                raise ValueError('Saját magadnak nem küldhetsz tárgyat.')
            if quantity < 1:
                raise ValueError('A mennyiség legalább 1 legyen.')
            await self.ensure_user_tx(db, guild_id, sender_id)
            await self.ensure_user_tx(db, guild_id, receiver_id)
            cursor = await db.execute('SELECT name, emoji FROM shop_items WHERE item_id = ? AND active = 1', (item_id,))
            item = await cursor.fetchone()
            if item is None:
                raise LookupError('Nincs ilyen tárgy.')
            cursor = await db.execute('SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?', (guild_id, sender_id, item_id))
            row = await cursor.fetchone()
            if row is None or int(row[0]) < quantity:
                raise ValueError('Nincs ennyi ebből a tárgyból a Tárgyaid között.')
            await db.execute('UPDATE inventory SET quantity = quantity - ? WHERE guild_id = ? AND user_id = ? AND item_id = ?', (quantity, guild_id, sender_id, item_id))
            await db.execute('INSERT INTO inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity', (guild_id, receiver_id, item_id, quantity))
            return (str(item[0]), str(item[1]), int(quantity))

        async def transfer_item_audited(self, guild_id: int, sender_id: int, receiver_id: int, item_id: str, quantity: int, *, source_ref: str) -> tuple[int, str, str, int, bool]:
            """Idempotent owning-domain item transfer with a stable transfer id.

            ``source_ref`` belongs to the caller/domain. Replaying the same source
            returns the original transfer without moving inventory again. A changed
            sender/receiver/item/quantity under the same source is rejected.
            """
            source_ref = str(source_ref).strip()[:190]
            if not source_ref:
                raise ValueError('Az átadás forrásazonosítója nem lehet üres.')
            quantity = int(quantity)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cur = await db.execute('SELECT transfer_id,sender_id,receiver_id,item_id,quantity\n                       FROM item_transfer_history WHERE guild_id=? AND source_ref=?', (guild_id, source_ref))
                    prior = await cur.fetchone()
                    if prior is not None:
                        if int(prior[1]) != int(sender_id) or int(prior[2]) != int(receiver_id) or str(prior[3]) != str(item_id) or (int(prior[4]) != quantity):
                            await db.rollback()
                            raise ValueError('Ez az átadási azonosító már más művelethez tartozik.')
                        cur = await db.execute('SELECT name,emoji FROM shop_items WHERE item_id=?', (item_id,))
                        item = await cur.fetchone()
                        await db.rollback()
                        return (int(prior[0]), str(item[0] if item else item_id), str(item[1] if item else '📦'), quantity, True)
                    name, emoji, moved = await self._transfer_item_tx(db, guild_id, sender_id, receiver_id, item_id, quantity)
                    cur = await db.execute('INSERT INTO item_transfer_history(\n                           guild_id,sender_id,receiver_id,item_id,quantity,source_ref,created_at\n                       ) VALUES(?,?,?,?,?,?,?)', (guild_id, sender_id, receiver_id, item_id, moved, source_ref, now))
                    transfer_id = int(cur.lastrowid)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            return (transfer_id, name, emoji, moved, False)

        @staticmethod
        def _crew_dict(row) -> dict[str, object]:
            return {'crew_id': int(row[0]), 'guild_id': int(row[1]), 'name': str(row[2]), 'owner_id': int(row[3]), 'bank': int(row[4]), 'level': int(row[5]), 'total_contributed': int(row[6]), 'description': str(row[7] or ''), 'created_at': str(row[8]), 'discord_role_id': int(row[9]) if row[9] is not None else None, 'member_count': int(row[10])}

        async def get_crew(self, guild_id: int, crew_id: int) -> dict[str, int | str] | None:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT c.crew_id,c.guild_id,c.name,c.owner_id,c.bank,c.level,c.total_contributed,\n                          c.description,c.created_at,c.discord_role_id,\n                          (SELECT COUNT(*) FROM crew_members m WHERE m.guild_id=c.guild_id AND m.crew_id=c.crew_id)\n                   FROM crews c WHERE c.guild_id=? AND c.crew_id=?', (guild_id, crew_id))
                row = await cursor.fetchone()
            return self._crew_dict(row) if row else None

        async def get_crew_membership(self, guild_id: int, user_id: int) -> tuple[dict[str, int | str], dict[str, int | str]] | None:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT c.crew_id,c.guild_id,c.name,c.owner_id,c.bank,c.level,c.total_contributed,\n                          c.description,c.created_at,c.discord_role_id,\n                          (SELECT COUNT(*) FROM crew_members mm WHERE mm.guild_id=c.guild_id AND mm.crew_id=c.crew_id),\n                          m.user_id,m.role,m.contributed,m.joined_at\n                   FROM crew_members m\n                   JOIN crews c ON c.crew_id=m.crew_id AND c.guild_id=m.guild_id\n                   WHERE m.guild_id=? AND m.user_id=?', (guild_id, user_id))
                row = await cursor.fetchone()
            if row is None:
                return None
            crew = self._crew_dict(row[:11])
            member = {'user_id': int(row[11]), 'role': str(row[12]), 'contributed': int(row[13]), 'joined_at': str(row[14])}
            return (crew, member)

        async def get_crew_members(self, guild_id: int, crew_id: int) -> list[dict[str, int | str]]:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("SELECT user_id,`role`,contributed,joined_at\n                   FROM crew_members WHERE guild_id=? AND crew_id=?\n                   ORDER BY CASE role WHEN 'leader' THEN 2 WHEN 'officer' THEN 1 ELSE 0 END DESC,\n                            contributed DESC, joined_at ASC", (guild_id, crew_id))
                rows = await cursor.fetchall()
            return [{'user_id': int(r[0]), 'role': str(r[1]), 'contributed': int(r[2]), 'joined_at': str(r[3])} for r in rows]

        async def create_crew(self, guild_id: int, user_id: int, name: str, normalized_name: str, cost: int) -> dict[str, int | str]:
            await self.ensure_user(guild_id, user_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT crew_id FROM crew_members WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    if await cursor.fetchone():
                        raise ValueError('Már egy Szervezet tagja vagy.')
                    cursor = await db.execute('SELECT 1 FROM crews WHERE guild_id=? AND normalized_name=?', (guild_id, normalized_name))
                    if await cursor.fetchone():
                        raise ValueError('Ezen a szerveren már van ilyen nevű Crew.')
                    cursor = await db.execute('SELECT wallet FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    row = await cursor.fetchone()
                    wallet = int(row[0]) if row else 0
                    if wallet < int(cost):
                        raise ValueError(f'A Szervezet alapítása ${int(cost):,}, de nincs elég pénz a tárcádban.'.replace(',', ' '))
                    await db.execute('UPDATE users SET wallet=wallet-?, money_lost=money_lost+? WHERE guild_id=? AND user_id=?', (int(cost), int(cost), guild_id, user_id))
                    cursor = await db.execute("INSERT INTO crews (guild_id,name,normalized_name,owner_id,bank,level,total_contributed,description,created_at)\n                       VALUES (?,?,?,?,0,1,0,'',?)", (guild_id, name, normalized_name, user_id, now))
                    crew_id = int(cursor.lastrowid or 0)
                    await db.execute("INSERT INTO crew_members (guild_id,crew_id,user_id,`role`,contributed,joined_at) VALUES (?,?,?,'leader',0,?)", (guild_id, crew_id, user_id, now))
                    await db.execute('INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)', (guild_id, user_id, -int(cost), f'crew_create:{crew_id}', now))
                    await self._add_stat_tx(db, guild_id, user_id, 'economy.lost', int(cost), now)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            crew = await self.get_crew(guild_id, crew_id)
            if crew is None:
                raise RuntimeError('A Szervezet létrehozása sikertelen volt.')
            return crew

        async def set_crew_discord_role_id(self, guild_id: int, crew_id: int, role_id: int | None) -> None:
            async with aiosqlite.connect(self.path) as db:
                await db.execute('UPDATE crews SET discord_role_id=? WHERE guild_id=? AND crew_id=?', (int(role_id) if role_id else None, guild_id, crew_id))
                await db.commit()

        async def set_crew_invite(self, guild_id: int, crew_id: int, user_id: int, invited_by: int, expires_at: datetime) -> None:
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('INSERT INTO crew_invites (guild_id,crew_id,user_id,invited_by,created_at,expires_at)\n                   VALUES (?,?,?,?,?,?)\n                   ON CONFLICT(guild_id,user_id) DO UPDATE SET\n                     crew_id=excluded.crew_id, invited_by=excluded.invited_by,\n                     created_at=excluded.created_at, expires_at=excluded.expires_at', (guild_id, crew_id, user_id, invited_by, now, expires_at.isoformat()))
                await db.commit()

        async def get_crew_invite(self, guild_id: int, user_id: int) -> tuple[dict[str, int | str], str] | None:
            now = datetime.now(timezone.utc)
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT i.crew_id,i.expires_at FROM crew_invites i\n                   WHERE i.guild_id=? AND i.user_id=?', (guild_id, user_id))
                row = await cursor.fetchone()
                if row is None:
                    return None
                expires = datetime.fromisoformat(str(row[1]))
                expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    await db.execute('DELETE FROM crew_invites WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    await db.commit()
                    return None
                crew_id = int(row[0])
            crew = await self.get_crew(guild_id, crew_id)
            return (crew, expires.isoformat()) if crew else None

        async def accept_crew_invite(self, guild_id: int, user_id: int, member_cap: int) -> int:
            now = datetime.now(timezone.utc)
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    cursor = await db.execute('SELECT crew_id FROM crew_members WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    if await cursor.fetchone():
                        raise ValueError('Már egy Szervezet tagja vagy.')
                    cursor = await db.execute('SELECT crew_id,expires_at FROM crew_invites WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    invite = await cursor.fetchone()
                    if invite is None:
                        raise ValueError('Nincs aktív Crew meghívód.')
                    expires = datetime.fromisoformat(str(invite[1]))
                    expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
                    if expires <= now:
                        await db.execute('DELETE FROM crew_invites WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                        raise ValueError('A Szervezet meghívód lejárt.')
                    crew_id = int(invite[0])
                    cursor = await db.execute('SELECT COUNT(*) FROM crew_members WHERE guild_id=? AND crew_id=?', (guild_id, crew_id))
                    count = int((await cursor.fetchone())[0])
                    if count >= int(member_cap):
                        raise ValueError('A Szervezet időközben megtelt.')
                    await db.execute("INSERT INTO crew_members (guild_id,crew_id,user_id,`role`,contributed,joined_at) VALUES (?,?,?,'member',0,?)", (guild_id, crew_id, user_id, now.isoformat()))
                    await db.execute('DELETE FROM crew_invites WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                    await db.commit()
                    return crew_id
                except Exception:
                    await db.rollback()
                    raise

        async def remove_crew_member(self, guild_id: int, crew_id: int, user_id: int) -> None:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("DELETE FROM crew_members WHERE guild_id=? AND crew_id=? AND user_id=? AND `role`!='leader'", (guild_id, crew_id, user_id))
                if cursor.rowcount > 0:
                    await db.execute('DELETE FROM crew_member_custom_ranks WHERE guild_id=? AND crew_id=? AND user_id=?', (guild_id, crew_id, user_id))
                await db.execute('DELETE FROM crew_invites WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                await db.commit()
            if cursor.rowcount <= 0:
                raise ValueError('A Szervezet tag nem távolítható el.')

