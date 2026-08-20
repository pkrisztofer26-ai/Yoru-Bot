from __future__ import annotations
from app.services.housing_projection_support import *

class HousingServiceMixin4:
        async def sell_property(self, guild_id: int, user_id: int, property_id: int) -> HousingSaleResult:
            await self.characters.require(guild_id, user_id)
            now_s = _iso()
            result: HousingSaleResult | None = None
            async with aiosqlite.connect(self.database.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    prop_cur = await db.execute(
                        self._property_select_sql()
                        + " WHERE property_id=? AND guild_id=? AND user_id=? AND status='owned'",
                        (int(property_id), guild_id, user_id),
                    )
                    prop_row = await prop_cur.fetchone()
                    if prop_row is None:
                        raise ValueError("Ez az ingatlan már nincs a tulajdonodban.")
                    prop = self._property_from_row(prop_row)
                    gross = cfg.property_sale_value(prop.city_key, prop.tier_key)
                    debt = min(gross, max(0, int(prop.maintenance_debt)))
                    received = max(0, gross - debt)

                    bal_cur = await db.execute(
                        "SELECT bank FROM users WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    bal_row = await bal_cur.fetchone()
                    if bal_row is None:
                        raise RuntimeError("A Yoru egyenleged nem található.")
                    new_bank = int(bal_row[0]) + received
                    await db.execute(
                        "UPDATE users SET bank=? WHERE guild_id=? AND user_id=?",
                        (new_bank, guild_id, user_id),
                    )
                    if received > 0:
                        await db.execute(
                            "INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                            (guild_id, user_id, received, f"housing_property_sale:{prop.tier_key}:{prop.city_key}:{prop.property_id}", now_s),
                        )
                    await db.execute("DELETE FROM housing_garage WHERE property_id=?", (prop.property_id,))
                    await db.execute(
                        """UPDATE housing_properties SET status='sold',sold_at=?,sale_price=?,updated_at=?
                           WHERE property_id=?""",
                        (now_s, gross, now_s, prop.property_id),
                    )

                    char_cur = await db.execute(
                        "SELECT home_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    state_cur = await db.execute(
                        "SELECT tier_key,city_key FROM housing_state WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    state_row = await state_cur.fetchone()
                    active_lost = bool(
                        char_row is not None
                        and state_row is not None
                        and str(char_row[0]) == prop.city_key
                        and str(state_row[1]) == prop.city_key
                        and str(state_row[0]) in cfg.PROPERTY_TIERS
                    )
                    if active_lost:
                        await db.execute(
                            """UPDATE housing_state SET tier_key='street',city_key=?,acquired_at=NULL,
                               paid_until=NULL,grace_until=NULL,updated_at=? WHERE guild_id=? AND user_id=?""",
                            (prop.city_key, now_s, guild_id, user_id),
                        )
                    await db.commit()
                    result = HousingSaleResult(
                        prop.property_id, prop.city_key, prop.tier_key, gross, debt, received, new_bank, active_lost,
                    )
                except Exception:
                    await db.rollback()
                    raise
            if result is None:
                raise RuntimeError("Az ingatlaneladás eredménye nem olvasható vissza.")
            return result

        async def storage_items(self, guild_id: int, user_id: int) -> list[StorageItem]:
            await self.characters.require(guild_id, user_id)
            async with aiosqlite.connect(self.database.path) as db:
                cur = await db.execute(
                    """SELECT hs.item_id,COALESCE(si.name,hs.item_id),COALESCE(si.emoji,'📦'),hs.quantity
                       FROM housing_storage hs LEFT JOIN shop_items si ON si.item_id=hs.item_id
                       WHERE hs.guild_id=? AND hs.user_id=? AND hs.quantity>0
                       ORDER BY COALESCE(si.price,0) DESC,COALESCE(si.name,hs.item_id)""",
                    (guild_id, user_id),
                )
                rows = await cur.fetchall()
            return [StorageItem(str(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows]

        async def storage_usage(self, guild_id: int, user_id: int) -> tuple[int, int]:
            state = await self.get(guild_id, user_id)
            async with aiosqlite.connect(self.database.path) as db:
                cur = await db.execute(
                    "SELECT COALESCE(SUM(quantity),0) FROM housing_storage WHERE guild_id=? AND user_id=? AND quantity>0",
                    (guild_id, user_id),
                )
                row = await cur.fetchone()
            return int(row[0] or 0) if row else 0, cfg.storage_capacity(state.tier_key)

        async def _resolve_inventory_item(self, db: aiosqlite.Connection, raw: str) -> tuple[str, str, str]:
            item_id = shop_cfg.resolve_item_id(raw)
            row = None
            if item_id:
                cur = await db.execute("SELECT item_id,name,emoji FROM shop_items WHERE item_id=?", (item_id,))
                row = await cur.fetchone()
            if row is None:
                cur = await db.execute(
                    "SELECT item_id,name,emoji FROM shop_items WHERE LOWER(name)=LOWER(?) LIMIT 1",
                    (str(raw).strip(),),
                )
                row = await cur.fetchone()
            if row is None:
                raise ValueError("Nem találtam ilyen tárgyat. Írd be a Tárgyaim panelen látható nevét.")
            return str(row[0]), str(row[1]), str(row[2])

        async def transfer_to_storage(self, guild_id: int, user_id: int, raw_item: str, quantity: int) -> StorageTransferResult:
            if int(quantity) <= 0:
                raise ValueError("A darabszám legalább 1 legyen.")
            now_s = _iso()
            async with aiosqlite.connect(self.database.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    char_cur = await db.execute(
                        "SELECT home_city_key,current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    if char_row is None:
                        raise ValueError("Még nincs aktív karaktered.")
                    if str(char_row[0]) != str(char_row[1]):
                        raise ValueError("Az otthoni tárolót csak akkor rendezheted, amikor otthon vagy.")
                    state_cur = await db.execute(
                        "SELECT tier_key FROM housing_state WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    state_row = await state_cur.fetchone()
                    tier_key = str(state_row[0]) if state_row else "street"
                    capacity = cfg.storage_capacity(tier_key)
                    item_id, name, emoji = await self._resolve_inventory_item(db, raw_item)
                    spec = shop_cfg.item_spec(item_id)
                    if spec is not None and spec.market_asset:
                        raise ValueError("A befektetéseket nem kell az otthoni tárolóban tartani; a Befektetések panel kezeli őket.")
                    inv_cur = await db.execute(
                        "SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_id=?",
                        (guild_id, user_id, item_id),
                    )
                    inv_row = await inv_cur.fetchone()
                    have = int(inv_row[0]) if inv_row else 0
                    if have < int(quantity):
                        raise ValueError(f"Nincs nálad ennyi ebből: {name}.")
                    usage_cur = await db.execute(
                        "SELECT COALESCE(SUM(quantity),0) FROM housing_storage WHERE guild_id=? AND user_id=? AND quantity>0",
                        (guild_id, user_id),
                    )
                    usage_row = await usage_cur.fetchone()
                    used = int(usage_row[0] or 0) if usage_row else 0
                    if used + int(quantity) > capacity:
                        raise ValueError(f"Nincs ennyi szabad hely az otthoni tárolóban. Jelenleg {used}/{capacity} hely foglalt.")
                    await db.execute(
                        "UPDATE inventory SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND item_id=?",
                        (int(quantity), guild_id, user_id, item_id),
                    )
                    await db.execute(
                        """INSERT INTO housing_storage(guild_id,user_id,item_id,quantity,updated_at)
                           VALUES (?,?,?,?,?) ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET
                           quantity=quantity+excluded.quantity,updated_at=excluded.updated_at""",
                        (guild_id, user_id, item_id, int(quantity), now_s),
                    )
                    await db.commit()
                    return StorageTransferResult(item_id, name, emoji, int(quantity), used + int(quantity), capacity)
                except Exception:
                    await db.rollback()
                    raise

        async def transfer_from_storage(self, guild_id: int, user_id: int, raw_item: str, quantity: int) -> StorageTransferResult:
            if int(quantity) <= 0:
                raise ValueError("A darabszám legalább 1 legyen.")
            now_s = _iso()
            async with aiosqlite.connect(self.database.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    char_cur = await db.execute(
                        "SELECT home_city_key,current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    if char_row is None:
                        raise ValueError("Még nincs aktív karaktered.")
                    if str(char_row[0]) != str(char_row[1]):
                        raise ValueError("Az otthoni tárolót csak akkor rendezheted, amikor otthon vagy.")
                    state_cur = await db.execute(
                        "SELECT tier_key FROM housing_state WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    state_row = await state_cur.fetchone()
                    tier_key = str(state_row[0]) if state_row else "street"
                    capacity = cfg.storage_capacity(tier_key)
                    item_id, name, emoji = await self._resolve_inventory_item(db, raw_item)
                    stored_cur = await db.execute(
                        "SELECT quantity FROM housing_storage WHERE guild_id=? AND user_id=? AND item_id=?",
                        (guild_id, user_id, item_id),
                    )
                    stored_row = await stored_cur.fetchone()
                    have = int(stored_row[0]) if stored_row else 0
                    if have < int(quantity):
                        raise ValueError(f"Nincs ennyi ebből az otthoni tárolóban: {name}.")
                    await db.execute(
                        "UPDATE housing_storage SET quantity=quantity-?,updated_at=? WHERE guild_id=? AND user_id=? AND item_id=?",
                        (int(quantity), now_s, guild_id, user_id, item_id),
                    )
                    await db.execute(
                        """INSERT INTO inventory(guild_id,user_id,item_id,quantity) VALUES (?,?,?,?)
                           ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                        (guild_id, user_id, item_id, int(quantity)),
                    )
                    usage_cur = await db.execute(
                        "SELECT COALESCE(SUM(quantity),0) FROM housing_storage WHERE guild_id=? AND user_id=? AND quantity>0",
                        (guild_id, user_id),
                    )
                    usage_row = await usage_cur.fetchone()
                    used_after = int(usage_row[0] or 0) if usage_row else 0
                    await db.commit()
                    return StorageTransferResult(item_id, name, emoji, int(quantity), used_after, capacity)
                except Exception:
                    await db.rollback()
                    raise

        async def garage_vehicles(self, guild_id: int, user_id: int, property_id: int) -> list[GarageVehicle]:
            prop = await self.get_property(guild_id, user_id, property_id)
            if prop is None:
                raise ValueError("Ez az ingatlan már nincs a tulajdonodban.")
            async with aiosqlite.connect(self.database.path) as db:
                cur = await db.execute(
                    """SELECT cv.vehicle_id,cv.model_key,cv.condition_key,cv.city_key,
                              CASE WHEN hg.vehicle_id IS NULL THEN 0 ELSE 1 END
                       FROM character_vehicles cv
                       LEFT JOIN housing_garage hg ON hg.vehicle_id=cv.vehicle_id AND hg.property_id=?
                       WHERE cv.guild_id=? AND cv.user_id=? AND cv.status='owned' AND cv.city_key=?
                       ORDER BY cv.acquired_at,cv.vehicle_id""",
                    (prop.property_id, guild_id, user_id, prop.city_key),
                )
                rows = await cur.fetchall()
            return [GarageVehicle(int(r[0]), str(r[1]), str(r[2]), str(r[3]), bool(int(r[4]))) for r in rows]

        async def garage_usage(self, guild_id: int, user_id: int, property_id: int) -> tuple[int, int]:
            prop = await self.get_property(guild_id, user_id, property_id)
            if prop is None:
                raise ValueError("Ez az ingatlan már nincs a tulajdonodban.")
            async with aiosqlite.connect(self.database.path) as db:
                cur = await db.execute("SELECT COUNT(*) FROM housing_garage WHERE property_id=?", (prop.property_id,))
                row = await cur.fetchone()
            return int(row[0]) if row else 0, cfg.garage_slots(prop.tier_key)

