from __future__ import annotations
from app.services.housing_projection_support import *

class HousingServiceMixin3:
        async def process_property_maintenance_user(
            self, guild_id: int, user_id: int, *, now: datetime | None = None
        ) -> list[BillingResult]:
            """Settle upkeep on every retained owned property.

            An owned home is never deleted because the player is short on cash.
            Unpaid upkeep becomes maintenance debt; future automatic passes settle it
            once the combined wallet+bank balance is sufficient.
            """
            now = (now or _utcnow()).astimezone(timezone.utc)
            now_s = _iso(now)
            results: list[BillingResult] = []
            properties = await self.properties(guild_id, user_id)
            for prop in properties:
                async with aiosqlite.connect(self.database.path) as db:
                    await db.execute("BEGIN IMMEDIATE")
                    try:
                        cur = await db.execute(
                            self._property_select_sql()
                            + " WHERE property_id=? AND guild_id=? AND user_id=? AND status='owned'",
                            (prop.property_id, guild_id, user_id),
                        )
                        row = await cur.fetchone()
                        if row is None:
                            await db.rollback()
                            continue
                        current = self._property_from_row(row)
                        paid_until = _parse(current.maintenance_paid_until) or now
                        debt = max(0, int(current.maintenance_debt))
                        weekly = cfg.weekly_cost(current.city_key, current.tier_key)
                        charged_new_period = False
                        # Catch up missed calendar periods exactly once each; repeated
                        # hourly billing passes cannot add the same week again.
                        safety = 0
                        while paid_until <= now and safety < 520:
                            debt += weekly
                            paid_until += timedelta(days=cfg.BILLING_PERIOD_DAYS)
                            charged_new_period = True
                            safety += 1

                        if debt <= 0:
                            await db.rollback()
                            continue

                        bal_cur = await db.execute(
                            "SELECT wallet,bank FROM users WHERE guild_id=? AND user_id=?",
                            (guild_id, user_id),
                        )
                        bal_row = await bal_cur.fetchone()
                        if bal_row is None:
                            raise RuntimeError("A Yoru egyenleged nem található.")
                        wallet, bank = int(bal_row[0]), int(bal_row[1])
                        if max(0, wallet) + max(0, bank) >= debt:
                            await self._spend_from_balances(
                                db,
                                guild_id,
                                user_id,
                                debt,
                                reason=f"housing_maintenance:{current.tier_key}:{current.city_key}:{current.property_id}",
                                now_s=now_s,
                            )
                            await db.execute(
                                """UPDATE housing_properties
                                   SET maintenance_paid_until=?,maintenance_grace_until=NULL,
                                       maintenance_debt=0,updated_at=?
                                   WHERE property_id=?""",
                                (_iso(paid_until), now_s, current.property_id),
                            )
                            await db.commit()
                            results.append(BillingResult(
                                "property_paid", guild_id, user_id, current.tier_key,
                                amount=debt, property_id=current.property_id,
                            ))
                            continue

                        grace = _parse(current.maintenance_grace_until)
                        if grace is None:
                            grace = now + timedelta(hours=cfg.GRACE_PERIOD_HOURS)
                        await db.execute(
                            """UPDATE housing_properties
                               SET maintenance_paid_until=?,maintenance_grace_until=?,maintenance_debt=?,updated_at=?
                               WHERE property_id=?""",
                            (_iso(paid_until), _iso(grace), debt, now_s, current.property_id),
                        )
                        await db.commit()
                        action = "property_grace_started" if current.maintenance_grace_until is None else (
                            "property_debt" if grace <= now else "property_grace"
                        )
                        results.append(BillingResult(
                            action, guild_id, user_id, current.tier_key,
                            amount=debt, grace_until=_iso(grace), property_id=current.property_id,
                        ))
                    except Exception:
                        await db.rollback()
                        raise
            return results

        async def process_all_due(self, *, now: datetime | None = None) -> list[BillingResult]:
            now = (now or _utcnow()).astimezone(timezone.utc)
            now_s = _iso(now)
            users: set[tuple[int, int]] = set()
            async with aiosqlite.connect(self.database.path) as db:
                cursor = await db.execute(
                    """SELECT guild_id,user_id FROM housing_state
                       WHERE tier_key IN ('shelter','rental') AND paid_until IS NOT NULL AND paid_until<=?""",
                    (now_s,),
                )
                users.update((int(row[0]), int(row[1])) for row in await cursor.fetchall())
                cursor = await db.execute(
                    """SELECT DISTINCT guild_id,user_id FROM housing_properties
                       WHERE status='owned' AND (maintenance_debt>0 OR maintenance_paid_until<=?)""",
                    (now_s,),
                )
                users.update((int(row[0]), int(row[1])) for row in await cursor.fetchall())

            results: list[BillingResult] = []
            for guild_id, user_id in sorted(users):
                try:
                    rent_result = await self.process_due_user(guild_id, user_id, now=now)
                    if rent_result.action not in {"not_due", "street", "no_character"}:
                        results.append(rent_result)
                    results.extend(await self.process_property_maintenance_user(guild_id, user_id, now=now))
                except Exception:
                    logger.exception("Housing billing failed guild=%s user=%s", guild_id, user_id)
            return results

        async def relocate_home_to_current(self, guild_id: int, user_id: int) -> HousingRelocationResult:
            """Make the player's current city their home without teleporting them.

            Rented accommodation ends when leaving the old home city. Owned property
            is retained in ``housing_properties`` and can be moved back into later.
            If the destination already contains one of the player's properties, it
            becomes the active residence immediately.
            """
            await self.characters.require(guild_id, user_id)
            now_s = _iso()
            from_city = ""
            to_city = ""
            activated_property_id: int | None = None
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
                    from_city, to_city = str(char_row[0]), str(char_row[1])
                    if from_city == to_city:
                        raise ValueError("Már ez a város az otthonod.")
                    if to_city not in character_cfg.STARTING_CITY_KEYS:
                        raise ValueError("Ez a város még nem választható állandó otthonnak.")

                    prop_cur = await db.execute(
                        self._property_select_sql()
                        + " WHERE guild_id=? AND user_id=? AND city_key=? AND status='owned' ORDER BY property_id DESC LIMIT 1",
                        (guild_id, user_id, to_city),
                    )
                    prop_row = await prop_cur.fetchone()
                    prop = self._property_from_row(prop_row) if prop_row is not None else None
                    if prop is not None:
                        activated_property_id = prop.property_id
                        tier_key = prop.tier_key
                        acquired_at = prop.acquired_at
                    else:
                        tier_key = "street"
                        acquired_at = None

                    await db.execute(
                        "UPDATE characters SET home_city_key=?,updated_at=? WHERE guild_id=? AND user_id=? AND status='active'",
                        (to_city, now_s, guild_id, user_id),
                    )
                    await db.execute(
                        """INSERT INTO housing_state
                           (guild_id,user_id,tier_key,city_key,acquired_at,paid_until,grace_until,updated_at)
                           VALUES (?,?,?,?,?,NULL,NULL,?)
                           ON CONFLICT(guild_id,user_id) DO UPDATE SET
                               tier_key=excluded.tier_key,city_key=excluded.city_key,acquired_at=excluded.acquired_at,
                               paid_until=NULL,grace_until=NULL,updated_at=excluded.updated_at""",
                        (guild_id, user_id, tier_key, to_city, acquired_at, now_s),
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

            state = await self.get(guild_id, user_id)
            prop = await self.get_property(guild_id, user_id, activated_property_id) if activated_property_id else None
            try:
                if not await self.characters.has_history_event(guild_id, user_id, "first_home_move"):
                    await self.characters.add_history(
                        guild_id,
                        user_id,
                        event_key="first_home_move",
                        title="Új otthonváros",
                        description=f"Először költöztél másik városba: {character_cfg.city_name(from_city)} után {character_cfg.city_name(to_city)} lett az otthonod.",
                        metadata={"from_city": from_city, "to_city": to_city},
                    )
            except Exception:
                logger.exception("Housing relocation history failed guild=%s user=%s", guild_id, user_id)
            return HousingRelocationResult(from_city, to_city, state, prop)

        async def move_into_property(self, guild_id: int, user_id: int, property_id: int) -> HousingRelocationResult:
            await self.characters.require(guild_id, user_id)
            now_s = _iso()
            from_city = ""
            to_city = ""
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
                    char_cur = await db.execute(
                        "SELECT home_city_key,current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'",
                        (guild_id, user_id),
                    )
                    char_row = await char_cur.fetchone()
                    if char_row is None:
                        raise ValueError("Még nincs aktív karaktered.")
                    from_city, current_city = str(char_row[0]), str(char_row[1])
                    to_city = prop.city_key
                    if current_city != to_city:
                        raise ValueError("Előbb utazz el abba a városba, ahol az ingatlan található.")
                    await db.execute(
                        "UPDATE characters SET home_city_key=?,updated_at=? WHERE guild_id=? AND user_id=? AND status='active'",
                        (to_city, now_s, guild_id, user_id),
                    )
                    await db.execute(
                        """INSERT INTO housing_state
                           (guild_id,user_id,tier_key,city_key,acquired_at,paid_until,grace_until,updated_at)
                           VALUES (?,?,?,?,?,NULL,NULL,?)
                           ON CONFLICT(guild_id,user_id) DO UPDATE SET
                               tier_key=excluded.tier_key,city_key=excluded.city_key,acquired_at=excluded.acquired_at,
                               paid_until=NULL,grace_until=NULL,updated_at=excluded.updated_at""",
                        (guild_id, user_id, prop.tier_key, to_city, prop.acquired_at, now_s),
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            return HousingRelocationResult(from_city, to_city, await self.get(guild_id, user_id), await self.get_property(guild_id, user_id, property_id))

