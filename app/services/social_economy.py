from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
import math

import aiosqlite

from app.database import Database
from app.progression_math import progress_for_xp
from app import social_config as cfg
from app.services.gameplay_settings import GameplaySettingsService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: str) -> datetime:
    result = datetime.fromisoformat(str(value))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class MarketListing:
    id: int
    guild_id: int
    seller_id: int
    item_id: str
    item_name: str
    emoji: str
    quantity_remaining: int
    unit_price: int
    expires_at: datetime


@dataclass(slots=True)
class Duel:
    id: int
    guild_id: int
    challenger_id: int
    target_id: int
    game: str
    stake: int
    status: str
    challenger_choice: str | None
    target_choice: str | None
    expires_at: datetime
    channel_id: int | None
    message_id: int | None


class SocialEconomyService:
    """Persistent backend for Yoru v3.13 Social Economy.

    Money/item transfers that require escrow are done under BEGIN IMMEDIATE so
    concurrent button clicks cannot duplicate items or spend the same wallet.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.gameplay = GameplaySettingsService(db)

    async def initialize(self) -> None:
        # Database.initialize creates these tables too. Keep this idempotent so
        # the cog can safely self-heal if it is loaded against an older DB.
        statements = (
            """CREATE TABLE IF NOT EXISTS player_market_listings (id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,seller_id INTEGER NOT NULL,item_id TEXT NOT NULL,quantity_total INTEGER NOT NULL,quantity_remaining INTEGER NOT NULL,unit_price INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL,expires_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_player_market_active ON player_market_listings(guild_id,status,created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_player_market_seller ON player_market_listings(guild_id,seller_id,status)",
            """CREATE TABLE IF NOT EXISTS player_market_trades (id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,listing_id INTEGER NOT NULL,seller_id INTEGER NOT NULL,buyer_id INTEGER NOT NULL,item_id TEXT NOT NULL,quantity INTEGER NOT NULL,unit_price INTEGER NOT NULL,gross INTEGER NOT NULL,tax INTEGER NOT NULL,net INTEGER NOT NULL,created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_player_market_trades_guild ON player_market_trades(guild_id,created_at DESC)",
            """CREATE TABLE IF NOT EXISTS server_shop_items (id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',emoji TEXT NOT NULL DEFAULT '🎁',price INTEGER NOT NULL,reward_type TEXT NOT NULL,reward_ref TEXT NOT NULL,reward_quantity INTEGER NOT NULL DEFAULT 1,stock INTEGER NOT NULL DEFAULT -1,per_user_limit INTEGER NOT NULL DEFAULT 0,required_activity_level INTEGER NOT NULL DEFAULT 0,required_progression_level INTEGER NOT NULL DEFAULT 0,duration_minutes INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_server_shop_items_guild ON server_shop_items(guild_id,active,id)",
            """CREATE TABLE IF NOT EXISTS server_shop_purchases (id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,shop_item_id INTEGER NOT NULL,user_id INTEGER NOT NULL,price INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'paid',created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_server_shop_purchase_user ON server_shop_purchases(guild_id,shop_item_id,user_id,status)",
            """CREATE TABLE IF NOT EXISTS server_shop_claims (id INTEGER PRIMARY KEY AUTOINCREMENT,purchase_id INTEGER NOT NULL UNIQUE,guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,reward_text TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,fulfilled_at TEXT,fulfilled_by INTEGER)""",
            """CREATE TABLE IF NOT EXISTS temporary_role_grants (guild_id INTEGER NOT NULL,user_id INTEGER NOT NULL,role_id INTEGER NOT NULL,expires_at TEXT NOT NULL,source_purchase_id INTEGER NOT NULL,delete_on_expire INTEGER NOT NULL DEFAULT 0,PRIMARY KEY (guild_id,user_id,role_id,source_purchase_id))""",
            """CREATE TABLE IF NOT EXISTS pvp_duels (id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,challenger_id INTEGER NOT NULL,target_id INTEGER NOT NULL,game TEXT NOT NULL,stake INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',challenger_choice TEXT,target_choice TEXT,winner_id INTEGER,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,resolved_at TEXT,channel_id INTEGER,message_id INTEGER)""",
            "CREATE INDEX IF NOT EXISTS idx_pvp_duels_active ON pvp_duels(guild_id,status,expires_at)",
        )
        async with aiosqlite.connect(self.db.path) as conn:
            for statement in statements:
                await conn.execute(statement)
            cur = await conn.execute("PRAGMA table_info(temporary_role_grants)")
            columns = {str(row[1]) for row in await cur.fetchall()}
            if "delete_on_expire" not in columns:
                await conn.execute("ALTER TABLE temporary_role_grants ADD COLUMN delete_on_expire INTEGER NOT NULL DEFAULT 0")
            await conn.commit()

    # ---------- shared SQL helpers ----------

    async def _ensure_user_tx(self, conn: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
        now = _now().isoformat()
        starting_balance = await self.db.get_starting_balance(guild_id, conn)
        await conn.execute(
            "INSERT OR IGNORE INTO users (guild_id,user_id,wallet,bank,created_at) VALUES (?,?,?,0,?)",
            (guild_id, user_id, starting_balance, now),
        )

    async def _stat_add_tx(self, conn: aiosqlite.Connection, guild_id: int, user_id: int, name: str, value: int) -> None:
        now = _now().isoformat()
        await conn.execute(
            """INSERT INTO user_statistics(guild_id,user_id,stat_name,value,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET
                 value=value+excluded.value, updated_at=excluded.updated_at""",
            (guild_id, user_id, name, int(value), now),
        )

    async def _last_insert_id(self, conn: aiosqlite.Connection) -> int:
        cur = await conn.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---------- player marketplace ----------

    async def expire_market_listings(self, guild_id: int | None = None) -> int:
        now = _now()
        params: list[Any] = [now.isoformat()]
        where = "status='active' AND expires_at<=?"
        if guild_id is not None:
            where += " AND guild_id=?"
            params.append(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                f"SELECT id,guild_id,seller_id,item_id,quantity_remaining FROM player_market_listings WHERE {where}",
                tuple(params),
            )
            rows = await cur.fetchall()
            for listing_id, gid, seller_id, item_id, quantity in rows:
                quantity = int(quantity)
                if quantity > 0:
                    await conn.execute(
                        """INSERT INTO inventory(guild_id,user_id,item_id,quantity) VALUES(?,?,?,?)
                           ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                        (int(gid), int(seller_id), str(item_id), quantity),
                    )
                await conn.execute(
                    "UPDATE player_market_listings SET status='expired',quantity_remaining=0 WHERE id=? AND status='active'",
                    (int(listing_id),),
                )
            await conn.commit()
        return len(rows)

    async def create_listing(self, guild_id: int, seller_id: int, item_id: str, quantity: int, unit_price: int) -> int:
        item_id = item_id.strip().lower()
        quantity = int(quantity)
        unit_price = int(unit_price)
        runtime = await self.gameplay.social(guild_id)
        if quantity < 1 or quantity > runtime.market_max_quantity:
            raise ValueError(f"A mennyiség 1–{runtime.market_max_quantity} lehet.")
        if unit_price < runtime.market_min_unit_price:
            raise ValueError(f"A minimum egységár {runtime.market_min_unit_price:,}.".replace(",", " "))
        now = _now()
        expires = now + timedelta(hours=runtime.market_listing_hours)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON;")
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT COUNT(*) FROM player_market_listings WHERE guild_id=? AND seller_id=? AND status='active'",
                (guild_id, seller_id),
            )
            active = int((await cur.fetchone())[0])
            if active >= runtime.market_max_active_per_user:
                await conn.rollback()
                raise ValueError(f"Maximum {runtime.market_max_active_per_user} aktív listinged lehet.")
            cur = await conn.execute(
                "SELECT name,emoji,COALESCE(category,'utility') FROM shop_items WHERE item_id=? AND active=1",
                (item_id,),
            )
            item = await cur.fetchone()
            if item is None:
                await conn.rollback()
                raise ValueError("Nincs ilyen kereskedhető item.")
            if str(item[2]) == "reward":
                await conn.rollback()
                raise ValueError("Valódi/premium reward item nem tehető player marketre.")
            cur = await conn.execute(
                "SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_id=?",
                (guild_id, seller_id, item_id),
            )
            row = await cur.fetchone()
            owned = int(row[0]) if row else 0
            if owned < quantity:
                await conn.rollback()
                raise ValueError("Nincs ennyi ebből az itemből az inventorydban.")
            await conn.execute(
                "UPDATE inventory SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND item_id=?",
                (quantity, guild_id, seller_id, item_id),
            )
            cur = await conn.execute(
                """INSERT INTO player_market_listings
                   (guild_id,seller_id,item_id,quantity_total,quantity_remaining,unit_price,status,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,'active',?,?)""",
                (guild_id, seller_id, item_id, quantity, quantity, unit_price, now.isoformat(), expires.isoformat()),
            )
            listing_id = await self._last_insert_id(conn)
            await self._stat_add_tx(conn, guild_id, seller_id, "social.market.listings_created", 1)
            await conn.commit()
        return listing_id

    async def list_market(
        self, guild_id: int, *, seller_id: int | None = None, search: str | None = None,
        limit: int = cfg.PLAYER_MARKET_PAGE_SIZE, offset: int = 0,
    ) -> list[MarketListing]:
        await self.expire_market_listings(guild_id)
        query = (
            """SELECT l.id,l.guild_id,l.seller_id,l.item_id,s.name,s.emoji,l.quantity_remaining,l.unit_price,l.expires_at
               FROM player_market_listings l JOIN shop_items s ON s.item_id=l.item_id
               WHERE l.guild_id=? AND l.status='active' AND l.quantity_remaining>0"""
        )
        params: list[Any] = [guild_id]
        if seller_id is not None:
            query += " AND l.seller_id=?"
            params.append(seller_id)
        if search and search.strip():
            needle = f"%{search.strip().lower()}%"
            query += " AND (LOWER(l.item_id) LIKE ? OR LOWER(s.name) LIKE ?)"
            params.extend([needle, needle])
        query += " ORDER BY l.created_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(50, int(limit))), max(0, int(offset))])
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(query, tuple(params))
            rows = await cur.fetchall()
        return [
            MarketListing(int(r[0]), int(r[1]), int(r[2]), str(r[3]), str(r[4]), str(r[5]), int(r[6]), int(r[7]), _dt(str(r[8])))
            for r in rows
        ]

    async def buy_listing(self, guild_id: int, buyer_id: int, listing_id: int, quantity: int) -> dict[str, Any]:
        quantity = int(quantity)
        if quantity < 1:
            raise ValueError("A mennyiség legalább 1.")
        now = _now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON;")
            await conn.execute("BEGIN IMMEDIATE")
            await self._ensure_user_tx(conn, guild_id, buyer_id)
            cur = await conn.execute(
                """SELECT seller_id,item_id,quantity_remaining,unit_price,status,expires_at
                   FROM player_market_listings WHERE id=? AND guild_id=?""",
                (listing_id, guild_id),
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback(); raise ValueError("Nincs ilyen marketplace listing.")
            seller_id, item_id, remaining, unit_price, status, expires_at = int(row[0]), str(row[1]), int(row[2]), int(row[3]), str(row[4]), _dt(str(row[5]))
            if status != "active":
                await conn.rollback(); raise ValueError("Ez a listing már nem aktív.")
            if expires_at <= now:
                if remaining > 0:
                    await conn.execute(
                        """INSERT INTO inventory(guild_id,user_id,item_id,quantity) VALUES(?,?,?,?)
                           ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                        (guild_id, seller_id, item_id, remaining),
                    )
                await conn.execute("UPDATE player_market_listings SET status='expired',quantity_remaining=0 WHERE id=?", (listing_id,))
                await conn.commit(); raise ValueError("Ez a listing lejárt; az item visszakerült az eladóhoz.")
            if seller_id == buyer_id:
                await conn.rollback(); raise ValueError("A saját listingedet nem vásárolhatod meg.")
            if quantity > remaining:
                await conn.rollback(); raise ValueError(f"Csak {remaining} db maradt a listingben.")
            gross = unit_price * quantity
            runtime = await self.gameplay.social(guild_id)
            tax = max(1, int(gross * runtime.market_tax_rate)) if gross > 0 and runtime.market_tax_rate > 0 else 0
            net = gross - tax
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, buyer_id))
            buyer_wallet = int((await cur.fetchone())[0])
            if buyer_wallet < gross:
                await conn.rollback(); raise ValueError("Nincs elég pénzed ehhez a vásárláshoz.")
            await self._ensure_user_tx(conn, guild_id, seller_id)
            await conn.execute(
                "UPDATE users SET wallet=wallet-?, money_lost=money_lost+? WHERE guild_id=? AND user_id=?",
                (gross, gross, guild_id, buyer_id),
            )
            await conn.execute(
                "UPDATE users SET wallet=wallet+?, money_earned=money_earned+? WHERE guild_id=? AND user_id=?",
                (net, net, guild_id, seller_id),
            )
            await conn.execute(
                """INSERT INTO inventory(guild_id,user_id,item_id,quantity) VALUES(?,?,?,?)
                   ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                (guild_id, buyer_id, item_id, quantity),
            )
            new_remaining = remaining - quantity
            new_status = "sold" if new_remaining <= 0 else "active"
            await conn.execute(
                "UPDATE player_market_listings SET quantity_remaining=?,status=? WHERE id=?",
                (new_remaining, new_status, listing_id),
            )
            await conn.execute(
                "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
                (guild_id, buyer_id, -gross, f"player_market_buy:{listing_id}:{item_id}x{quantity}", now.isoformat()),
            )
            await conn.execute(
                "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
                (guild_id, seller_id, net, f"player_market_sale:{listing_id}:{item_id}x{quantity}", now.isoformat()),
            )
            await conn.execute(
                """INSERT INTO player_market_trades
                   (guild_id,listing_id,seller_id,buyer_id,item_id,quantity,unit_price,gross,tax,net,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (guild_id, listing_id, seller_id, buyer_id, item_id, quantity, unit_price, gross, tax, net, now.isoformat()),
            )
            await self._stat_add_tx(conn, guild_id, buyer_id, "social.market.purchases", 1)
            await self._stat_add_tx(conn, guild_id, buyer_id, "social.market.spent", gross)
            await self._stat_add_tx(conn, guild_id, seller_id, "social.market.sales", 1)
            await self._stat_add_tx(conn, guild_id, seller_id, "social.market.earned", net)
            await conn.commit()
        info = await self.db.get_shop_item(item_id)
        return {"listing_id": listing_id, "seller_id": seller_id, "item_id": item_id, "item_name": info[0] if info else item_id, "emoji": info[1] if info else "📦", "quantity": quantity, "gross": gross, "tax": tax, "net": net}

    async def cancel_listing(self, guild_id: int, seller_id: int, listing_id: int) -> int:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT item_id,quantity_remaining,status,seller_id FROM player_market_listings WHERE id=? AND guild_id=?",
                (listing_id, guild_id),
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback(); raise ValueError("Nincs ilyen listing.")
            item_id, remaining, status, owner = str(row[0]), int(row[1]), str(row[2]), int(row[3])
            if owner != seller_id:
                await conn.rollback(); raise ValueError("Csak a saját listingedet törölheted.")
            if status != "active":
                await conn.rollback(); raise ValueError("Ez a listing már nem aktív.")
            if remaining > 0:
                await conn.execute(
                    """INSERT INTO inventory(guild_id,user_id,item_id,quantity) VALUES(?,?,?,?)
                       ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                    (guild_id, seller_id, item_id, remaining),
                )
            await conn.execute(
                "UPDATE player_market_listings SET status='cancelled',quantity_remaining=0 WHERE id=?",
                (listing_id,),
            )
            await conn.commit()
        return remaining

    async def market_history(self, guild_id: int, user_id: int, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT id,listing_id,seller_id,buyer_id,item_id,quantity,unit_price,gross,tax,net,created_at
                   FROM player_market_trades WHERE guild_id=? AND (seller_id=? OR buyer_id=?)
                   ORDER BY id DESC LIMIT ? OFFSET ?""",
                (guild_id, user_id, user_id, max(1, min(30, int(limit))), max(0, int(offset))),
            )
            rows = await cur.fetchall()
        return [
            {"id": int(r[0]), "listing_id": int(r[1]), "seller_id": int(r[2]), "buyer_id": int(r[3]), "item_id": str(r[4]), "quantity": int(r[5]), "unit_price": int(r[6]), "gross": int(r[7]), "tax": int(r[8]), "net": int(r[9]), "created_at": _dt(str(r[10]))}
            for r in rows
        ]

    # ---------- custom server shop ----------

    async def create_server_shop_item(
        self, guild_id: int, *, name: str, description: str, emoji: str, price: int,
        reward_type: str, reward_ref: str, reward_quantity: int = 1, stock: int = -1,
        per_user_limit: int = 0, required_activity_level: int = 0,
        required_progression_level: int = 0, duration_minutes: int = 0,
    ) -> int:
        name = name.strip()[:cfg.SERVER_SHOP_MAX_NAME]
        description = description.strip()[:cfg.SERVER_SHOP_MAX_DESCRIPTION]
        emoji = (emoji.strip() or cfg.SERVER_SHOP_DEFAULT_EMOJI)[:16]
        reward_type = reward_type.strip().lower()
        reward_ref = reward_ref.strip()
        if not name:
            raise ValueError("A reward neve nem lehet üres.")
        if price <= 0:
            raise ValueError("Az árnak pozitívnak kell lennie.")
        if reward_type not in cfg.SERVER_SHOP_REWARD_TYPES:
            raise ValueError("Reward type: role, temporary_role, custom_role, temporary_custom_role, item vagy custom.")
        if reward_type in {"custom_role", "temporary_custom_role"}:
            reward_ref = "buyer_custom_role"
        elif not reward_ref:
            raise ValueError("A reward hivatkozás/szöveg nem lehet üres.")
        if reward_quantity < 1:
            raise ValueError("A reward quantity legalább 1.")
        if stock < -1 or stock > cfg.SERVER_SHOP_MAX_STOCK:
            raise ValueError("Stock: -1 (végtelen) vagy pozitív készlet.")
        if per_user_limit < 0 or per_user_limit > cfg.SERVER_SHOP_MAX_PER_USER:
            raise ValueError("A user limit nem lehet negatív.")
        if reward_type in {"temporary_role", "temporary_custom_role"} and not (1 <= duration_minutes <= cfg.SERVER_SHOP_MAX_TEMP_ROLE_MINUTES):
            raise ValueError("Ideiglenes role-nál adj meg érvényes duration_minutes értéket.")
        if reward_type not in {"temporary_role", "temporary_custom_role"}:
            duration_minutes = 0
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM server_shop_items WHERE guild_id=? AND active=1", (guild_id,))
            runtime = await self.gameplay.social(guild_id)
            if int((await cur.fetchone())[0]) >= runtime.server_shop_max_items:
                raise ValueError(f"Maximum {runtime.server_shop_max_items} aktív server shop reward lehet.")
            cur = await conn.execute(
                """INSERT INTO server_shop_items
                   (guild_id,name,description,emoji,price,reward_type,reward_ref,reward_quantity,stock,per_user_limit,
                    required_activity_level,required_progression_level,duration_minutes,active,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (guild_id, name, description, emoji, int(price), reward_type, reward_ref, int(reward_quantity), int(stock), int(per_user_limit), max(0,int(required_activity_level)), max(0,int(required_progression_level)), int(duration_minutes), _now().isoformat()),
            )
            item_id = await self._last_insert_id(conn)
            await conn.commit()
        return item_id

    async def list_server_shop(self, guild_id: int, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        query = "SELECT id,name,description,emoji,price,reward_type,reward_ref,reward_quantity,stock,per_user_limit,required_activity_level,required_progression_level,duration_minutes,active FROM server_shop_items WHERE guild_id=?"
        if not include_inactive:
            query += " AND active=1"
        query += " ORDER BY active DESC,id ASC LIMIT 100"
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(query, (guild_id,))
            rows = await cur.fetchall()
        keys = ("id","name","description","emoji","price","reward_type","reward_ref","reward_quantity","stock","per_user_limit","required_activity_level","required_progression_level","duration_minutes","active")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    @staticmethod
    def _validate_server_shop_values(
        *, name: str, description: str, emoji: str, price: int, reward_type: str, reward_ref: str,
        reward_quantity: int, stock: int, per_user_limit: int, required_activity_level: int,
        required_progression_level: int, duration_minutes: int,
    ) -> dict[str, Any]:
        name = str(name).strip()[:cfg.SERVER_SHOP_MAX_NAME]
        description = str(description).strip()[:cfg.SERVER_SHOP_MAX_DESCRIPTION]
        emoji = (str(emoji).strip() or cfg.SERVER_SHOP_DEFAULT_EMOJI)[:16]
        reward_type = str(reward_type).strip().lower()
        reward_ref = str(reward_ref).strip()
        price = int(price); reward_quantity = int(reward_quantity); stock = int(stock); per_user_limit = int(per_user_limit)
        required_activity_level = max(0, int(required_activity_level)); required_progression_level = max(0, int(required_progression_level))
        duration_minutes = int(duration_minutes)
        if not name: raise ValueError("A reward neve nem lehet üres.")
        if price <= 0: raise ValueError("Az árnak pozitívnak kell lennie.")
        if reward_type not in cfg.SERVER_SHOP_REWARD_TYPES: raise ValueError("Reward type: role, temporary_role, custom_role, temporary_custom_role, item vagy custom.")
        if reward_type in {"custom_role", "temporary_custom_role"}:
            reward_ref = "buyer_custom_role"
        elif not reward_ref:
            raise ValueError("A reward hivatkozás/szöveg nem lehet üres.")
        if reward_quantity < 1: raise ValueError("A reward quantity legalább 1.")
        if stock < -1 or stock > cfg.SERVER_SHOP_MAX_STOCK: raise ValueError("Stock: -1 (végtelen) vagy 0+ készlet.")
        if per_user_limit < 0 or per_user_limit > cfg.SERVER_SHOP_MAX_PER_USER: raise ValueError("A user limit nem lehet negatív.")
        if reward_type in {"temporary_role", "temporary_custom_role"}:
            if not (1 <= duration_minutes <= cfg.SERVER_SHOP_MAX_TEMP_ROLE_MINUTES):
                raise ValueError("Ideiglenes role-nál adj meg érvényes duration_minutes értéket.")
        else:
            duration_minutes = 0
        return {
            "name": name, "description": description, "emoji": emoji, "price": price, "reward_type": reward_type,
            "reward_ref": reward_ref, "reward_quantity": reward_quantity, "stock": stock, "per_user_limit": per_user_limit,
            "required_activity_level": required_activity_level, "required_progression_level": required_progression_level,
            "duration_minutes": duration_minutes,
        }

    async def update_server_shop_item(self, guild_id: int, item_id: int, **changes: Any) -> dict[str, Any]:
        current = await self.get_server_shop_item(guild_id, item_id)
        if current is None:
            raise ValueError("Nincs ilyen Server Shop reward.")
        fields = {
            key: changes.get(key, current[key])
            for key in (
                "name", "description", "emoji", "price", "reward_type", "reward_ref", "reward_quantity",
                "stock", "per_user_limit", "required_activity_level", "required_progression_level", "duration_minutes",
            )
        }
        fields = self._validate_server_shop_values(**fields)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """UPDATE server_shop_items SET name=?,description=?,emoji=?,price=?,reward_type=?,reward_ref=?,reward_quantity=?,
                   stock=?,per_user_limit=?,required_activity_level=?,required_progression_level=?,duration_minutes=?
                   WHERE guild_id=? AND id=?""",
                (fields["name"], fields["description"], fields["emoji"], fields["price"], fields["reward_type"], fields["reward_ref"],
                 fields["reward_quantity"], fields["stock"], fields["per_user_limit"], fields["required_activity_level"],
                 fields["required_progression_level"], fields["duration_minutes"], guild_id, item_id),
            )
            await conn.commit()
        result = await self.get_server_shop_item(guild_id, item_id)
        if result is None:
            raise ValueError("A reward frissítése után nem található.")
        return result

    async def set_server_shop_item_active(self, guild_id: int, item_id: int, active: bool) -> bool:
        item = await self.get_server_shop_item(guild_id, item_id)
        if item is None:
            return False
        if active and not int(item["active"]):
            async with aiosqlite.connect(self.db.path) as conn:
                cur = await conn.execute("SELECT COUNT(*) FROM server_shop_items WHERE guild_id=? AND active=1", (guild_id,))
                runtime = await self.gameplay.social(guild_id)
                if int((await cur.fetchone())[0]) >= runtime.server_shop_max_items:
                    raise ValueError(f"Maximum {runtime.server_shop_max_items} aktív server shop reward lehet.")
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("UPDATE server_shop_items SET active=? WHERE guild_id=? AND id=?", (1 if active else 0, guild_id, item_id))
            await conn.commit()
            return bool(cur.rowcount)

    async def server_shop_purchase_count(self, guild_id: int, item_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM server_shop_purchases WHERE guild_id=? AND shop_item_id=? AND user_id=? AND status IN ('paid','delivered','claimed')",
                (guild_id, item_id, user_id),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def disable_server_shop_item(self, guild_id: int, item_id: int) -> bool:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("UPDATE server_shop_items SET active=0 WHERE guild_id=? AND id=? AND active=1", (guild_id, item_id))
            await conn.commit()
            return bool(cur.rowcount)

    async def get_server_shop_item(self, guild_id: int, item_id: int) -> dict[str, Any] | None:
        rows = await self.list_server_shop(guild_id, include_inactive=True)
        return next((row for row in rows if int(row["id"]) == int(item_id)), None)

    async def begin_server_shop_purchase(self, guild_id: int, user_id: int, item_id: int) -> dict[str, Any]:
        now = _now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await self._ensure_user_tx(conn, guild_id, user_id)
            cur = await conn.execute(
                """SELECT name,description,emoji,price,reward_type,reward_ref,reward_quantity,stock,per_user_limit,
                          required_activity_level,required_progression_level,duration_minutes,active
                   FROM server_shop_items WHERE guild_id=? AND id=?""",
                (guild_id, item_id),
            )
            row = await cur.fetchone()
            if row is None or int(row[12]) != 1:
                await conn.rollback(); raise ValueError("Nincs ilyen aktív server shop reward.")
            name, description, emoji, price, reward_type, reward_ref, reward_quantity, stock, per_limit, req_activity, req_progression, duration, _active = row
            price, stock, per_limit = int(price), int(stock), int(per_limit)
            if stock == 0:
                await conn.rollback(); raise ValueError("Ez a reward elfogyott.")
            if per_limit > 0:
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM server_shop_purchases WHERE guild_id=? AND shop_item_id=? AND user_id=? AND status IN ('paid','delivered','claimed')",
                    (guild_id, item_id, user_id),
                )
                bought = int((await cur.fetchone())[0])
                if bought >= per_limit:
                    await conn.rollback(); raise ValueError("Elérted ennek a rewardnak a személyes vásárlási limitjét.")
            cur = await conn.execute("SELECT level FROM activity_users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            ar = await cur.fetchone(); activity_level = int(ar[0]) if ar else 0
            if activity_level < int(req_activity):
                await conn.rollback(); raise ValueError(f"Ehhez legalább Activity Level {int(req_activity)} kell.")
            cur = await conn.execute("SELECT wallet,xp_points FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            ur = await cur.fetchone(); wallet, xp_points = int(ur[0]), int(ur[1])
            progression_level = int(progress_for_xp(xp_points)[0])
            if progression_level < int(req_progression):
                await conn.rollback(); raise ValueError(f"Ehhez legalább Yoru Level {int(req_progression)} kell.")
            if wallet < price:
                await conn.rollback(); raise ValueError("Nincs elég pénzed ehhez a rewardhoz.")
            await conn.execute(
                "UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?",
                (price, price, guild_id, user_id),
            )
            if stock > 0:
                await conn.execute("UPDATE server_shop_items SET stock=stock-1 WHERE guild_id=? AND id=?", (guild_id, item_id))
            cur = await conn.execute(
                "INSERT INTO server_shop_purchases(guild_id,shop_item_id,user_id,price,status,created_at) VALUES(?,?,?,?, 'paid', ?)",
                (guild_id, item_id, user_id, price, now.isoformat()),
            )
            purchase_id = await self._last_insert_id(conn)
            await conn.execute(
                "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
                (guild_id, user_id, -price, f"server_shop_buy:{item_id}:purchase_{purchase_id}", now.isoformat()),
            )
            await self._stat_add_tx(conn, guild_id, user_id, "social.server_shop.purchases", 1)
            await self._stat_add_tx(conn, guild_id, user_id, "social.server_shop.spent", price)
            claim_id = None
            if str(reward_type) == "custom":
                cur = await conn.execute(
                    "INSERT INTO server_shop_claims(purchase_id,guild_id,user_id,reward_text,status,created_at) VALUES(?,?,?,?, 'pending', ?)",
                    (purchase_id, guild_id, user_id, str(reward_ref), now.isoformat()),
                )
                claim_id = await self._last_insert_id(conn)
            await conn.commit()
        return {
            "purchase_id": purchase_id, "claim_id": claim_id, "shop_item_id": item_id,
            "name": str(name), "description": str(description), "emoji": str(emoji), "price": price,
            "reward_type": str(reward_type), "reward_ref": str(reward_ref), "reward_quantity": int(reward_quantity),
            "duration_minutes": int(duration),
        }

    async def complete_server_shop_purchase(self, purchase_id: int, *, status: str = "delivered") -> None:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("UPDATE server_shop_purchases SET status=? WHERE id=? AND status='paid'", (status, purchase_id))
            await conn.commit()

    async def refund_server_shop_purchase(self, purchase_id: int) -> bool:
        now = _now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                """SELECT p.guild_id,p.user_id,p.price,p.shop_item_id,p.status,i.stock
                   FROM server_shop_purchases p JOIN server_shop_items i ON i.id=p.shop_item_id
                   WHERE p.id=?""", (purchase_id,))
            row = await cur.fetchone()
            if row is None or str(row[4]) not in {"paid", "claimed"}:
                await conn.rollback(); return False
            guild_id, user_id, price, shop_item_id, _status, stock = int(row[0]), int(row[1]), int(row[2]), int(row[3]), str(row[4]), int(row[5])
            await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?", (price, price, guild_id, user_id))
            if stock >= 0:
                await conn.execute("UPDATE server_shop_items SET stock=stock+1 WHERE id=?", (shop_item_id,))
            await conn.execute("UPDATE server_shop_purchases SET status='refunded' WHERE id=?", (purchase_id,))
            await conn.execute("DELETE FROM server_shop_claims WHERE purchase_id=? AND status='pending'", (purchase_id,))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id,user_id,price,f"server_shop_refund:{purchase_id}",now))
            await conn.commit()
        return True

    async def add_temporary_role_grant(
        self, guild_id: int, user_id: int, role_id: int, purchase_id: int, duration_minutes: int,
        *, delete_on_expire: bool = False,
    ) -> datetime:
        expires = _now() + timedelta(minutes=max(1, duration_minutes))
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO temporary_role_grants
                   (guild_id,user_id,role_id,expires_at,source_purchase_id,delete_on_expire) VALUES(?,?,?,?,?,?)""",
                (guild_id,user_id,role_id,expires.isoformat(),purchase_id,1 if delete_on_expire else 0),
            )
            await conn.commit()
        return expires

    async def expired_temporary_roles(self) -> list[tuple[int,int,int,int,bool]]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT guild_id,user_id,role_id,source_purchase_id,delete_on_expire FROM temporary_role_grants WHERE expires_at<=?",
                (_now().isoformat(),),
            )
            return [(int(a),int(b),int(c),int(d),bool(e)) for a,b,c,d,e in await cur.fetchall()]

    async def delete_temporary_role_grant(self, guild_id: int, user_id: int, role_id: int, purchase_id: int) -> None:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("DELETE FROM temporary_role_grants WHERE guild_id=? AND user_id=? AND role_id=? AND source_purchase_id=?", (guild_id,user_id,role_id,purchase_id))
            await conn.commit()

    async def list_pending_claims(self, guild_id: int, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT id,purchase_id,user_id,reward_text,created_at FROM server_shop_claims WHERE guild_id=? AND status='pending' ORDER BY id ASC LIMIT ? OFFSET ?",
                (guild_id, max(1,min(50,int(limit))), max(0,int(offset))),
            )
            rows = await cur.fetchall()
        return [{"id":int(r[0]),"purchase_id":int(r[1]),"user_id":int(r[2]),"reward_text":str(r[3]),"created_at":_dt(str(r[4]))} for r in rows]

    async def fulfill_claim(self, guild_id: int, claim_id: int, admin_id: int) -> bool:
        now = _now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT purchase_id FROM server_shop_claims WHERE guild_id=? AND id=? AND status='pending'", (guild_id,claim_id))
            row = await cur.fetchone()
            if row is None:
                await conn.rollback(); return False
            purchase_id = int(row[0])
            await conn.execute("UPDATE server_shop_claims SET status='fulfilled',fulfilled_at=?,fulfilled_by=? WHERE id=?", (now,admin_id,claim_id))
            await conn.execute("UPDATE server_shop_purchases SET status='delivered' WHERE id=?", (purchase_id,))
            await conn.commit()
        return True

    # ---------- PvP duels ----------

    async def create_duel(self, guild_id: int, challenger_id: int, target_id: int, game: str, stake: int, channel_id: int | None) -> Duel:
        game = game.lower().strip()
        stake = int(stake)
        if challenger_id == target_id:
            raise ValueError("Magadat nem hívhatod ki duelre.")
        if game not in cfg.PVP_GAMES:
            raise ValueError("Játék: coinflip, dice vagy rps.")
        runtime = await self.gameplay.social(guild_id)
        if stake < runtime.pvp_min_stake:
            raise ValueError(f"A minimum tét {runtime.pvp_min_stake:,}.".replace(",", " "))
        await self.db.ensure_user(guild_id, challenger_id)
        wallet, _ = await self.db.get_balance(guild_id, challenger_id)
        if wallet < stake:
            raise ValueError("Nincs elég pénzed ehhez a tétethez.")
        now = _now(); expires = now + timedelta(seconds=runtime.pvp_challenge_seconds)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            # Cross-system guard: a player cannot enter a PvP duel while an
            # unfinished house Casino session exists. This shares the same DB
            # write lock as Casino reservations, so simultaneous starts cannot
            # race past each other.
            cur = await conn.execute(
                """SELECT user_id FROM casino_sessions
                   WHERE guild_id=? AND user_id IN (?,?)
                     AND status IN ('ACTIVE','WAITING_INPUT','SETTLING')
                   LIMIT 1""",
                (guild_id, challenger_id, target_id),
            )
            if await cur.fetchone() is not None:
                await conn.rollback()
                raise ValueError("Valamelyik játékosnak már fut egy Casino játéka.")
            cur = await conn.execute(
                "SELECT COUNT(*) FROM pvp_duels WHERE guild_id=? AND status IN ('pending','accepted') AND (challenger_id IN (?,?) OR target_id IN (?,?))",
                (guild_id,challenger_id,target_id,challenger_id,target_id),
            )
            if int((await cur.fetchone())[0]) > 0:
                raise ValueError("Valamelyik játékosnak már van aktív duelje.")
            cur = await conn.execute(
                """INSERT INTO pvp_duels(guild_id,challenger_id,target_id,game,stake,status,created_at,expires_at,channel_id)
                   VALUES(?,?,?,?,?,'pending',?,?,?)""",
                (guild_id,challenger_id,target_id,game,stake,now.isoformat(),expires.isoformat(),channel_id),
            )
            duel_id = await self._last_insert_id(conn)
            await conn.commit()
        return Duel(duel_id,guild_id,challenger_id,target_id,game,stake,"pending",None,None,expires,channel_id,None)

    async def set_duel_message(self, duel_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("UPDATE pvp_duels SET message_id=? WHERE id=?", (message_id,duel_id)); await conn.commit()

    async def get_duel(self, duel_id: int) -> Duel | None:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT id,guild_id,challenger_id,target_id,game,stake,status,challenger_choice,target_choice,expires_at,channel_id,message_id FROM pvp_duels WHERE id=?",
                (duel_id,),
            ); r = await cur.fetchone()
        if r is None: return None
        return Duel(int(r[0]),int(r[1]),int(r[2]),int(r[3]),str(r[4]),int(r[5]),str(r[6]),str(r[7]) if r[7] else None,str(r[8]) if r[8] else None,_dt(str(r[9])),int(r[10]) if r[10] is not None else None,int(r[11]) if r[11] is not None else None)

    async def accept_duel(self, duel_id: int, target_id: int) -> Duel:
        now = _now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT guild_id,challenger_id,target_id,game,stake,status,expires_at,channel_id,message_id FROM pvp_duels WHERE id=?", (duel_id,))
            r = await cur.fetchone()
            if r is None: await conn.rollback(); raise ValueError("A duel már nem létezik.")
            guild_id, challenger, target, game, stake, status, expires = int(r[0]),int(r[1]),int(r[2]),str(r[3]),int(r[4]),str(r[5]),_dt(str(r[6]))
            if target != target_id: await conn.rollback(); raise ValueError("Ezt a duelt csak a kihívott játékos fogadhatja el.")
            if status != "pending" or expires <= now: await conn.rollback(); raise ValueError("A duel már nem fogadható el.")
            active = await conn.execute(
                """SELECT user_id FROM casino_sessions
                   WHERE guild_id=? AND user_id IN (?,?)
                     AND status IN ('ACTIVE','WAITING_INPUT','SETTLING')
                   LIMIT 1""",
                (guild_id, challenger, target),
            )
            if await active.fetchone() is not None:
                await conn.rollback()
                raise ValueError("Valamelyik játékosnak már fut egy Casino játéka.")
            await self._ensure_user_tx(conn,guild_id,challenger); await self._ensure_user_tx(conn,guild_id,target)
            cur = await conn.execute("SELECT user_id,wallet FROM users WHERE guild_id=? AND user_id IN (?,?)", (guild_id,challenger,target))
            balances = {int(uid):int(wallet) for uid,wallet in await cur.fetchall()}
            if balances.get(challenger,0) < stake: await conn.rollback(); raise ValueError("A kihívónak már nincs meg a tét.")
            if balances.get(target,0) < stake: await conn.rollback(); raise ValueError("Nincs elég pénzed a duel elfogadásához.")
            for uid in (challenger,target):
                await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (stake,stake,guild_id,uid))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id,uid,-stake,f"pvp_escrow:{duel_id}:{game}",now.isoformat()))
                await self._stat_add_tx(conn,guild_id,uid,"social.pvp.wagered",stake)
            runtime = await self.gameplay.social(guild_id)
            rps_expires = now + timedelta(seconds=runtime.pvp_rps_seconds)
            await conn.execute("UPDATE pvp_duels SET status='accepted',expires_at=? WHERE id=?", (rps_expires.isoformat(),duel_id))
            await conn.commit()
        return Duel(duel_id,guild_id,challenger,target,game,stake,"accepted",None,None,rps_expires,int(r[7]) if r[7] is not None else None,int(r[8]) if r[8] is not None else None)

    async def decline_duel(self, duel_id: int, target_id: int) -> bool:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("UPDATE pvp_duels SET status='declined',resolved_at=? WHERE id=? AND target_id=? AND status='pending'", (_now().isoformat(),duel_id,target_id)); await conn.commit(); return bool(cur.rowcount)

    async def choose_rps(self, duel_id: int, user_id: int, choice: str) -> Duel:
        choice = choice.lower(); aliases = {"rock":"rock","paper":"paper","scissors":"scissors"}
        if choice not in aliases: raise ValueError("Érvénytelen RPS választás.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT challenger_id,target_id,status FROM pvp_duels WHERE id=?",(duel_id,)); row=await cur.fetchone()
            if row is None or str(row[2])!="accepted": await conn.rollback(); raise ValueError("Ez a duel már nem aktív.")
            challenger,target=int(row[0]),int(row[1])
            if user_id==challenger: field="challenger_choice"
            elif user_id==target: field="target_choice"
            else: await conn.rollback(); raise ValueError("Nem vagy résztvevő ebben a duelben.")
            cur=await conn.execute(f"SELECT {field} FROM pvp_duels WHERE id=?",(duel_id,)); existing=await cur.fetchone()
            if existing and existing[0]: await conn.rollback(); raise ValueError("Már választottál.")
            await conn.execute(f"UPDATE pvp_duels SET {field}=? WHERE id=?",(choice,duel_id)); await conn.commit()
        duel=await self.get_duel(duel_id)
        if duel is None: raise ValueError("A duel eltűnt.")
        return duel

    async def settle_duel(self, duel_id: int, winner_id: int | None) -> dict[str, Any]:
        now=_now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT guild_id,challenger_id,target_id,game,stake,status FROM pvp_duels WHERE id=?",(duel_id,)); row=await cur.fetchone()
            if row is None: await conn.rollback(); raise ValueError("Nincs ilyen duel.")
            guild_id,challenger,target,game,stake,status=int(row[0]),int(row[1]),int(row[2]),str(row[3]),int(row[4]),str(row[5])
            if status!="accepted": await conn.rollback(); raise ValueError("Ez a duel már le van zárva.")
            if winner_id is not None and winner_id not in {challenger,target}: await conn.rollback(); raise ValueError("Érvénytelen winner.")
            if winner_id is None:
                for uid in (challenger,target):
                    await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(stake,stake,guild_id,uid))
                    await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(guild_id,uid,stake,f"pvp_tie_refund:{duel_id}:{game}",now.isoformat()))
                    await self._stat_add_tx(conn,guild_id,uid,"social.pvp.ties",1)
                result_status="tied"
            else:
                pot=stake*2
                loser=target if winner_id==challenger else challenger
                await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(pot,pot,guild_id,winner_id))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(guild_id,winner_id,pot,f"pvp_win:{duel_id}:{game}",now.isoformat()))
                await self._stat_add_tx(conn,guild_id,winner_id,"social.pvp.wins",1)
                await self._stat_add_tx(conn,guild_id,loser,"social.pvp.losses",1)
                await self._stat_add_tx(conn,guild_id,winner_id,"social.pvp.profit",stake)
                await self._stat_add_tx(conn,guild_id,loser,"social.pvp.profit",-stake)
                result_status="resolved"
            for uid in (challenger,target): await self._stat_add_tx(conn,guild_id,uid,"social.pvp.duels",1)
            await conn.execute("UPDATE pvp_duels SET status=?,winner_id=?,resolved_at=? WHERE id=?",(result_status,winner_id,now.isoformat(),duel_id)); await conn.commit()
        return {"duel_id":duel_id,"guild_id":guild_id,"challenger_id":challenger,"target_id":target,"game":game,"stake":stake,"winner_id":winner_id,"status":result_status}

    async def cleanup_duels(self) -> int:
        """Expire pending duels and refund accepted escrow after timeout/restart."""
        now=_now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT id,guild_id,challenger_id,target_id,game,stake,status FROM pvp_duels WHERE status IN ('pending','accepted') AND expires_at<=?",(now.isoformat(),)); rows=await cur.fetchall()
            for duel_id,guild_id,challenger,target,game,stake,status in rows:
                if str(status)=="accepted":
                    for uid in (int(challenger),int(target)):
                        await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(int(stake),int(stake),int(guild_id),uid))
                        await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(int(guild_id),uid,int(stake),f"pvp_timeout_refund:{int(duel_id)}:{str(game)}",now.isoformat()))
                await conn.execute("UPDATE pvp_duels SET status='expired',resolved_at=? WHERE id=?",(now.isoformat(),int(duel_id)))
            await conn.commit()
        return len(rows)

    async def refund_all_accepted_duels(self) -> int:
        """Startup safety: accepted RPS escrow from a dead process is always returned."""
        async with aiosqlite.connect(self.db.path) as conn:
            cur=await conn.execute("SELECT id FROM pvp_duels WHERE status='accepted'"); ids=[int(r[0]) for r in await cur.fetchall()]
        if not ids: return 0
        # Make them immediately eligible for the normal atomic cleanup path.
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.executemany("UPDATE pvp_duels SET expires_at=? WHERE id=?",[(_now().isoformat(),i) for i in ids]); await conn.commit()
        await self.cleanup_duels()
        return len(ids)

    async def duel_stats(self, guild_id: int, user_id: int) -> dict[str,int]:
        names=("social.pvp.duels","social.pvp.wins","social.pvp.losses","social.pvp.ties","social.pvp.wagered","social.pvp.profit")
        result={n:0 for n in names}
        async with aiosqlite.connect(self.db.path) as conn:
            q=','.join('?' for _ in names)
            cur=await conn.execute(f"SELECT stat_name,value FROM user_statistics WHERE guild_id=? AND user_id=? AND stat_name IN ({q})",(guild_id,user_id,*names))
            for name,value in await cur.fetchall(): result[str(name)]=int(value)
        return result

    # ---------- economy analytics ----------

    @staticmethod
    def _reason_bucket(reason: str) -> str:
        r=reason.lower()
        if r.startswith("business_"): return "Biznisz Empire"
        if r.startswith("heist_"): return "Nagy Meló"
        if r.startswith("player_market_"): return "Player Market"
        if r.startswith("server_shop_"): return "Server Shop"
        if r.startswith("pvp_"): return "PvP Duel"
        if r.startswith(("buy:","sell:")): return "Shop"
        if r.startswith("market_"): return "Napi piac"
        if r.startswith(("gamble:","gamble_reserve:","gamble_payout:","blackjack","roulette","coinflip","dice","slots","highlow","rps","chicken","gambling")): return "Gambling"
        if r.startswith(("work:","crime:","search:","beg:","daily","weekly","monthly","interest","role_income")): return "Economy jutalmak"
        if r.startswith(("pay_to:","pay_from:")): return "Player transfer"
        if r.startswith(("jackpot","lottery")): return "Community gambling"
        return "Egyéb"

    async def analytics(self, guild_id: int, hours: int = 24) -> dict[str,Any]:
        hours=max(1,min(24*30,int(hours))); since=_now()-timedelta(hours=hours)
        async with aiosqlite.connect(self.db.path) as conn:
            cur=await conn.execute("SELECT user_id,wallet,bank FROM users WHERE guild_id=?",(guild_id,)); users=await cur.fetchall()
            cur=await conn.execute("SELECT amount,reason FROM transactions WHERE guild_id=? AND created_at>=?",(guild_id,since.isoformat())); tx=await cur.fetchall()
            cur=await conn.execute("SELECT COALESCE(SUM(gross),0),COUNT(*) FROM player_market_trades WHERE guild_id=? AND created_at>=?",(guild_id,since.isoformat())); market_row=await cur.fetchone()
            cur=await conn.execute("SELECT COALESCE(SUM(stake*2),0),COUNT(*) FROM pvp_duels WHERE guild_id=? AND status IN ('resolved','tied') AND resolved_at>=?",(guild_id,since.isoformat())); duel_row=await cur.fetchone()
        wallet_total=sum(int(r[1]) for r in users); bank_total=sum(int(r[2]) for r in users); supply=wallet_total+bank_total
        wealth=sorted((int(r[1])+int(r[2]) for r in users),reverse=True); count=len(wealth)
        top1_share=(wealth[0]/supply*100) if wealth and supply>0 else 0.0
        top_n=max(1,math.ceil(count*0.10)) if count else 0
        top10_share=(sum(wealth[:top_n])/supply*100) if top_n and supply>0 else 0.0
        credits=sum(int(a) for a,_ in tx if int(a)>0); debits=sum(-int(a) for a,_ in tx if int(a)<0); net=sum(int(a) for a,_ in tx)
        buckets:dict[str,int]={}
        for amount,reason in tx:
            key=self._reason_bucket(str(reason)); buckets[key]=buckets.get(key,0)+int(amount)
        return {"hours":hours,"users":count,"wallet_total":wallet_total,"bank_total":bank_total,"supply":supply,"credits":credits,"debits":debits,"net":net,"created":max(net,0),"burned":max(-net,0),"top1_share":top1_share,"top10_share":top10_share,"market_volume":int(market_row[0] or 0),"market_trades":int(market_row[1] or 0),"duel_volume":int(duel_row[0] or 0),"duels":int(duel_row[1] or 0),"buckets":dict(sorted(buckets.items(),key=lambda kv:abs(kv[1]),reverse=True))}
