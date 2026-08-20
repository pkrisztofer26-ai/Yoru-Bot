from __future__ import annotations
from app.services.housing_projection_support import *

class HousingServiceMixin1:
        def __init__(
            self, database: Database, characters: CharacterService, memory_adapters: MemoryAdapterService | None = None
        ) -> None:
            self.database = database
            self.characters = characters
            self.memory_adapters = memory_adapters

        @staticmethod
        def _state_from_row(row: Any) -> HousingState:
            return HousingState(
                guild_id=int(row[0]),
                user_id=int(row[1]),
                tier_key=str(row[2]),
                city_key=str(row[3]),
                acquired_at=str(row[4]) if row[4] is not None else None,
                paid_until=str(row[5]) if row[5] is not None else None,
                grace_until=str(row[6]) if row[6] is not None else None,
                updated_at=str(row[7]) if row[7] is not None else None,
            )

        @staticmethod
        def _property_from_row(row: Any) -> HousingProperty:
            return HousingProperty(
                property_id=int(row[0]),
                guild_id=int(row[1]),
                user_id=int(row[2]),
                city_key=str(row[3]),
                tier_key=str(row[4]),
                purchase_price=int(row[5]),
                maintenance_paid_until=str(row[6]),
                maintenance_grace_until=str(row[7]) if row[7] is not None else None,
                maintenance_debt=int(row[8] or 0),
                last_opportunity_cycle=str(row[9]) if row[9] is not None else None,
                status=str(row[10]),
                acquired_at=str(row[11]),
                upgraded_at=str(row[12]) if row[12] is not None else None,
                updated_at=str(row[13]),
                sold_at=str(row[14]) if row[14] is not None else None,
                sale_price=int(row[15]) if row[15] is not None else None,
            )

        @staticmethod
        def _property_select_sql() -> str:
            return (
                "SELECT property_id,guild_id,user_id,city_key,tier_key,purchase_price,"
                "maintenance_paid_until,maintenance_grace_until,maintenance_debt,last_opportunity_cycle,"
                "status,acquired_at,upgraded_at,updated_at,sold_at,sale_price FROM housing_properties"
            )

        async def get(self, guild_id: int, user_id: int) -> HousingState:
            character = await self.characters.require(guild_id, user_id)
            async with aiosqlite.connect(self.database.path) as db:
                cursor = await db.execute(
                    """SELECT guild_id,user_id,tier_key,city_key,acquired_at,paid_until,grace_until,updated_at
                       FROM housing_state WHERE guild_id=? AND user_id=?""",
                    (guild_id, user_id),
                )
                row = await cursor.fetchone()
            if row is not None:
                return self._state_from_row(row)
            return HousingState(
                guild_id=int(guild_id),
                user_id=int(user_id),
                tier_key="street",
                city_key=character.home_city_key,
                acquired_at=None,
                paid_until=None,
                grace_until=None,
                updated_at=None,
            )

        async def properties(self, guild_id: int, user_id: int) -> list[HousingProperty]:
            await self.characters.require(guild_id, user_id)
            async with aiosqlite.connect(self.database.path) as db:
                cursor = await db.execute(
                    self._property_select_sql()
                    + " WHERE guild_id=? AND user_id=? AND status='owned' ORDER BY acquired_at,property_id",
                    (guild_id, user_id),
                )
                rows = await cursor.fetchall()
            return [self._property_from_row(row) for row in rows]

        async def get_property(self, guild_id: int, user_id: int, property_id: int) -> HousingProperty | None:
            async with aiosqlite.connect(self.database.path) as db:
                cursor = await db.execute(
                    self._property_select_sql()
                    + " WHERE guild_id=? AND user_id=? AND property_id=? AND status='owned'",
                    (guild_id, user_id, int(property_id)),
                )
                row = await cursor.fetchone()
            return self._property_from_row(row) if row is not None else None

        async def property_in_city(self, guild_id: int, user_id: int, city_key: str) -> HousingProperty | None:
            async with aiosqlite.connect(self.database.path) as db:
                cursor = await db.execute(
                    self._property_select_sql()
                    + " WHERE guild_id=? AND user_id=? AND city_key=? AND status='owned' ORDER BY property_id DESC LIMIT 1",
                    (guild_id, user_id, str(city_key)),
                )
                row = await cursor.fetchone()
            return self._property_from_row(row) if row is not None else None

        async def active_property(self, guild_id: int, user_id: int) -> HousingProperty | None:
            state = await self.get(guild_id, user_id)
            if state.tier_key not in cfg.PROPERTY_TIERS:
                return None
            prop = await self.property_in_city(guild_id, user_id, state.city_key)
            if prop is None or prop.tier_key != state.tier_key:
                return None
            return prop

        async def _record_first_milestone(self, guild_id: int, user_id: int, tier_key: str, city_key: str) -> None:
            city_name = character_cfg.city_name(city_key)
            milestone = {
                "shelter": (
                    "first_shelter", "Első biztos lakhatás",
                    f"Először kerültél le az utcáról: szállót szereztél {city_name} városában.",
                ),
                "rental": (
                    "first_rental", "Első albérlet",
                    f"Beköltöztél az első saját albérletedbe {city_name} városában.",
                ),
                "owned": (
                    "first_owned_home", "Első saját lakás",
                    f"Megvetted az első saját lakásodat {city_name} városában.",
                ),
                "premium": (
                    "first_premium_home", "Prémium ingatlan",
                    f"Prémium ingatlanná fejlesztetted az otthonodat {city_name} városában.",
                ),
            }.get(str(tier_key))
            if milestone is None:
                return
            event_key, title, description = milestone
            if await self.characters.has_history_event(guild_id, user_id, event_key):
                return
            try:
                await self.characters.add_history(
                    guild_id,
                    user_id,
                    event_key=event_key,
                    title=title,
                    description=description,
                    metadata={"housing_tier": tier_key, "city": city_key},
                )
            except Exception:
                logger.exception("Housing milestone write failed guild=%s user=%s tier=%s", guild_id, user_id, tier_key)

        @staticmethod
        async def _spend_from_balances(
            db: aiosqlite.Connection,
            guild_id: int,
            user_id: int,
            amount: int,
            *,
            reason: str,
            now_s: str,
            count_as_loss: bool = True,
        ) -> tuple[int, int, int, int]:
            cursor = await db.execute(
                "SELECT wallet,bank FROM users WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("A Yoru egyenleged nem található.")
            wallet, bank = int(row[0]), int(row[1])
            wallet_available, bank_available = max(0, wallet), max(0, bank)
            if wallet_available + bank_available < int(amount):
                raise ValueError("Nincs elég pénzed a tárcádban és a bankodban összesen ehhez.")
            wallet_used = min(wallet_available, int(amount))
            bank_used = int(amount) - wallet_used
            new_wallet = wallet - wallet_used
            new_bank = bank - bank_used
            if count_as_loss:
                await db.execute(
                    "UPDATE users SET wallet=?,bank=?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?",
                    (new_wallet, new_bank, int(amount), guild_id, user_id),
                )
                await db.execute(
                    """INSERT INTO user_statistics (guild_id,user_id,stat_name,value,updated_at)
                       VALUES (?,?,'economy.lost',?,?)
                       ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET
                           value=value+excluded.value, updated_at=excluded.updated_at""",
                    (guild_id, user_id, int(amount), now_s),
                )
            else:
                await db.execute(
                    "UPDATE users SET wallet=?,bank=? WHERE guild_id=? AND user_id=?",
                    (new_wallet, new_bank, guild_id, user_id),
                )
            await db.execute(
                "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                (guild_id, user_id, -int(amount), reason, now_s),
            )
            return wallet_used, bank_used, new_wallet, new_bank

