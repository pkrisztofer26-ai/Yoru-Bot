from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from typing import Any

from app import character_config as character_cfg
from app import db_backend as aiosqlite
from app import housing_config as cfg
from app import shop_config as shop_cfg
from app.database import Database
from app.services.characters import CharacterService
from app.services.memory_adapters import MemoryAdapterService

logger = logging.getLogger("vaultbot.housing")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class HousingState:
    guild_id: int
    user_id: int
    tier_key: str
    city_key: str
    acquired_at: str | None
    paid_until: str | None
    grace_until: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class HousingProperty:
    property_id: int
    guild_id: int
    user_id: int
    city_key: str
    tier_key: str
    purchase_price: int
    maintenance_paid_until: str
    maintenance_grace_until: str | None
    maintenance_debt: int
    last_opportunity_cycle: str | None
    status: str
    acquired_at: str
    upgraded_at: str | None
    updated_at: str
    sold_at: str | None
    sale_price: int | None


@dataclass(frozen=True, slots=True)
class HousingPurchaseResult:
    state: HousingState
    price: int
    wallet_used: int
    bank_used: int
    new_wallet: int
    new_bank: int
    property: HousingProperty | None = None


@dataclass(frozen=True, slots=True)
class HousingSaleResult:
    property_id: int
    city_key: str
    tier_key: str
    gross_value: int
    debt_settled: int
    received: int
    new_bank: int
    active_home_lost: bool


@dataclass(frozen=True, slots=True)
class HousingRelocationResult:
    from_city_key: str
    to_city_key: str
    state: HousingState
    activated_property: HousingProperty | None


@dataclass(frozen=True, slots=True)
class BillingResult:
    action: str
    guild_id: int
    user_id: int
    tier_key: str
    amount: int = 0
    grace_until: str | None = None
    property_id: int | None = None


@dataclass(frozen=True, slots=True)
class StorageItem:
    item_id: str
    name: str
    emoji: str
    quantity: int


@dataclass(frozen=True, slots=True)
class StorageTransferResult:
    item_id: str
    name: str
    emoji: str
    quantity: int
    stored_total: int
    capacity: int


@dataclass(frozen=True, slots=True)
class GarageVehicle:
    vehicle_id: int
    model_key: str
    condition_key: str
    city_key: str
    parked: bool


@dataclass(frozen=True, slots=True)
class PremiumHousingOpportunityResult:
    item_id: str
    item_name: str
    item_emoji: str


