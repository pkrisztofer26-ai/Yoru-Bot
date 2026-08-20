from __future__ import annotations
from app.services.housing_projection_support import *

class HousingServiceMixin2:
        async def purchase_next(
            self, guild_id: int, user_id: int, *, expected_tier: str
        ) -> HousingPurchaseResult:
            character = await self.characters.require(guild_id, user_id)
            now = _utcnow()
            now_s = _iso(now)
            paid_until = _iso(now + timedelta(days=cfg.BILLING_PERIOD_DAYS))
            property_id: int | None = None

            async with aiosqlite.connect(self.database.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    cursor = await db.execute(
                        "SELECT tier_key,city_key FROM housing_state WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    row = await cursor.fetchone()
                    current_tier = str(row[0]) if row is not None else "street"
                    current_city = str(row[1]) if row is not None else character.home_city_key
                    if current_tier != str(expected_tier):
                        raise ValueError("A lakhatási helyzeted közben megváltozott. Nyisd meg újra a Lakhatás panelt.")
                    target_tier = cfg.next_tier(current_tier)
                    if target_tier is None:
                        raise ValueError("A Prémium ingatlan a jelenlegi lakhatási rendszer legfelső szintje.")

                    char_cur = await db.execute(
                        "SELECT home_city_key,current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    if char_row is None:
                        raise ValueError("Még nincs aktív karaktered.")
                    home_city, current_location = str(char_row[0]), str(char_row[1])
                    if current_city != home_city and current_tier != "street":
                        raise ValueError("A lakhatási adataid városa nem egyezik az otthonoddal. Kérj admin ellenőrzést.")
                    if current_location != home_city:
                        raise ValueError("Új lakhatást csak akkor intézhetsz, amikor az otthonod városában tartózkodsz.")
                    city_key = home_city

                    if target_tier == "owned":
                        existing_cur = await db.execute(
                            "SELECT property_id FROM housing_properties WHERE guild_id=? AND user_id=? AND city_key=? AND status='owned' LIMIT 1",
                            (guild_id, user_id, city_key),
                        )
                        if await existing_cur.fetchone() is not None:
                            raise ValueError("Ebben a városban már van saját ingatlanod. Az Ingatlanjaim panelen beköltözhetsz oda.")
                    elif target_tier == "premium":
                        prop_cur = await db.execute(
                            self._property_select_sql()
                            + " WHERE guild_id=? AND user_id=? AND city_key=? AND tier_key='owned' AND status='owned' ORDER BY property_id DESC LIMIT 1",
                            (guild_id, user_id, city_key),
                        )
                        prop_row = await prop_cur.fetchone()
                        if prop_row is None:
                            raise ValueError("A Prémium ingatlanhoz előbb saját lakás szükséges ebben a városban.")
                        current_property = self._property_from_row(prop_row)
                        if current_property.maintenance_debt > 0:
                            raise ValueError("A prémium fejlesztés előtt rendezd a saját lakás fenntartási hátralékát.")
                        property_id = int(current_property.property_id)

                    price = cfg.entry_price(city_key, target_tier)
                    wallet_used, bank_used, new_wallet, new_bank = await self._spend_from_balances(
                        db,
                        guild_id,
                        user_id,
                        price,
                        reason=f"housing_purchase:{target_tier}:{city_key}",
                        now_s=now_s,
                    )

                    if target_tier in cfg.RENTED_TIERS:
                        await db.execute(
                            """INSERT INTO housing_state
                               (guild_id,user_id,tier_key,city_key,acquired_at,paid_until,grace_until,updated_at)
                               VALUES (?,?,?,?,?,?,NULL,?)
                               ON CONFLICT(guild_id,user_id) DO UPDATE SET
                                   tier_key=excluded.tier_key,city_key=excluded.city_key,
                                   acquired_at=excluded.acquired_at,paid_until=excluded.paid_until,
                                   grace_until=NULL,updated_at=excluded.updated_at""",
                            (guild_id, user_id, target_tier, city_key, now_s, paid_until, now_s),
                        )
                    elif target_tier == "owned":
                        inserted = await db.execute(
                            """INSERT INTO housing_properties
                               (guild_id,user_id,city_key,tier_key,purchase_price,maintenance_paid_until,
                                maintenance_grace_until,maintenance_debt,last_opportunity_cycle,status,
                                acquired_at,upgraded_at,updated_at,sold_at,sale_price)
                               VALUES (?,?,?,?,?,?,NULL,0,NULL,'owned',?,NULL,?,NULL,NULL)""",
                            (guild_id, user_id, city_key, "owned", price, paid_until, now_s, now_s),
                        )
                        property_id = int(getattr(inserted, "lastrowid", 0) or 0)
                        if property_id <= 0:
                            last_cur = await db.execute(
                                "SELECT property_id FROM housing_properties WHERE guild_id=? AND user_id=? AND city_key=? AND status='owned' ORDER BY property_id DESC LIMIT 1",
                                (guild_id, user_id, city_key),
                            )
                            last_row = await last_cur.fetchone()
                            property_id = int(last_row[0]) if last_row else 0
                        await db.execute(
                            """INSERT INTO housing_state
                               (guild_id,user_id,tier_key,city_key,acquired_at,paid_until,grace_until,updated_at)
                               VALUES (?,?,?,?,?,NULL,NULL,?)
                               ON CONFLICT(guild_id,user_id) DO UPDATE SET
                                   tier_key=excluded.tier_key,city_key=excluded.city_key,
                                   acquired_at=excluded.acquired_at,paid_until=NULL,grace_until=NULL,updated_at=excluded.updated_at""",
                            (guild_id, user_id, "owned", city_key, now_s, now_s),
                        )
                    elif target_tier == "premium":
                        assert property_id is not None
                        await db.execute(
                            """UPDATE housing_properties
                               SET tier_key='premium',purchase_price=purchase_price+?,upgraded_at=?,updated_at=?
                               WHERE property_id=? AND guild_id=? AND user_id=? AND status='owned'""",
                            (price, now_s, now_s, property_id, guild_id, user_id),
                        )
                        await db.execute(
                            """UPDATE housing_state SET tier_key='premium',city_key=?,paid_until=NULL,grace_until=NULL,updated_at=?
                               WHERE guild_id=? AND user_id=?""",
                            (city_key, now_s, guild_id, user_id),
                        )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

            state = await self.get(guild_id, user_id)
            prop = await self.get_property(guild_id, user_id, property_id) if property_id else None
            await self._record_first_milestone(guild_id, user_id, target_tier, city_key)
            if self.memory_adapters is not None:
                try:
                    await self.memory_adapters.housing_purchased(
                        guild_id, user_id, tier_key=target_tier, city_key=city_key,
                        property_id=property_id, occurred_at=now_s,
                    )
                except Exception:
                    logger.exception(
                        "Housing first-contact memory failed guild=%s user=%s tier=%s",
                        guild_id, user_id, target_tier,
                    )
            return HousingPurchaseResult(state, price, wallet_used, bank_used, new_wallet, new_bank, prop)

        async def process_due_user(self, guild_id: int, user_id: int, *, now: datetime | None = None) -> BillingResult:
            """Settle the active rented residence. Owned-property upkeep is separate."""
            now = (now or _utcnow()).astimezone(timezone.utc)
            now_s = _iso(now)
            character = await self.characters.get(guild_id, user_id)
            if character is None:
                return BillingResult("no_character", guild_id, user_id, "street")

            evicted = False
            evicted_from = "street"
            result: BillingResult
            async with aiosqlite.connect(self.database.path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    cursor = await db.execute(
                        """SELECT tier_key,city_key,paid_until,grace_until
                           FROM housing_state WHERE guild_id=? AND user_id=?""",
                        (guild_id, user_id),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        await db.rollback()
                        return BillingResult("street", guild_id, user_id, "street")

                    tier_key = str(row[0])
                    city_key = str(row[1])
                    paid_until = _parse(str(row[2]) if row[2] is not None else None)
                    grace_until = _parse(str(row[3]) if row[3] is not None else None)
                    if tier_key not in cfg.RENTED_TIERS or paid_until is None or paid_until > now:
                        await db.rollback()
                        return BillingResult("not_due", guild_id, user_id, tier_key, grace_until=str(row[3]) if row[3] else None)

                    amount = cfg.weekly_cost(city_key, tier_key)
                    balance_cur = await db.execute(
                        "SELECT wallet,bank FROM users WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    balance_row = await balance_cur.fetchone()
                    if balance_row is None:
                        raise RuntimeError("A Yoru egyenleged nem található.")
                    wallet, bank = int(balance_row[0]), int(balance_row[1])

                    if max(0, wallet) + max(0, bank) >= amount:
                        await self._spend_from_balances(
                            db,
                            guild_id,
                            user_id,
                            amount,
                            reason=f"housing_weekly:{tier_key}:{city_key}",
                            now_s=now_s,
                        )
                        next_due = _iso(now + timedelta(days=cfg.BILLING_PERIOD_DAYS))
                        await db.execute(
                            "UPDATE housing_state SET paid_until=?,grace_until=NULL,updated_at=? WHERE guild_id=? AND user_id=?",
                            (next_due, now_s, guild_id, user_id),
                        )
                        await db.commit()
                        return BillingResult("paid", guild_id, user_id, tier_key, amount=amount)

                    if grace_until is None:
                        new_grace = _iso(now + timedelta(hours=cfg.GRACE_PERIOD_HOURS))
                        await db.execute(
                            "UPDATE housing_state SET grace_until=?,updated_at=? WHERE guild_id=? AND user_id=?",
                            (new_grace, now_s, guild_id, user_id),
                        )
                        await db.commit()
                        return BillingResult("grace_started", guild_id, user_id, tier_key, amount=amount, grace_until=new_grace)

                    if grace_until > now:
                        await db.rollback()
                        return BillingResult("grace", guild_id, user_id, tier_key, amount=amount, grace_until=_iso(grace_until))

                    evicted = True
                    evicted_from = tier_key
                    await db.execute(
                        """UPDATE housing_state
                           SET tier_key='street',city_key=?,acquired_at=NULL,paid_until=NULL,grace_until=NULL,updated_at=?
                           WHERE guild_id=? AND user_id=?""",
                        (character.home_city_key, now_s, guild_id, user_id),
                    )
                    await db.commit()
                    result = BillingResult("lost_housing", guild_id, user_id, "street")
                except Exception:
                    await db.rollback()
                    raise

            if evicted:
                try:
                    await self.characters.add_history(
                        guild_id,
                        user_id,
                        event_key="housing_lost",
                        title="Lakhatás megszűnt",
                        description="A lakhatási költség türelmi ideje lejárt, ezért ismét az utcára kerültél.",
                        metadata={"previous_tier": evicted_from},
                    )
                except Exception:
                    logger.exception("Housing loss history failed guild=%s user=%s", guild_id, user_id)
            return result

