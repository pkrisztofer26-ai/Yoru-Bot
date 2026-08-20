from __future__ import annotations
from app.services.housing_projection_support import *

class HousingServiceMixin5:
        async def park_vehicle(self, guild_id: int, user_id: int, property_id: int, vehicle_id: int) -> tuple[int, int]:
            await self.characters.require(guild_id, user_id)
            now_s = _iso()
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
                    slots = cfg.garage_slots(prop.tier_key)
                    if slots <= 0:
                        raise ValueError("Ehhez az ingatlanhoz nem tartozik garázshely.")
                    char_cur = await db.execute(
                        "SELECT current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    if char_row is None or str(char_row[0]) != prop.city_key:
                        raise ValueError("A garázst csak akkor rendezheted, amikor az ingatlan városában vagy.")
                    vehicle_cur = await db.execute(
                        """SELECT city_key FROM character_vehicles
                           WHERE vehicle_id=? AND guild_id=? AND user_id=? AND status='owned'""",
                        (int(vehicle_id), guild_id, user_id),
                    )
                    vehicle_row = await vehicle_cur.fetchone()
                    if vehicle_row is None:
                        raise ValueError("Ez a jármű már nincs a tulajdonodban.")
                    if str(vehicle_row[0]) != prop.city_key:
                        raise ValueError("Ez a jármű nincs az ingatlan városában.")
                    existing_cur = await db.execute("SELECT property_id FROM housing_garage WHERE vehicle_id=?", (int(vehicle_id),))
                    existing = await existing_cur.fetchone()
                    if existing is not None and int(existing[0]) == prop.property_id:
                        await db.rollback()
                        used, _ = await self.garage_usage(guild_id, user_id, prop.property_id)
                        return used, slots
                    count_cur = await db.execute("SELECT COUNT(*) FROM housing_garage WHERE property_id=?", (prop.property_id,))
                    count_row = await count_cur.fetchone()
                    used = int(count_row[0]) if count_row else 0
                    if used >= slots:
                        raise ValueError("Nincs több szabad garázshely ennél az ingatlannál.")
                    await db.execute("DELETE FROM housing_garage WHERE vehicle_id=?", (int(vehicle_id),))
                    await db.execute(
                        "INSERT INTO housing_garage(property_id,vehicle_id,guild_id,user_id,parked_at) VALUES (?,?,?,?,?)",
                        (prop.property_id, int(vehicle_id), guild_id, user_id, now_s),
                    )
                    await db.commit()
                    return used + 1, slots
                except Exception:
                    await db.rollback()
                    raise

        async def unpark_vehicle(self, guild_id: int, user_id: int, property_id: int, vehicle_id: int) -> tuple[int, int]:
            prop = await self.get_property(guild_id, user_id, property_id)
            if prop is None:
                raise ValueError("Ez az ingatlan már nincs a tulajdonodban.")
            async with aiosqlite.connect(self.database.path) as db:
                char_cur = await db.execute(
                    "SELECT current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                    (guild_id, user_id),
                )
                char_row = await char_cur.fetchone()
                if char_row is None or str(char_row[0]) != prop.city_key:
                    raise ValueError("A garázst csak akkor rendezheted, amikor az ingatlan városában vagy.")
                await db.execute(
                    "DELETE FROM housing_garage WHERE property_id=? AND vehicle_id=? AND guild_id=? AND user_id=?",
                    (prop.property_id, int(vehicle_id), guild_id, user_id),
                )
                await db.commit()
            return await self.garage_usage(guild_id, user_id, property_id)

        @staticmethod
        def _premium_opportunity_hash(guild_id: int, user_id: int, cycle_id: str) -> int:
            raw = f"housing-premium:{int(guild_id)}:{int(user_id)}:{cycle_id}".encode("utf-8")
            return int(hashlib.sha256(raw).hexdigest()[:16], 16)

        async def premium_opportunity_available(self, guild_id: int, user_id: int, cycle_id: str) -> bool:
            character = await self.characters.get(guild_id, user_id)
            if character is None or character.current_city_key != character.home_city_key:
                return False
            state = await self.get(guild_id, user_id)
            if state.tier_key != "premium":
                return False
            prop = await self.active_property(guild_id, user_id)
            if prop is None or prop.maintenance_debt > 0 or prop.last_opportunity_cycle == str(cycle_id):
                return False
            return self._premium_opportunity_hash(guild_id, user_id, str(cycle_id)) % cfg.PREMIUM_OPPORTUNITY_MODULUS == 0

        async def claim_premium_opportunity(
            self, guild_id: int, user_id: int, cycle_id: str
        ) -> PremiumHousingOpportunityResult:
            await self.characters.require(guild_id, user_id)
            if self._premium_opportunity_hash(guild_id, user_id, str(cycle_id)) % cfg.PREMIUM_OPPORTUNITY_MODULUS != 0:
                raise ValueError("Ez a privát lehetőség most nem elérhető.")
            now_s = _iso()
            reward_seed = self._premium_opportunity_hash(guild_id, user_id, str(cycle_id) + ":reward")
            reward_id = cfg.PREMIUM_OPPORTUNITY_REWARDS[reward_seed % len(cfg.PREMIUM_OPPORTUNITY_REWARDS)]
            spec = shop_cfg.item_spec(reward_id)
            if spec is None:
                raise RuntimeError("A prémium lakhatási jutalom konfigurációja hiányos.")
            async with aiosqlite.connect(self.database.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    char_cur = await db.execute(
                        "SELECT home_city_key,current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    if char_row is None or str(char_row[0]) != str(char_row[1]):
                        raise ValueError("Ezt a lehetőséget akkor tudod elintézni, amikor otthon vagy.")
                    prop_cur = await db.execute(
                        self._property_select_sql()
                        + " WHERE guild_id=? AND user_id=? AND city_key=? AND tier_key='premium' AND status='owned' ORDER BY property_id DESC LIMIT 1",
                        (guild_id, user_id, str(char_row[0])),
                    )
                    prop_row = await prop_cur.fetchone()
                    if prop_row is None:
                        raise ValueError("Nincs aktív Prémium ingatlanod.")
                    prop = self._property_from_row(prop_row)
                    if prop.maintenance_debt > 0:
                        raise ValueError("Előbb rendezd az ingatlan karbantartási hátralékát.")
                    if prop.last_opportunity_cycle == str(cycle_id):
                        raise ValueError("Ezt a meghívást már felhasználtad.")
                    await db.execute(
                        "UPDATE housing_properties SET last_opportunity_cycle=?,updated_at=? WHERE property_id=?",
                        (str(cycle_id), now_s, prop.property_id),
                    )
                    await db.execute(
                        """INSERT INTO inventory(guild_id,user_id,item_id,quantity) VALUES (?,?,?,1)
                           ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+1""",
                        (guild_id, user_id, reward_id),
                    )
                    await db.execute(
                        """INSERT INTO user_statistics(guild_id,user_id,stat_name,value,updated_at)
                           VALUES (?,?,'housing.premium_opportunities',1,?)
                           ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET
                           value=value+1,updated_at=excluded.updated_at""",
                        (guild_id, user_id, now_s),
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            return PremiumHousingOpportunityResult(reward_id, spec.name, spec.emoji)

