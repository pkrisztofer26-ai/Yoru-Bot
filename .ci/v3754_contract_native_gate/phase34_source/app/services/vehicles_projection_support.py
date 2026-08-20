from __future__ import annotations
__all__ = ['Any', 'Callable', 'CharacterService', 'ConsequenceMemoryService', 'Database', 'KeyedLockPool', 'MarketOffer', 'MemoryAdapterService', 'TravelResult', 'Vehicle', 'VehiclePurchaseResult', 'VehicleRepairResult', 'VehicleSaleResult', '_iso', '_rounded_price', '_serialized_vehicle_action', '_utcnow', 'aiosqlite', 'asyncio', 'cfg', 'character_cfg', 'dataclass', 'datetime', 'json', 'logging', 'npc_favor_config', 'random', 'timedelta', 'timezone', 'wraps']
from dataclasses import dataclass
import asyncio
from functools import wraps
from datetime import datetime, timedelta, timezone
import json
import logging
import random
from typing import Any, Callable
from app import character_config as character_cfg
from app import db_backend as aiosqlite
from app import vehicle_config as cfg
from app import npc_favor_config
from app.database import Database
from app.core.keyed_locks import KeyedLockPool
from app.services.characters import CharacterService
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _iso(value: datetime | None=None) -> str:
    return (value or _utcnow()).isoformat()

def _rounded_price(value: int) -> int:
    step = 10000
    return max(step, int(round(int(value) / step)) * step)

def _serialized_vehicle_action(func):

    @wraps(func)
    async def wrapper(self, guild_id: int, user_id: int, *args, **kwargs):
        key = (int(guild_id), int(user_id))
        async with self._action_locks.hold(key):
            return await func(self, guild_id, user_id, *args, **kwargs)
    return wrapper

@dataclass(frozen=True, slots=True)
class Vehicle:
    vehicle_id: int
    guild_id: int
    user_id: int
    model_key: str
    condition_key: str
    city_key: str
    purchase_price: int
    estimated_value: int
    status: str
    acquired_at: str
    updated_at: str
    sold_at: str | None
    is_primary: bool = False
    issue_key: str | None = None
    issue_revealed: bool = False
    last_service_at: str | None = None

@dataclass(frozen=True, slots=True)
class MarketOffer:
    offer_id: int
    guild_id: int
    city_key: str
    model_key: str
    condition_key: str
    price: int
    status: str
    created_at: str
    expires_at: str
    buyer_user_id: int | None
    purchased_at: str | None

@dataclass(frozen=True, slots=True)
class VehiclePurchaseResult:
    vehicle: Vehicle
    offer: MarketOffer | None
    price: int
    wallet_used: int
    bank_used: int
    new_wallet: int
    new_bank: int
    source: str = 'used_market'
    base_price: int = 0
    discount_saved: int = 0
    favor_effect_key: str | None = None

@dataclass(frozen=True, slots=True)
class VehicleSaleResult:
    vehicle_id: int
    model_key: str
    received: int
    new_bank: int

@dataclass(frozen=True, slots=True)
class VehicleRepairResult:
    vehicle: Vehicle
    paid: int
    old_condition_key: str
    new_condition_key: str
    issue_fixed: bool
    new_wallet: int
    new_bank: int
    base_price: int = 0
    discount_saved: int = 0
    favor_effect_key: str | None = None

@dataclass(frozen=True, slots=True)
class TravelResult:
    from_city_key: str
    to_city_key: str
    mode_key: str
    cost: int
    new_wallet: int
    new_bank: int
    vehicle: Vehicle | None
    event_text: str | None = None
    old_condition_key: str | None = None
    new_condition_key: str | None = None
    issue_revealed: bool = False
