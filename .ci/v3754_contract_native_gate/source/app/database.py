from __future__ import annotations

from datetime import datetime, timezone
from app import db_backend as aiosqlite
from app.contract_schema_mysql import MYSQL_CONTRACT_DDL

class Database:
    def __init__(self, path: str, starting_balance: int = 0) -> None:
        self.path = str(path)
        self.starting_balance = int(starting_balance)

    async def get_starting_balance(self, guild_id: int, *, db=None) -> int:
        return int(self.starting_balance)

    async def _ensure_contract_economy_schema(self, db: aiosqlite.Connection) -> None:
        if not aiosqlite.using_mysql():
            raise RuntimeError("W14.5N native projection is MySQL-only")
        for statement in MYSQL_CONTRACT_DDL:
            await aiosqlite.execute_backend_ddl(db, sqlite_sql=statement, mysql_sql=statement)

    async def ensure_user_tx(self, db: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
        """Ensure a user using the caller-owned transaction/connection."""
        now = datetime.now(timezone.utc).isoformat()
        starting_balance = await self.get_starting_balance(guild_id, db=db)
        await db.execute(
            """
            INSERT OR IGNORE INTO users
                (guild_id, user_id, wallet, bank, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (guild_id, user_id, starting_balance, now),
        )

    async def ensure_user(self, guild_id: int, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self.ensure_user_tx(db, guild_id, user_id)
            await db.commit()

    async def reserve_wallet_and_bank_tx(
        self,
        db: aiosqlite.Connection,
        guild_id: int,
        user_id: int,
        amount: int,
        reason: str,
        *,
        now: str | None = None,
    ) -> tuple[int, int, int, int]:
        """Caller-owned atomic reserve primitive used by escrow-style domains.

        Wallet is consumed first, then bank. No commit is performed here.
        Returns ``(wallet_used, bank_used, new_wallet, new_bank)``.
        """
        amount = int(amount)
        if amount <= 0:
            raise ValueError("Az összegnek pozitívnak kell lennie.")
        await self.ensure_user_tx(db, guild_id, user_id)
        now = now or datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("A felhasználó nem található.")
        wallet, bank = int(row[0]), int(row[1])
        wallet_available = max(0, wallet)
        bank_available = max(0, bank)
        if wallet_available + bank_available < amount:
            raise ValueError("Nincs elég pénzed a tárcában és a bankban összesen.")
        wallet_used = min(wallet_available, amount)
        bank_used = amount - wallet_used
        new_wallet = wallet - wallet_used
        new_bank = bank - bank_used
        await db.execute(
            "UPDATE users SET wallet = ?, bank = ?, money_lost = money_lost + ? WHERE guild_id = ? AND user_id = ?",
            (new_wallet, new_bank, amount, guild_id, user_id),
        )
        await db.execute(
            """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
               VALUES (?, ?, 'economy.lost', ?, ?)
               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                   value = value + excluded.value, updated_at = excluded.updated_at""",
            (guild_id, user_id, amount, now),
        )
        await db.execute(
            "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, -amount, reason, now),
        )
        return wallet_used, bank_used, new_wallet, new_bank

    async def refund_wallet_and_bank_tx(
        self,
        db: aiosqlite.Connection,
        guild_id: int,
        user_id: int,
        wallet_amount: int,
        bank_amount: int,
        reason: str,
        *,
        now: str | None = None,
    ) -> tuple[int, int]:
        """Reverse a previous reserve into its original funding sources."""
        wallet_amount = max(0, int(wallet_amount))
        bank_amount = max(0, int(bank_amount))
        amount = wallet_amount + bank_amount
        if amount <= 0:
            raise ValueError("A visszatérítés összege pozitív legyen.")
        await self.ensure_user_tx(db, guild_id, user_id)
        now = now or datetime.now(timezone.utc).isoformat()
        await db.execute(
            """UPDATE users
               SET wallet = wallet + ?, bank = bank + ?,
                   money_lost = MAX(0, money_lost - ?)
               WHERE guild_id = ? AND user_id = ?""",
            (wallet_amount, bank_amount, amount, guild_id, user_id),
        )
        await db.execute(
            """UPDATE user_statistics
               SET value = MAX(0, value - ?), updated_at = ?
               WHERE guild_id = ? AND user_id = ? AND stat_name = 'economy.lost'""",
            (amount, now, guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, amount, reason, now),
        )
        cursor = await db.execute(
            "SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        return (int(row[0]), int(row[1])) if row else (wallet_amount, bank_amount)

    async def credit_wallet_tx(
        self,
        db: aiosqlite.Connection,
        guild_id: int,
        user_id: int,
        amount: int,
        reason: str,
        *,
        now: str | None = None,
    ) -> int:
        """Credit an authoritative payout inside the caller-owned transaction."""
        amount = int(amount)
        if amount <= 0:
            raise ValueError("A jóváírás összege pozitív legyen.")
        await self.ensure_user_tx(db, guild_id, user_id)
        now = now or datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE users SET wallet=wallet+?, money_earned=money_earned+? WHERE guild_id=? AND user_id=?",
            (amount, amount, guild_id, user_id),
        )
        await db.execute(
            """INSERT INTO user_statistics(guild_id,user_id,stat_name,value,updated_at)
               VALUES(?,?,'economy.earned',?,?)
               ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET
                   value=value+excluded.value,updated_at=excluded.updated_at""",
            (guild_id, user_id, amount, now),
        )
        cursor = await db.execute(
            "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        new_wallet = int(row[0]) if row else amount
        await db.execute(
            """INSERT INTO user_statistics (guild_id, user_id, stat_name, value, updated_at)
               VALUES (?, ?, 'economy.wallet_peak', ?, ?)
               ON CONFLICT(guild_id, user_id, stat_name) DO UPDATE SET
                   value = MAX(value, excluded.value), updated_at = excluded.updated_at""",
            (guild_id, user_id, new_wallet, now),
        )
        await db.execute(
            "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
            (guild_id, user_id, amount, reason, now),
        )
        return new_wallet

    async def get_balance(self, guild_id: int, user_id: int) -> tuple[int, int]:
        await self.ensure_user(guild_id, user_id)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT wallet, bank FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("A felhasználó létrehozása sikertelen volt.")
        return int(row[0]), int(row[1])
