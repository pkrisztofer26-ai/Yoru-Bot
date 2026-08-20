from __future__ import annotations
from app.database_support import *

class DatabaseMixin8:
        async def get_starting_balance(self, guild_id: int, db: aiosqlite.Connection | None=None) -> int:
            """Return the guild-scoped starting wallet balance.

            DB guild_state is authoritative; ``self.starting_balance`` remains the
            install-level fallback for servers that never changed the setting.
            Passing an existing connection avoids nested SQLite connections inside
            atomic service transactions.
            """
            if db is None:
                raw = await self.guild_state_repository.get(guild_id, 'economy_starting_balance')
            else:
                raw = await self.guild_state_repository.get(guild_id, 'economy_starting_balance', connection=db)
            try:
                value = self.starting_balance if raw is None or not str(raw).strip() else int(str(raw))
            except (TypeError, ValueError):
                value = self.starting_balance
            return max(0, min(10 ** 15, int(value)))

        async def ensure_user_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
            """Ensure a user using the caller-owned transaction/connection."""
            now = datetime.now(timezone.utc).isoformat()
            starting_balance = await self.get_starting_balance(guild_id, db=db)
            await db.execute('\n            INSERT OR IGNORE INTO users\n                (guild_id, user_id, wallet, bank, created_at)\n            VALUES (?, ?, ?, 0, ?)\n            ', (guild_id, user_id, starting_balance, now))

        async def ensure_user(self, guild_id: int, user_id: int) -> None:
            async with aiosqlite.connect(self.path) as db:
                await self.ensure_user_tx(db, guild_id, user_id)
                await db.commit()

        async def reserve_wallet_and_bank_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int, amount: int, reason: str, *, now: str | None=None) -> tuple[int, int, int, int]:
            """Caller-owned atomic reserve primitive used by escrow-style domains.

            Wallet is consumed first, then bank. No commit is performed here.
            Returns ``(wallet_used, bank_used, new_wallet, new_bank)``.
            """
            amount = int(amount)
            if amount <= 0:
                raise ValueError('Az összegnek pozitívnak kell lennie.')
            await self.ensure_user_tx(db, guild_id, user_id)
            now = now or datetime.now(timezone.utc).isoformat()
            cursor = await db.execute('SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?', (guild_id, user_id))
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError('A felhasználó nem található.')
            wallet, bank = (int(row[0]), int(row[1]))
            wallet_available = max(0, wallet)
            bank_available = max(0, bank)
            if wallet_available + bank_available < amount:
                raise ValueError('Nincs elég pénzed a tárcában és a bankban összesen.')
            wallet_used = min(wallet_available, amount)
            bank_used = amount - wallet_used
            new_wallet = wallet - wallet_used
            new_bank = bank - bank_used
            await db.execute('UPDATE users SET wallet = ?, bank = ?, money_lost = money_lost + ? WHERE guild_id = ? AND user_id = ?', (new_wallet, new_bank, amount, guild_id, user_id))
            await db.execute("INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)\n               VALUES (?, ?, 'economy.lost', ?, ?)\n               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET\n                   value = value + excluded.value, updated_at = excluded.updated_at", (guild_id, user_id, amount, now))
            await db.execute('INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)', (guild_id, user_id, -amount, reason, now))
            return (wallet_used, bank_used, new_wallet, new_bank)

        async def refund_wallet_and_bank_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int, wallet_amount: int, bank_amount: int, reason: str, *, now: str | None=None) -> tuple[int, int]:
            """Reverse a previous reserve into its original funding sources."""
            wallet_amount = max(0, int(wallet_amount))
            bank_amount = max(0, int(bank_amount))
            amount = wallet_amount + bank_amount
            if amount <= 0:
                raise ValueError('A visszatérítés összege pozitív legyen.')
            await self.ensure_user_tx(db, guild_id, user_id)
            now = now or datetime.now(timezone.utc).isoformat()
            await db.execute('UPDATE users\n               SET wallet = wallet + ?, bank = bank + ?,\n                   money_lost = MAX(0, money_lost - ?)\n               WHERE guild_id = ? AND user_id = ?', (wallet_amount, bank_amount, amount, guild_id, user_id))
            await db.execute("UPDATE user_statistics\n               SET value = MAX(0, value - ?), updated_at = ?\n               WHERE guild_id = ? AND user_id = ? AND stat_name = 'economy.lost'", (amount, now, guild_id, user_id))
            await db.execute('INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)', (guild_id, user_id, amount, reason, now))
            cursor = await db.execute('SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?', (guild_id, user_id))
            row = await cursor.fetchone()
            return (int(row[0]), int(row[1])) if row else (wallet_amount, bank_amount)

        async def credit_wallet_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int, amount: int, reason: str, *, now: str | None=None) -> int:
            """Credit an authoritative payout inside the caller-owned transaction."""
            amount = int(amount)
            if amount <= 0:
                raise ValueError('A jóváírás összege pozitív legyen.')
            await self.ensure_user_tx(db, guild_id, user_id)
            now = now or datetime.now(timezone.utc).isoformat()
            await db.execute('UPDATE users SET wallet=wallet+?, money_earned=money_earned+? WHERE guild_id=? AND user_id=?', (amount, amount, guild_id, user_id))
            await db.execute("INSERT INTO user_statistics(guild_id,user_id,stat_name,value,updated_at)\n               VALUES(?,?,'economy.earned',?,?)\n               ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET\n                   value=value+excluded.value,updated_at=excluded.updated_at", (guild_id, user_id, amount, now))
            cursor = await db.execute('SELECT wallet FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            row = await cursor.fetchone()
            new_wallet = int(row[0]) if row else amount
            await db.execute("INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)\n               VALUES (?, ?, 'economy.wallet_peak', ?, ?)\n               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET\n                   value = MAX(value, excluded.value), updated_at = excluded.updated_at", (guild_id, user_id, new_wallet, now))
            await db.execute('INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)', (guild_id, user_id, amount, reason, now))
            return new_wallet

        async def get_balance(self, guild_id: int, user_id: int) -> tuple[int, int]:
            await self.ensure_user(guild_id, user_id)
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?', (guild_id, user_id))
                row = await cursor.fetchone()
            if row is None:
                raise RuntimeError('A felhasználó létrehozása sikertelen volt.')
            return (int(row[0]), int(row[1]))

        async def debit_wallet_and_bank(self, guild_id: int, user_id: int, amount: int, reason: str) -> tuple[int, int, int, int]:
            """Atomically spend from wallet first, then bank, without requiring a manual withdraw.

            The transaction-scoped implementation lives in ``reserve_wallet_and_bank_tx``
            so escrow domains can share exactly the same accounting semantics.
            """
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    result = await self.reserve_wallet_and_bank_tx(db, guild_id, user_id, amount, reason)
                    await db.commit()
                    return result
                except Exception:
                    await db.rollback()
                    raise

        async def refund_wallet_and_bank(self, guild_id: int, user_id: int, wallet_amount: int, bank_amount: int, reason: str) -> tuple[int, int]:
            """Reverse ``debit_wallet_and_bank`` to the original funding sources."""
            async with aiosqlite.connect(self.path) as db:
                await db.execute('BEGIN IMMEDIATE')
                try:
                    result = await self.refund_wallet_and_bank_tx(db, guild_id, user_id, wallet_amount, bank_amount, reason)
                    await db.commit()
                    return result
                except Exception:
                    await db.rollback()
                    raise

        async def _add_stat_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int, stat_name: str, amount: int, now: str) -> None:
            await db.execute('INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)\n               VALUES (?, ?, ?, ?, ?)\n               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET\n                   value = value + excluded.value, updated_at = excluded.updated_at', (guild_id, user_id, stat_name, amount, now))

        async def get_user_stat(self, guild_id: int, user_id: int, stat_name: str) -> int | None:
            await self.ensure_user(guild_id, user_id)
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name = ?', (guild_id, user_id, stat_name))
                row = await cursor.fetchone()
            return None if row is None else int(row[0])

        async def get_user_statistics(self, guild_id: int, user_id: int, prefix: str | None=None) -> dict[str, int]:
            await self.ensure_user(guild_id, user_id)
            async with aiosqlite.connect(self.path) as db:
                if prefix:
                    cursor = await db.execute('SELECT stat_name, value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name LIKE ? ORDER BY stat_name', (guild_id, user_id, f'{prefix}%'))
                else:
                    cursor = await db.execute('SELECT stat_name, value FROM user_statistics WHERE guild_id = ? AND user_id = ? ORDER BY stat_name', (guild_id, user_id))
                rows = await cursor.fetchall()
            return {str(row[0]): int(row[1]) for row in rows}

        async def add_user_stat(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> int:
            await self.ensure_user(guild_id, user_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)\n                   VALUES (?, ?, ?, ?, ?)\n                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET\n                       value = value + excluded.value, updated_at = excluded.updated_at', (guild_id, user_id, stat_name, amount, now))
                cursor = await db.execute('SELECT value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name = ?', (guild_id, user_id, stat_name))
                row = await cursor.fetchone()
                await db.commit()
            return int(row[0]) if row else amount

        async def set_user_stat(self, guild_id: int, user_id: int, stat_name: str, value: int) -> int:
            await self.ensure_user(guild_id, user_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)\n                   VALUES (?, ?, ?, ?, ?)\n                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET\n                       value = excluded.value, updated_at = excluded.updated_at', (guild_id, user_id, stat_name, value, now))
                await db.commit()
            return value

        async def set_user_stat_max(self, guild_id: int, user_id: int, stat_name: str, value: int) -> int:
            await self.ensure_user(guild_id, user_id)
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.path) as db:
                await db.execute('INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)\n                   VALUES (?, ?, ?, ?, ?)\n                   ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET\n                       value = MAX(value, excluded.value), updated_at = excluded.updated_at', (guild_id, user_id, stat_name, value, now))
                cursor = await db.execute('SELECT value FROM user_statistics WHERE guild_id = ? AND user_id = ? AND stat_name = ?', (guild_id, user_id, stat_name))
                row = await cursor.fetchone()
                await db.commit()
            return int(row[0]) if row else value

        async def add_item(self, guild_id: int, user_id: int, item_id: str, quantity: int=1) -> None:
            await self.ensure_user(guild_id, user_id)
            async with aiosqlite.connect(self.path) as db:
                await db.execute('INSERT INTO inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity', (guild_id, user_id, item_id, quantity))
                await db.commit()

        async def get_item_quantity(self, guild_id: int, user_id: int, item_id: str) -> int:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute('SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?', (guild_id, user_id, item_id))
                row = await cursor.fetchone()
            return int(row[0]) if row else 0

