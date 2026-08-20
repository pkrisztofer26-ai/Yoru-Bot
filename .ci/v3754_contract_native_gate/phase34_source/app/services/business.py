# STATIC_CONTRACT: event_type="business_delivery_completed"
# STATIC_CONTRACT: "business_delivery"
# STATIC_CONTRACT: business_offers
# STATIC_CONTRACT: async def create_offer
# STATIC_CONTRACT: business_property_purchased
# STATIC_CONTRACT: business_property_purchased(
from __future__ import annotations
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from app import db_backend as aiosqlite
from app import business_config as cfg
from app import character_config
from app import npc_favor_config
from app.services.server_settings import ServerSettingsService
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService
from app.ui import money

@dataclass(frozen=True)
class BusinessSettings:
    enabled: bool
    license_price: int
    tax_percent: int
    offline_cap_hours: int
    base_property_cap: int
    absolute_cap: int
    city_cap: int
    income_multiplier_percent: int
    worker_contract_days: int
    property_offer_hours: int
    transfer_tax_percent: int

@dataclass(frozen=True)
class BusinessLicensePurchaseResult:
    paid: int
    base_price: int
    discount_saved: int = 0
    favor_effect_key: str | None = None

class BusinessService:

    def __init__(self, database, statistics, world=None, characters=None, memory: ConsequenceMemoryService | None=None, memory_adapters: MemoryAdapterService | None=None) -> None:
        self.db = database
        self.stats = statistics
        self.world = world
        self.characters = characters
        self.memory = memory
        self.memory_adapters = memory_adapters
        self.settings = ServerSettingsService(database)
        self.bot = None
        self.contracts = None

    def bind_contracts(self, contract_service) -> None:
        self.contracts = contract_service

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def get_settings(self, guild_id: int) -> BusinessSettings:
        get_int = self.settings.get_int
        license_price = await get_int(guild_id, cfg.BUSINESS_LICENSE_PRICE_KEY)
        tax = await get_int(guild_id, cfg.BUSINESS_TAX_PERCENT_KEY)
        offline = await get_int(guild_id, cfg.BUSINESS_OFFLINE_CAP_HOURS_KEY)
        base_cap = await get_int(guild_id, cfg.BUSINESS_BASE_PROPERTY_CAP_KEY)
        absolute_cap = await get_int(guild_id, cfg.BUSINESS_ABSOLUTE_CAP_KEY)
        city_cap = await get_int(guild_id, cfg.BUSINESS_CITY_CAP_KEY)
        multiplier = await get_int(guild_id, cfg.BUSINESS_INCOME_MULTIPLIER_KEY)
        worker_days = await get_int(guild_id, cfg.BUSINESS_WORKER_DAYS_KEY)
        offer_hours = await get_int(guild_id, cfg.BUSINESS_OFFER_HOURS_KEY)
        transfer_tax = await get_int(guild_id, cfg.BUSINESS_TRANSFER_TAX_KEY)
        return BusinessSettings(enabled=await self.settings.get_bool(guild_id, cfg.BUSINESS_ENABLED_KEY, cfg.DEFAULT_ENABLED), license_price=cfg.DEFAULT_LICENSE_PRICE if license_price is None else max(cfg.MIN_LICENSE_PRICE, min(cfg.MAX_LICENSE_PRICE, int(license_price))), tax_percent=cfg.DEFAULT_TAX_PERCENT if tax is None else max(cfg.MIN_TAX_PERCENT, min(cfg.MAX_TAX_PERCENT, int(tax))), offline_cap_hours=cfg.DEFAULT_OFFLINE_CAP_HOURS if offline is None else max(cfg.MIN_OFFLINE_CAP_HOURS, min(cfg.MAX_OFFLINE_CAP_HOURS, int(offline))), base_property_cap=cfg.DEFAULT_BASE_PROPERTY_CAP if base_cap is None else max(cfg.MIN_PROPERTY_CAP, min(cfg.MAX_PROPERTY_CAP, int(base_cap))), absolute_cap=cfg.DEFAULT_ABSOLUTE_CAP if absolute_cap is None else max(cfg.MIN_PROPERTY_CAP, min(cfg.MAX_PROPERTY_CAP, int(absolute_cap))), city_cap=cfg.DEFAULT_CITY_CAP if city_cap is None else max(1, min(cfg.MAX_PROPERTY_CAP, int(city_cap))), income_multiplier_percent=cfg.DEFAULT_INCOME_MULTIPLIER_PERCENT if multiplier is None else max(cfg.MIN_INCOME_MULTIPLIER_PERCENT, min(cfg.MAX_INCOME_MULTIPLIER_PERCENT, int(multiplier))), worker_contract_days=cfg.DEFAULT_WORKER_CONTRACT_DAYS if worker_days is None else max(cfg.MIN_WORKER_CONTRACT_DAYS, min(cfg.MAX_WORKER_CONTRACT_DAYS, int(worker_days))), property_offer_hours=cfg.PROPERTY_OFFER_HOURS if offer_hours is None else max(1, min(168, int(offer_hours))), transfer_tax_percent=cfg.PROPERTY_TRANSFER_TAX_PERCENT if transfer_tax is None else max(0, min(50, int(transfer_tax))))

    async def _require_enabled(self, guild_id: int) -> BusinessSettings:
        settings = await self.get_settings(guild_id)
        if not settings.enabled:
            raise ValueError('A Vállalkozások rendszer ezen a szerveren ki van kapcsolva.')
        return settings

    async def eligibility(self, guild_id: int, user_id: int) -> dict[str, Any]:
        settings = await self.get_settings(guild_id)
        has_license = await self.has_license(guild_id, user_id)
        return {'enabled': settings.enabled, 'has_license': has_license, 'license_price': settings.license_price, 'eligible': settings.enabled}

    async def has_license(self, guild_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute('SELECT 1 FROM business_licenses WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            return await cur.fetchone() is not None

    async def license_quote(self, guild_id: int, user_id: int) -> BusinessLicensePurchaseResult:
        settings = await self._require_enabled(guild_id)
        base_price = int(settings.license_price)
        discount_saved = 0
        effect_key: str | None = None
        if self.memory is not None:
            effect = npc_favor_config.effect('bence_business_license_discount')
            voucher = await self.memory.active_favor_effect(guild_id, user_id, effect_key=effect.key, subject_key=effect.npc_key)
            if voucher is not None:
                discount_saved = effect.savings(base_price)
                effect_key = effect.key
        return BusinessLicensePurchaseResult(paid=max(0, base_price - discount_saved), base_price=base_price, discount_saved=discount_saved, favor_effect_key=effect_key)

    async def buy_license_result(self, guild_id: int, user_id: int) -> BusinessLicensePurchaseResult:
        settings = await self._require_enabled(guild_id)
        eligible = await self.eligibility(guild_id, user_id)
        if eligible['has_license']:
            raise ValueError('Már rendelkezel vállalkozói engedéllyel.')
        await self.db.ensure_user(guild_id, user_id)
        now = self._now().isoformat()
        base_price = int(settings.license_price)
        price = base_price
        discount_saved = 0
        favor_effect_key: str | None = None
        favor_fact = None
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            if self.memory is not None:
                effect = npc_favor_config.effect('bence_business_license_discount')
                favor_fact = await self.memory.active_favor_effect_tx(conn, guild_id, user_id, effect_key=effect.key, subject_key=effect.npc_key)
                if favor_fact is not None:
                    discount_saved = effect.savings(base_price)
                    price = max(0, base_price - discount_saved)
                    favor_effect_key = effect.key
            cur = await conn.execute('SELECT wallet FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            wallet = int((await cur.fetchone())[0])
            if wallet < price:
                await conn.rollback()
                raise ValueError('Nincs elég pénzed a vállalkozói engedélyre.')
            cur = await conn.execute('SELECT 1 FROM business_licenses WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            if await cur.fetchone() is not None:
                await conn.rollback()
                raise ValueError('Már rendelkezel vállalkozói engedéllyel.')
            await conn.execute('UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?', (price, price, guild_id, user_id))
            await conn.execute('INSERT INTO business_licenses(guild_id,user_id,purchased_at) VALUES(?,?,?)', (guild_id, user_id, now))
            await conn.execute('INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)', (guild_id, user_id, -price, 'business_license', now))
            if favor_fact is not None:
                consumed = await self.memory.consume_active_favor_effect_tx(conn, memory_id=favor_fact.memory_id)
                if not consumed:
                    await conn.rollback()
                    raise RuntimeError('A vállalkozói kedvezmény közben már nem volt elérhető; a vásárlás nem kerülhetett félállapotba.')
            await conn.commit()
        await self.stats.add(guild_id, user_id, 'business.license.spent', price)
        if self.memory_adapters is not None:
            try:
                await self.memory_adapters.business_license_purchased(guild_id, user_id, paid=price, base_price=base_price, discount_saved=discount_saved, favor_effect_key=favor_effect_key, occurred_at=now)
            except Exception:
                pass
        return BusinessLicensePurchaseResult(paid=price, base_price=base_price, discount_saved=discount_saved, favor_effect_key=favor_effect_key)

    async def deliver_contract_supply(self, guild_id: int, user_id: int, contract_id: int, objective_id: int) -> dict[str, Any]:
        """Consume real inventory into a player-owned business and emit one stable delivery event."""
        if self.contracts is None:
            raise RuntimeError('A Megbízások rendszer nincs bekötve.')
        contract = await self.contracts.get_contract(guild_id, contract_id)
        if contract is None or contract.status != 'active' or contract.assignee_id != int(user_id):
            raise ValueError('Ez a vállalkozási szállítás nem teljesíthető innen.')
        source_state = await self.contracts.source_state(guild_id, contract_id) if contract.creator_id is None else None
        if contract.creator_id is None:
            if contract.source_type not in {'public', 'private'} or not source_state:
                raise ValueError('Ehhez a Yoru-megbízáshoz nincs érvényes üzleti cél.')
            target_user_id = int(source_state.get('target_user_id') or 0)
            if target_user_id != int(user_id):
                raise ValueError('Ez az üzleti megbízás nem neked szól.')
        objectives = await self.contracts.objectives(guild_id, contract_id)
        objective = next((row for row in objectives if int(row.get('objective_id') or 0) == int(objective_id)), None)
        if objective is None or objective.get('objective_type') != 'business_delivery' or objective.get('status') != 'pending':
            raise ValueError('Ez a vállalkozási szállítás már nem aktív.')
        target = str(objective.get('target_ref') or '').lower()
        if not target.startswith('property:'):
            raise ValueError('A vállalkozási szállítás célja hibás.')
        try:
            property_id = int(target.split(':', 1)[1])
        except ValueError as exc:
            raise ValueError('A vállalkozási szállítás célja hibás.') from exc
        metadata = dict(objective.get('metadata') or {})
        item_id = str(metadata.get('item_id') or '').strip().lower()
        quantity = max(1, int(metadata.get('quantity') or objective.get('required_value') or 1))
        if not item_id:
            raise ValueError('A vállalkozási szállítás tárgya nincs meghatározva.')
        source_ref = f'contract-business:{int(contract_id)}:{int(objective_id)}'
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            try:
                cur = await conn.execute('SELECT owner_id FROM business_properties WHERE guild_id=? AND property_id=?', (guild_id, property_id))
                row = await cur.fetchone()
                if row is None:
                    raise ValueError('A célvállalkozás már nem létezik.')
                expected_owner_id = int(contract.creator_id) if contract.creator_id is not None else int(user_id)
                if int(row[0]) != expected_owner_id:
                    raise ValueError('A célvállalkozás nem a megbízás jogosult tulajdonosához tartozik.')
                cur = await conn.execute('SELECT delivery_id,item_id,quantity FROM business_delivery_history WHERE guild_id=? AND source_ref=?', (guild_id, source_ref))
                replay = await cur.fetchone()
                if replay is not None:
                    await conn.commit()
                    delivery_id = int(replay[0])
                    moved_item = str(replay[1])
                    moved_quantity = int(replay[2])
                else:
                    cur = await conn.execute('SELECT quantity FROM inventory WHERE guild_id=? AND user_id=? AND item_id=?', (guild_id, user_id, item_id))
                    inv = await cur.fetchone()
                    owned = int(inv[0]) if inv else 0
                    if owned < quantity:
                        raise ValueError('Nincs nálad elég a szükséges tárgyból a vállalkozási szállításhoz.')
                    if owned == quantity:
                        await conn.execute('DELETE FROM inventory WHERE guild_id=? AND user_id=? AND item_id=?', (guild_id, user_id, item_id))
                    else:
                        await conn.execute('UPDATE inventory SET quantity=quantity-? WHERE guild_id=? AND user_id=? AND item_id=?', (quantity, guild_id, user_id, item_id))
                    cur = await conn.execute('INSERT INTO business_delivery_history(guild_id,property_id,provider_user_id,item_id,quantity,source_ref,created_at)\n                           VALUES(?,?,?,?,?,?,?)', (guild_id, property_id, user_id, item_id, quantity, source_ref, now))
                    delivery_id = int(cur.lastrowid or 0)
                    moved_item = item_id
                    moved_quantity = quantity
                    await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        result = await self.contracts.record_matching_domain_event(guild_id, user_id, event_key=f'business_delivery:{delivery_id}', event_type='business_delivery_completed', target_ref=f'property:{property_id}', delta=moved_quantity, payload={'delivery_id': delivery_id, 'property_id': property_id, 'item_id': moved_item, 'quantity': moved_quantity})
        return {'delivery_id': delivery_id, 'item_id': moved_item, 'quantity': moved_quantity, 'contract': result}
