from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app import business_config as cfg
from app.services.server_settings import ServerSettingsService


@dataclass(frozen=True)
class BusinessSettings:
    enabled: bool
    required_activity_level: int
    required_prestige: int
    license_price: int
    tax_percent: int
    offline_cap_hours: int
    base_property_cap: int
    prestige_step: int
    absolute_cap: int
    city_cap: int
    income_multiplier_percent: int
    worker_contract_days: int
    property_offer_hours: int
    transfer_tax_percent: int
    faction_bonus_percent: int
    faction_xp_per_claim: int


class BusinessService:
    def __init__(self, database, statistics, prestige, activity, crew, factions) -> None:
        self.db = database
        self.stats = statistics
        self.prestige = prestige
        self.activity = activity
        self.crew = crew
        self.factions = factions
        self.settings = ServerSettingsService(database)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _dt(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    async def get_settings(self, guild_id: int) -> BusinessSettings:
        get_int = self.settings.get_int
        required_activity = await get_int(guild_id, cfg.BUSINESS_ACTIVITY_LEVEL_KEY)
        required_prestige = await get_int(guild_id, cfg.BUSINESS_PRESTIGE_KEY)
        license_price = await get_int(guild_id, cfg.BUSINESS_LICENSE_PRICE_KEY)
        tax = await get_int(guild_id, cfg.BUSINESS_TAX_PERCENT_KEY)
        offline = await get_int(guild_id, cfg.BUSINESS_OFFLINE_CAP_HOURS_KEY)
        base_cap = await get_int(guild_id, cfg.BUSINESS_BASE_PROPERTY_CAP_KEY)
        prestige_step = await get_int(guild_id, cfg.BUSINESS_PRESTIGE_STEP_KEY)
        absolute_cap = await get_int(guild_id, cfg.BUSINESS_ABSOLUTE_CAP_KEY)
        city_cap = await get_int(guild_id, cfg.BUSINESS_CITY_CAP_KEY)
        multiplier = await get_int(guild_id, cfg.BUSINESS_INCOME_MULTIPLIER_KEY)
        worker_days = await get_int(guild_id, cfg.BUSINESS_WORKER_DAYS_KEY)
        offer_hours = await get_int(guild_id, cfg.BUSINESS_OFFER_HOURS_KEY)
        transfer_tax = await get_int(guild_id, cfg.BUSINESS_TRANSFER_TAX_KEY)
        faction_bonus = await get_int(guild_id, cfg.BUSINESS_FACTION_BONUS_KEY)
        faction_xp = await get_int(guild_id, cfg.BUSINESS_FACTION_XP_KEY)
        return BusinessSettings(
            enabled=await self.settings.get_bool(guild_id, cfg.BUSINESS_ENABLED_KEY, cfg.DEFAULT_ENABLED),
            required_activity_level=cfg.DEFAULT_REQUIRED_ACTIVITY_LEVEL if required_activity is None else max(0, min(500, int(required_activity))),
            required_prestige=cfg.DEFAULT_REQUIRED_PRESTIGE if required_prestige is None else max(0, min(100, int(required_prestige))),
            license_price=cfg.DEFAULT_LICENSE_PRICE if license_price is None else max(cfg.MIN_LICENSE_PRICE, min(cfg.MAX_LICENSE_PRICE, int(license_price))),
            tax_percent=cfg.DEFAULT_TAX_PERCENT if tax is None else max(cfg.MIN_TAX_PERCENT, min(cfg.MAX_TAX_PERCENT, int(tax))),
            offline_cap_hours=cfg.DEFAULT_OFFLINE_CAP_HOURS if offline is None else max(cfg.MIN_OFFLINE_CAP_HOURS, min(cfg.MAX_OFFLINE_CAP_HOURS, int(offline))),
            base_property_cap=cfg.DEFAULT_BASE_PROPERTY_CAP if base_cap is None else max(cfg.MIN_PROPERTY_CAP, min(cfg.MAX_PROPERTY_CAP, int(base_cap))),
            prestige_step=cfg.DEFAULT_PRESTIGE_STEP if prestige_step is None else max(cfg.MIN_PRESTIGE_STEP, min(cfg.MAX_PRESTIGE_STEP, int(prestige_step))),
            absolute_cap=cfg.DEFAULT_ABSOLUTE_CAP if absolute_cap is None else max(cfg.MIN_PROPERTY_CAP, min(cfg.MAX_PROPERTY_CAP, int(absolute_cap))),
            city_cap=cfg.DEFAULT_CITY_CAP if city_cap is None else max(1, min(cfg.MAX_PROPERTY_CAP, int(city_cap))),
            income_multiplier_percent=cfg.DEFAULT_INCOME_MULTIPLIER_PERCENT if multiplier is None else max(cfg.MIN_INCOME_MULTIPLIER_PERCENT, min(cfg.MAX_INCOME_MULTIPLIER_PERCENT, int(multiplier))),
            worker_contract_days=cfg.DEFAULT_WORKER_CONTRACT_DAYS if worker_days is None else max(cfg.MIN_WORKER_CONTRACT_DAYS, min(cfg.MAX_WORKER_CONTRACT_DAYS, int(worker_days))),
            property_offer_hours=cfg.PROPERTY_OFFER_HOURS if offer_hours is None else max(1,min(168,int(offer_hours))),
            transfer_tax_percent=cfg.PROPERTY_TRANSFER_TAX_PERCENT if transfer_tax is None else max(0,min(50,int(transfer_tax))),
            faction_bonus_percent=cfg.FACTION_BONUS_PERCENT if faction_bonus is None else max(0,min(50,int(faction_bonus))),
            faction_xp_per_claim=cfg.FACTION_XP_PER_CLAIM if faction_xp is None else max(0,min(100000,int(faction_xp))),
        )

    async def set_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.settings.set_bool(guild_id, cfg.BUSINESS_ENABLED_KEY, bool(enabled))

    async def set_unlock_settings(self, guild_id: int, *, activity_level: int, prestige: int, license_price: int) -> None:
        if not 0 <= int(activity_level) <= 500:
            raise ValueError("Az Activity követelmény 0–500 között lehet.")
        if not 0 <= int(prestige) <= 100:
            raise ValueError("A Prestige követelmény 0–100 között lehet.")
        if not cfg.MIN_LICENSE_PRICE <= int(license_price) <= cfg.MAX_LICENSE_PRICE:
            raise ValueError("Érvénytelen Business License ár.")
        await self.settings.set_int(guild_id, cfg.BUSINESS_ACTIVITY_LEVEL_KEY, int(activity_level))
        await self.settings.set_int(guild_id, cfg.BUSINESS_PRESTIGE_KEY, int(prestige))
        await self.settings.set_int(guild_id, cfg.BUSINESS_LICENSE_PRICE_KEY, int(license_price))

    async def set_economy_settings(self, guild_id: int, *, tax_percent: int, offline_cap_hours: int, income_multiplier_percent: int, worker_contract_days: int) -> None:
        if not cfg.MIN_TAX_PERCENT <= int(tax_percent) <= cfg.MAX_TAX_PERCENT:
            raise ValueError(f"Az adó {cfg.MIN_TAX_PERCENT}–{cfg.MAX_TAX_PERCENT}% között lehet.")
        if not cfg.MIN_OFFLINE_CAP_HOURS <= int(offline_cap_hours) <= cfg.MAX_OFFLINE_CAP_HOURS:
            raise ValueError(f"Az offline cap {cfg.MIN_OFFLINE_CAP_HOURS}–{cfg.MAX_OFFLINE_CAP_HOURS} óra között lehet.")
        if not cfg.MIN_INCOME_MULTIPLIER_PERCENT <= int(income_multiplier_percent) <= cfg.MAX_INCOME_MULTIPLIER_PERCENT:
            raise ValueError(f"A bevételi szorzó {cfg.MIN_INCOME_MULTIPLIER_PERCENT}–{cfg.MAX_INCOME_MULTIPLIER_PERCENT}% között lehet.")
        if not cfg.MIN_WORKER_CONTRACT_DAYS <= int(worker_contract_days) <= cfg.MAX_WORKER_CONTRACT_DAYS:
            raise ValueError(f"A dolgozói szerződés {cfg.MIN_WORKER_CONTRACT_DAYS}–{cfg.MAX_WORKER_CONTRACT_DAYS} nap között lehet.")
        await self.settings.set_int(guild_id, cfg.BUSINESS_TAX_PERCENT_KEY, int(tax_percent))
        await self.settings.set_int(guild_id, cfg.BUSINESS_OFFLINE_CAP_HOURS_KEY, int(offline_cap_hours))
        await self.settings.set_int(guild_id, cfg.BUSINESS_INCOME_MULTIPLIER_KEY, int(income_multiplier_percent))
        await self.settings.set_int(guild_id, cfg.BUSINESS_WORKER_DAYS_KEY, int(worker_contract_days))

    async def set_limit_settings(self, guild_id: int, *, base_cap: int, prestige_step: int, absolute_cap: int, city_cap: int) -> None:
        for value, label in ((base_cap, "alap limit"), (absolute_cap, "abszolút limit"), (city_cap, "városi limit")):
            if not cfg.MIN_PROPERTY_CAP <= int(value) <= cfg.MAX_PROPERTY_CAP:
                raise ValueError(f"A(z) {label} {cfg.MIN_PROPERTY_CAP}–{cfg.MAX_PROPERTY_CAP} között lehet.")
        if not cfg.MIN_PRESTIGE_STEP <= int(prestige_step) <= cfg.MAX_PRESTIGE_STEP:
            raise ValueError(f"A Prestige step {cfg.MIN_PRESTIGE_STEP}–{cfg.MAX_PRESTIGE_STEP} között lehet.")
        if int(base_cap) > int(absolute_cap):
            raise ValueError("Az alap property limit nem lehet nagyobb az abszolút limitnél.")
        await self.settings.set_int(guild_id, cfg.BUSINESS_BASE_PROPERTY_CAP_KEY, int(base_cap))
        await self.settings.set_int(guild_id, cfg.BUSINESS_PRESTIGE_STEP_KEY, int(prestige_step))
        await self.settings.set_int(guild_id, cfg.BUSINESS_ABSOLUTE_CAP_KEY, int(absolute_cap))
        await self.settings.set_int(guild_id, cfg.BUSINESS_CITY_CAP_KEY, int(city_cap))

    async def set_market_settings(self,guild_id:int,*,offer_hours:int,transfer_tax_percent:int,faction_bonus_percent:int,faction_xp_per_claim:int)->None:
        if not 1<=int(offer_hours)<=168: raise ValueError("Offer idő: 1–168 óra.")
        if not 0<=int(transfer_tax_percent)<=50: raise ValueError("Transfer tax: 0–50%.")
        if not 0<=int(faction_bonus_percent)<=50: raise ValueError("Frakció bonus: 0–50%.")
        if not 0<=int(faction_xp_per_claim)<=100000: raise ValueError("Frakció XP/claim: 0–100000.")
        await self.settings.set_int(guild_id,cfg.BUSINESS_OFFER_HOURS_KEY,int(offer_hours))
        await self.settings.set_int(guild_id,cfg.BUSINESS_TRANSFER_TAX_KEY,int(transfer_tax_percent))
        await self.settings.set_int(guild_id,cfg.BUSINESS_FACTION_BONUS_KEY,int(faction_bonus_percent))
        await self.settings.set_int(guild_id,cfg.BUSINESS_FACTION_XP_KEY,int(faction_xp_per_claim))

    async def ensure_catalog(self, guild_id: int) -> None:
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            for item in cfg.PROPERTY_TEMPLATES:
                await conn.execute(
                    """INSERT OR IGNORE INTO business_properties
                       (guild_id,template_key,name,emoji,category,city,district,street,base_price,base_hourly_revenue,hourly_upkeep,max_workers,level,reputation,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,0,?)""",
                    (guild_id, item.key, item.name, item.emoji, item.category, item.city, item.district, item.street, item.base_price, item.hourly_revenue, item.hourly_upkeep, item.max_workers, now),
                )
            await conn.commit()

    async def _require_enabled(self, guild_id: int) -> BusinessSettings:
        settings = await self.get_settings(guild_id)
        if not settings.enabled:
            raise ValueError("A Biznisz Empire ezen a szerveren ki van kapcsolva.")
        return settings

    async def eligibility(self, guild_id: int, user_id: int) -> dict[str, Any]:
        settings = await self.get_settings(guild_id)
        activity = await self.activity.profile(guild_id, user_id)
        prestige = await self.prestige.state(guild_id, user_id)
        has_license = await self.has_license(guild_id, user_id)
        return {
            "enabled": settings.enabled,
            "activity_level": activity.level,
            "required_activity_level": settings.required_activity_level,
            "prestige": prestige.rank,
            "required_prestige": settings.required_prestige,
            "has_license": has_license,
            "license_price": settings.license_price,
            "eligible": settings.enabled and activity.level >= settings.required_activity_level and prestige.rank >= settings.required_prestige,
        }

    async def has_license(self, guild_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute("SELECT 1 FROM business_licenses WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            return await cur.fetchone() is not None

    async def buy_license(self, guild_id: int, user_id: int) -> int:
        settings = await self._require_enabled(guild_id)
        eligible = await self.eligibility(guild_id, user_id)
        if eligible["has_license"]:
            raise ValueError("Már van permanent Business License-ed.")
        if int(eligible["activity_level"]) < settings.required_activity_level:
            raise ValueError(f"Ehhez legalább Activity Level {settings.required_activity_level} kell.")
        if int(eligible["prestige"]) < settings.required_prestige:
            raise ValueError(f"Ehhez legalább Prestige {settings.required_prestige} kell.")
        await self.db.ensure_user(guild_id, user_id)
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            wallet = int((await cur.fetchone())[0])
            if wallet < settings.license_price:
                await conn.rollback()
                raise ValueError("Nincs elég pénzed a Business License-re.")
            cur = await conn.execute("SELECT 1 FROM business_licenses WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            if await cur.fetchone() is not None:
                await conn.rollback()
                raise ValueError("Már van permanent Business License-ed.")
            await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (settings.license_price, settings.license_price, guild_id, user_id))
            await conn.execute("INSERT INTO business_licenses(guild_id,user_id,purchased_at) VALUES(?,?,?)", (guild_id, user_id, now))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, user_id, -settings.license_price, "business_license", now))
            await conn.commit()
        await self.stats.add(guild_id, user_id, "business.license.spent", settings.license_price)
        return settings.license_price

    async def property_cap(self, guild_id: int, user_id: int) -> int:
        settings = await self.get_settings(guild_id)
        prestige = (await self.prestige.state(guild_id, user_id)).rank
        bonus = prestige // max(1, settings.prestige_step)
        return min(settings.absolute_cap, settings.base_property_cap + bonus)

    async def properties(self, guild_id: int, *, owner_id: int | None = None, available_only: bool = False) -> list[dict[str, Any]]:
        await self.ensure_catalog(guild_id)
        query = """SELECT property_id,template_key,name,emoji,category,city,district,street,base_price,base_hourly_revenue,hourly_upkeep,max_workers,owner_id,level,reputation,last_claim_at,acquired_at
                   FROM business_properties WHERE guild_id=?"""
        params: list[Any] = [guild_id]
        if owner_id is not None:
            query += " AND owner_id=?"
            params.append(owner_id)
        if available_only:
            query += " AND owner_id IS NULL"
        query += " ORDER BY base_price ASC,property_id ASC"
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(query, tuple(params))
            rows = await cur.fetchall()
        keys = ["property_id","template_key","name","emoji","category","city","district","street","base_price","base_hourly_revenue","hourly_upkeep","max_workers","owner_id","level","reputation","last_claim_at","acquired_at"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    async def get_property(self, guild_id: int, property_id: int) -> dict[str, Any] | None:
        await self.ensure_catalog(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT property_id,template_key,name,emoji,category,city,district,street,base_price,base_hourly_revenue,hourly_upkeep,max_workers,owner_id,level,reputation,last_claim_at,acquired_at
                   FROM business_properties WHERE guild_id=? AND property_id=?""",
                (guild_id, property_id),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        keys = ["property_id","template_key","name","emoji","category","city","district","street","base_price","base_hourly_revenue","hourly_upkeep","max_workers","owner_id","level","reputation","last_claim_at","acquired_at"]
        return dict(zip(keys, row, strict=True))

    async def _check_owner_caps_tx(self, conn, guild_id: int, buyer_id: int, city: str, settings: BusinessSettings) -> None:
        cur = await conn.execute("SELECT prestige_rank FROM user_prestige WHERE guild_id=? AND user_id=?", (guild_id, buyer_id))
        prestige_row = await cur.fetchone()
        prestige = int(prestige_row[0]) if prestige_row else 0
        cap = min(settings.absolute_cap, settings.base_property_cap + prestige // max(1, settings.prestige_step))
        cur = await conn.execute("SELECT COUNT(*) FROM business_properties WHERE guild_id=? AND owner_id=?", (guild_id, buyer_id))
        owned = int((await cur.fetchone())[0])
        if owned >= cap:
            raise ValueError(f"Elérted a property limitedet: {owned}/{cap}.")
        cur = await conn.execute("SELECT COUNT(*) FROM business_properties WHERE guild_id=? AND owner_id=? AND city=?", (guild_id, buyer_id, city))
        city_owned = int((await cur.fetchone())[0])
        if city_owned >= settings.city_cap:
            raise ValueError(f"Anti-monopoly: {city} városban maximum {settings.city_cap} propertyd lehet.")

    async def buy_property(self, guild_id: int, user_id: int, property_id: int) -> dict[str, Any]:
        settings = await self._require_enabled(guild_id)
        if not await self.has_license(guild_id, user_id):
            raise ValueError("Előbb vásárolj permanent Business License-t.")
        await self.ensure_catalog(guild_id)
        await self.db.ensure_user(guild_id, user_id)
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT name,emoji,city,base_price,owner_id FROM business_properties WHERE guild_id=? AND property_id=?", (guild_id, property_id))
            row = await cur.fetchone()
            if row is None:
                await conn.rollback(); raise ValueError("Nincs ilyen property.")
            name, emoji, city, price, owner_id = str(row[0]), str(row[1]), str(row[2]), int(row[3]), row[4]
            if owner_id is not None:
                await conn.rollback(); raise ValueError("Ezt a propertyt már birtokolja valaki. Küldj neki ajánlatot.")
            try:
                await self._check_owner_caps_tx(conn, guild_id, user_id, city, settings)
            except ValueError:
                await conn.rollback(); raise
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            wallet = int((await cur.fetchone())[0])
            if wallet < price:
                await conn.rollback(); raise ValueError("Nincs elég pénzed a property megvásárlásához.")
            await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (price, price, guild_id, user_id))
            await conn.execute("UPDATE business_properties SET owner_id=?,level=1,reputation=0,last_claim_at=?,acquired_at=? WHERE guild_id=? AND property_id=? AND owner_id IS NULL", (user_id, now, now, guild_id, property_id))
            await conn.execute("INSERT INTO business_transactions(guild_id,property_id,user_id,amount,kind,created_at) VALUES(?,?,?,?,?,?)", (guild_id, property_id, user_id, -price, "world_purchase", now))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, user_id, -price, f"business_property_buy:{property_id}", now))
            await conn.commit()
        await self.stats.add(guild_id, user_id, "business.property.spent", price)
        await self.stats.increment(guild_id, user_id, "business.property.bought")
        return {"property_id": property_id, "name": name, "emoji": emoji, "city": city, "price": price}

    async def active_workers(self, guild_id: int, property_id: int) -> list[dict[str, Any]]:
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("DELETE FROM business_workers WHERE guild_id=? AND property_id=? AND expires_at<=?", (guild_id, property_id, now))
            cur = await conn.execute(
                """SELECT id,worker_key,name,tier,revenue_bonus_percent,wage_per_hour,hired_at,expires_at
                   FROM business_workers WHERE guild_id=? AND property_id=? AND expires_at>? ORDER BY revenue_bonus_percent DESC,id ASC""",
                (guild_id, property_id, now),
            )
            rows = await cur.fetchall()
            await conn.commit()
        keys = ["id","worker_key","name","tier","revenue_bonus_percent","wage_per_hour","hired_at","expires_at"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    async def worker_pool(self, guild_id: int, *, now: datetime | None = None) -> list[cfg.WorkerDefinition]:
        now = now or self._now()
        seed = f"{guild_id}:{now.date().isoformat()}:yoru-business-workers"
        rng = random.Random(seed)
        workers = list(cfg.WORKERS)
        rng.shuffle(workers)
        return workers[:6]

    async def hire_worker(self, guild_id: int, user_id: int, property_id: int, worker_key: str) -> dict[str, Any]:
        settings = await self._require_enabled(guild_id)
        worker = cfg.WORKER_BY_KEY.get(worker_key)
        if worker is None:
            raise ValueError("Ez a dolgozó nincs a mai rotációban.")
        if worker.key not in {item.key for item in await self.worker_pool(guild_id)}:
            raise ValueError("Ez a dolgozó már nincs a mai rotációban.")
        await self.db.ensure_user(guild_id, user_id)
        now = self._now()
        expires = now + timedelta(days=settings.worker_contract_days)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT owner_id,max_workers,level FROM business_properties WHERE guild_id=? AND property_id=?", (guild_id, property_id))
            row = await cur.fetchone()
            if row is None or row[0] is None or int(row[0]) != user_id:
                await conn.rollback(); raise ValueError("Csak a saját propertydre vehetsz fel dolgozót.")
            slots = int(row[1]) + max(0, int(row[2]) - 1) // 2
            cur = await conn.execute("SELECT COUNT(*) FROM business_workers WHERE guild_id=? AND property_id=? AND expires_at>?", (guild_id, property_id, now.isoformat()))
            active = int((await cur.fetchone())[0])
            if active >= slots:
                await conn.rollback(); raise ValueError(f"Nincs szabad worker slot ({active}/{slots}).")
            cur = await conn.execute("SELECT 1 FROM business_workers WHERE guild_id=? AND property_id=? AND worker_key=? AND expires_at>?", (guild_id, property_id, worker.key, now.isoformat()))
            if await cur.fetchone() is not None:
                await conn.rollback(); raise ValueError("Ez a dolgozó már ezen a propertyn dolgozik.")
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            wallet = int((await cur.fetchone())[0])
            if wallet < worker.hire_fee:
                await conn.rollback(); raise ValueError("Nincs elég pénzed a felvételi díjra.")
            await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (worker.hire_fee, worker.hire_fee, guild_id, user_id))
            await conn.execute(
                """INSERT INTO business_workers(guild_id,property_id,owner_id,worker_key,name,tier,revenue_bonus_percent,wage_per_hour,hired_at,expires_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (guild_id, property_id, user_id, worker.key, worker.name, worker.tier, worker.revenue_bonus_percent, worker.wage_per_hour, now.isoformat(), expires.isoformat()),
            )
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, user_id, -worker.hire_fee, f"business_worker_hire:{property_id}:{worker.key}", now.isoformat()))
            await conn.commit()
        await self.stats.add(guild_id, user_id, "business.worker.spent", worker.hire_fee)
        return {"worker": worker, "expires_at": expires, "slots": slots}

    async def claim_preview(self, guild_id: int, user_id: int, property_id: int, *, now: datetime | None = None) -> dict[str, Any]:
        settings = await self.get_settings(guild_id)
        prop = await self.get_property(guild_id, property_id)
        if prop is None or prop["owner_id"] is None or int(prop["owner_id"]) != user_id:
            raise ValueError("Ez nem a te propertyd.")
        now = now or self._now()
        start = self._dt(prop.get("last_claim_at")) or self._dt(prop.get("acquired_at")) or now
        elapsed_hours = max(0.0, min(float(settings.offline_cap_hours), (now - start).total_seconds() / 3600))
        workers = await self.active_workers(guild_id, property_id)
        worker_bonus = sum(int(item["revenue_bonus_percent"]) for item in workers)
        worker_wages = sum(int(item["wage_per_hour"]) for item in workers)
        level = int(prop["level"])
        reputation = int(prop["reputation"])
        level_bonus = 15 * max(0, level - 1)
        reputation_bonus = min(25, reputation // 40)
        total_bonus_percent = worker_bonus + level_bonus + reputation_bonus
        gross_hourly = int(int(prop["base_hourly_revenue"]) * settings.income_multiplier_percent / 100)
        gross = int(gross_hourly * elapsed_hours * (1 + total_bonus_percent / 100))
        upkeep_hourly = int(prop["hourly_upkeep"]) + worker_wages
        upkeep = int(upkeep_hourly * elapsed_hours)
        tax = int(gross * settings.tax_percent / 100)
        net = max(0, gross - upkeep - tax)
        faction_bonus = 0
        membership = await self.crew.get_membership(guild_id, user_id)
        if membership is not None and net > 0:
            faction_bonus = int(net * settings.faction_bonus_percent / 100)
        return {
            "property": prop,
            "elapsed_hours": elapsed_hours,
            "workers": workers,
            "worker_bonus_percent": worker_bonus,
            "level_bonus_percent": level_bonus,
            "reputation_bonus_percent": reputation_bonus,
            "gross": gross,
            "upkeep": upkeep,
            "tax": tax,
            "net": net,
            "faction_bonus": faction_bonus,
            "total_payout": net + faction_bonus,
            "settings": settings,
        }

    async def claim(self, guild_id: int, user_id: int, property_id: int) -> dict[str, Any]:
        await self._require_enabled(guild_id)
        preview = await self.claim_preview(guild_id, user_id, property_id)
        if preview["elapsed_hours"] < 0.05:
            raise ValueError("Még alig termelt a biznisz. Várj legalább pár percet.")
        now = self._now().isoformat()
        payout = int(preview["total_payout"])
        rep_gain = max(1, min(20, int(preview["elapsed_hours"] * 2) + 1)) if payout > 0 else 0
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT owner_id,last_claim_at,reputation FROM business_properties WHERE guild_id=? AND property_id=?", (guild_id, property_id))
            row = await cur.fetchone()
            if row is None or row[0] is None or int(row[0]) != user_id:
                await conn.rollback(); raise ValueError("Ez már nem a te propertyd.")
            # Reject a stale double-click if another claim changed last_claim_at.
            if str(row[1] or "") != str(preview["property"].get("last_claim_at") or ""):
                await conn.rollback(); raise ValueError("A bevételt közben már begyűjtötték. Frissítsd a panelt.")
            if payout > 0:
                await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?", (payout, payout, guild_id, user_id))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, user_id, payout, f"business_claim:{property_id}", now))
                await conn.execute("INSERT INTO business_transactions(guild_id,property_id,user_id,amount,kind,created_at) VALUES(?,?,?,?,?,?)", (guild_id, property_id, user_id, payout, "claim", now))
            new_rep = min(cfg.MAX_REPUTATION, int(row[2]) + rep_gain)
            await conn.execute("UPDATE business_properties SET last_claim_at=?,reputation=? WHERE guild_id=? AND property_id=?", (now, new_rep, guild_id, property_id))
            membership = await self.crew.get_membership(guild_id, user_id)
            if membership is not None and int(preview["faction_bonus"]) > 0:
                # Matching dividend to the Faction bank. This does not come out of the player's payout.
                await conn.execute("UPDATE crews SET bank=bank+? WHERE guild_id=? AND crew_id=?", (int(preview["faction_bonus"]), guild_id, membership.crew.crew_id))
            await conn.commit()
        if payout > 0:
            await self.stats.add(guild_id, user_id, "business.earned", payout)
            await self.stats.increment(guild_id, user_id, "business.claims")
        if await self.crew.get_membership(guild_id, user_id) is not None:
            await self.factions.add_xp_for_member(guild_id, user_id, preview["settings"].faction_xp_per_claim, source="business")
        preview["reputation_gain"] = rep_gain
        preview["new_reputation"] = min(cfg.MAX_REPUTATION, int(preview["property"]["reputation"]) + rep_gain)
        return preview

    async def upgrade_property(self, guild_id: int, user_id: int, property_id: int) -> dict[str, Any]:
        await self._require_enabled(guild_id)
        await self.db.ensure_user(guild_id, user_id)
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT name,owner_id,level,reputation,base_price FROM business_properties WHERE guild_id=? AND property_id=?", (guild_id, property_id))
            row = await cur.fetchone()
            if row is None or row[1] is None or int(row[1]) != user_id:
                await conn.rollback(); raise ValueError("Ez nem a te propertyd.")
            name, level, reputation, base_price = str(row[0]), int(row[2]), int(row[3]), int(row[4])
            if level >= cfg.MAX_BUSINESS_LEVEL:
                await conn.rollback(); raise ValueError("Ez a biznisz már max szintű.")
            needed_rep = cfg.upgrade_required_reputation(level)
            if reputation < needed_rep:
                await conn.rollback(); raise ValueError(f"A következő fejlesztéshez legalább {needed_rep} Reputation kell.")
            cost = cfg.upgrade_cost(base_price, level)
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            wallet = int((await cur.fetchone())[0])
            if wallet < cost:
                await conn.rollback(); raise ValueError("Nincs elég pénzed a fejlesztéshez.")
            await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (cost, cost, guild_id, user_id))
            await conn.execute("UPDATE business_properties SET level=level+1 WHERE guild_id=? AND property_id=?", (guild_id, property_id))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, user_id, -cost, f"business_upgrade:{property_id}:{level+1}", now))
            await conn.commit()
        await self.stats.add(guild_id, user_id, "business.upgrade.spent", cost)
        return {"name": name, "old_level": level, "new_level": level + 1, "cost": cost}

    async def expire_offers(self, guild_id: int) -> int:
        now = self._now().isoformat()
        refunded = 0
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT offer_id,buyer_id,amount FROM business_offers WHERE guild_id=? AND status='pending' AND expires_at<=?", (guild_id, now))
            rows = await cur.fetchall()
            for offer_id, buyer_id, amount in rows:
                amount = int(amount); buyer_id = int(buyer_id); offer_id = int(offer_id)
                await conn.execute("UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?", (amount, amount, guild_id, buyer_id))
                await conn.execute("UPDATE business_offers SET status='expired',resolved_at=? WHERE offer_id=?", (now, offer_id))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, buyer_id, amount, f"business_offer_refund_expired:{offer_id}", now))
                refunded += 1
            await conn.commit()
        return refunded

    async def create_offer(self, guild_id: int, buyer_id: int, property_id: int, amount: int) -> dict[str, Any]:
        settings = await self._require_enabled(guild_id)
        if not await self.has_license(guild_id, buyer_id):
            raise ValueError("Ajánlathoz Business License kell.")
        amount = int(amount)
        if amount < 1_000_000:
            raise ValueError("A minimum property offer 1 000 000.")
        await self.expire_offers(guild_id)
        await self.db.ensure_user(guild_id, buyer_id)
        now = self._now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT name,city,owner_id FROM business_properties WHERE guild_id=? AND property_id=?", (guild_id, property_id))
            row = await cur.fetchone()
            if row is None or row[2] is None:
                await conn.rollback(); raise ValueError("Erre a propertyre nem kell player offer; a világpiacon közvetlenül megvehető.")
            seller_id = int(row[2])
            if seller_id == buyer_id:
                await conn.rollback(); raise ValueError("Saját propertydre nem tehetsz ajánlatot.")
            try:
                await self._check_owner_caps_tx(conn, guild_id, buyer_id, str(row[1]), settings)
            except ValueError:
                await conn.rollback(); raise
            cur = await conn.execute("SELECT 1 FROM business_offers WHERE guild_id=? AND property_id=? AND buyer_id=? AND status='pending'", (guild_id, property_id, buyer_id))
            if await cur.fetchone() is not None:
                await conn.rollback(); raise ValueError("Már van aktív ajánlatod erre a propertyre.")
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (guild_id, buyer_id))
            wallet = int((await cur.fetchone())[0])
            if wallet < amount:
                await conn.rollback(); raise ValueError("Nincs elég pénzed az escrow ajánlathoz.")
            await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?", (amount, amount, guild_id, buyer_id))
            cur = await conn.execute(
                """INSERT INTO business_offers(guild_id,property_id,seller_id,buyer_id,amount,status,created_at,expires_at)
                   VALUES(?,?,?,?,?,'pending',?,?)""",
                (guild_id, property_id, seller_id, buyer_id, amount, now.isoformat(), (now + timedelta(hours=settings.property_offer_hours)).isoformat()),
            )
            offer_id = int(cur.lastrowid)
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, buyer_id, -amount, f"business_offer_escrow:{offer_id}", now.isoformat()))
            await conn.commit()
        return {"offer_id": offer_id, "property_id": property_id, "property_name": str(row[0]), "seller_id": seller_id, "buyer_id": buyer_id, "amount": amount}

    async def offers(self, guild_id: int, user_id: int, *, incoming: bool = True) -> list[dict[str, Any]]:
        await self.expire_offers(guild_id)
        field = "o.seller_id" if incoming else "o.buyer_id"
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                f"""SELECT o.offer_id,o.property_id,p.name,p.emoji,o.seller_id,o.buyer_id,o.amount,o.status,o.created_at,o.expires_at
                    FROM business_offers o JOIN business_properties p ON p.property_id=o.property_id AND p.guild_id=o.guild_id
                    WHERE o.guild_id=? AND {field}=? AND o.status='pending' ORDER BY o.amount DESC,o.created_at ASC""",
                (guild_id, user_id),
            )
            rows = await cur.fetchall()
        keys = ["offer_id","property_id","property_name","emoji","seller_id","buyer_id","amount","status","created_at","expires_at"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    async def resolve_offer(self, guild_id: int, seller_id: int, offer_id: int, *, accept: bool) -> dict[str, Any]:
        settings = await self._require_enabled(guild_id)
        await self.expire_offers(guild_id)
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                """SELECT o.property_id,o.seller_id,o.buyer_id,o.amount,o.status,p.name,p.city,p.owner_id
                   FROM business_offers o JOIN business_properties p ON p.property_id=o.property_id AND p.guild_id=o.guild_id
                   WHERE o.guild_id=? AND o.offer_id=?""",
                (guild_id, offer_id),
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback(); raise ValueError("Nincs ilyen offer.")
            property_id, offer_seller, buyer_id, amount, status, name, city, current_owner = int(row[0]), int(row[1]), int(row[2]), int(row[3]), str(row[4]), str(row[5]), str(row[6]), row[7]
            if offer_seller != seller_id or current_owner is None or int(current_owner) != seller_id:
                await conn.rollback(); raise ValueError("Ezt az ajánlatot nem te kezelheted.")
            if status != "pending":
                await conn.rollback(); raise ValueError("Ez az ajánlat már nem aktív.")
            if not accept:
                await conn.execute("UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?", (amount, amount, guild_id, buyer_id))
                await conn.execute("UPDATE business_offers SET status='rejected',resolved_at=? WHERE offer_id=?", (now, offer_id))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, buyer_id, amount, f"business_offer_refund_rejected:{offer_id}", now))
                await conn.commit()
                return {"accepted": False, "property_id": property_id, "property_name": name, "buyer_id": buyer_id, "amount": amount}
            try:
                await self._check_owner_caps_tx(conn, guild_id, buyer_id, city, settings)
            except ValueError:
                await conn.rollback(); raise
            transfer_tax = max(0, amount * settings.transfer_tax_percent // 100)
            seller_net = amount - transfer_tax
            await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?", (seller_net, seller_net, guild_id, seller_id))
            # A property teljes üzleti állapota együtt kerül átadásra: level, reputation
            # és az aktív worker szerződések is a propertyhez tartoznak, nem a régi tulajhoz.
            await conn.execute("UPDATE business_properties SET owner_id=?,last_claim_at=?,acquired_at=? WHERE guild_id=? AND property_id=?", (buyer_id, now, now, guild_id, property_id))
            await conn.execute("UPDATE business_offers SET status='accepted',resolved_at=? WHERE offer_id=?", (now, offer_id))
            # Refund all other pending escrow offers on the sold property.
            cur = await conn.execute("SELECT offer_id,buyer_id,amount FROM business_offers WHERE guild_id=? AND property_id=? AND status='pending' AND offer_id<>?", (guild_id, property_id, offer_id))
            others = await cur.fetchall()
            for other_id, other_buyer, other_amount in others:
                other_id = int(other_id); other_buyer = int(other_buyer); other_amount = int(other_amount)
                await conn.execute("UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?", (other_amount, other_amount, guild_id, other_buyer))
                await conn.execute("UPDATE business_offers SET status='cancelled',resolved_at=? WHERE offer_id=?", (now, other_id))
                await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, other_buyer, other_amount, f"business_offer_refund_sold:{other_id}", now))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, seller_id, seller_net, f"business_property_sale:{property_id}", now))
            await conn.execute("INSERT INTO business_transactions(guild_id,property_id,user_id,amount,kind,created_at) VALUES(?,?,?,?,?,?)", (guild_id, property_id, seller_id, seller_net, "player_sale", now))
            await conn.commit()
        await self.stats.add(guild_id, seller_id, "business.property.sale_earned", seller_net)
        await self.stats.increment(guild_id, buyer_id, "business.property.bought_player")
        return {"accepted": True, "property_id": property_id, "property_name": name, "buyer_id": buyer_id, "amount": amount, "transfer_tax": transfer_tax, "seller_net": seller_net}

    async def cancel_offer(self, guild_id: int, buyer_id: int, offer_id: int) -> int:
        await self.expire_offers(guild_id)
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT amount,status,buyer_id FROM business_offers WHERE guild_id=? AND offer_id=?", (guild_id, offer_id))
            row = await cur.fetchone()
            if row is None or int(row[2]) != buyer_id:
                await conn.rollback(); raise ValueError("Ezt az ajánlatot nem te kezelheted.")
            if str(row[1]) != "pending":
                await conn.rollback(); raise ValueError("Ez az ajánlat már nem aktív.")
            amount = int(row[0])
            await conn.execute("UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?", (amount, amount, guild_id, buyer_id))
            await conn.execute("UPDATE business_offers SET status='cancelled',resolved_at=? WHERE offer_id=?", (now, offer_id))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)", (guild_id, buyer_id, amount, f"business_offer_refund_cancelled:{offer_id}", now))
            await conn.commit()
        return amount

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict[str, int]]:
        await self.ensure_catalog(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT owner_id,COUNT(*),COALESCE(SUM(base_price * (100 + (level-1)*25) / 100),0),COALESCE(SUM(reputation),0)
                   FROM business_properties WHERE guild_id=? AND owner_id IS NOT NULL
                   GROUP BY owner_id ORDER BY 3 DESC,4 DESC LIMIT ?""",
                (guild_id, max(1, min(25, int(limit)))),
            )
            rows = await cur.fetchall()
        return [{"user_id": int(r[0]), "properties": int(r[1]), "empire_value": int(r[2]), "reputation": int(r[3])} for r in rows]
