from __future__ import annotations
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
import asyncio
import random
from app.database import Database
from app.core.keyed_locks import KeyedLockPool
from app.services.economy import CooldownError, EconomyService, JailError
from app.services.casino import CasinoService
from app import economy_config as eco
from app import casino_config as casino_cfg
from app import shop_config as shop_cfg
from app.ui import money
from app.text_hu import format_hu_relative

@dataclass(slots=True)
class ExtrasCasinoResult:
    game_id: str
    bet: int
    payout: int
    profit: int
    wallet: int
    multiplier: float
    result: str
    details: dict = field(default_factory=dict)

class ExtrasService:
    WEEKLY_COOLDOWN = eco.WEEKLY_COOLDOWN
    MONTHLY_COOLDOWN = eco.MONTHLY_COOLDOWN
    INTEREST_COOLDOWN = eco.INTEREST_COOLDOWN

    def __init__(self, database: Database, economy: EconomyService, casino: CasinoService | None=None) -> None:
        self.db = database
        self.economy = economy
        self.casino = casino or CasinoService(database)
        self.contracts = None
        self._chicken_locks: KeyedLockPool[tuple[int, int]] = KeyedLockPool()

    def bind_contracts(self, contracts) -> None:
        self.contracts = contracts

    async def deliver_contract_item(self, guild_id: int, user_id: int, contract_id: int, objective_id: int) -> dict:
        """Settle an item handoff in the inventory domain, then emit its stable contract event."""
        if self.contracts is None:
            raise RuntimeError('A megbízási rendszer jelenleg nem érhető el.')
        contract = await self.contracts.get_contract(guild_id, contract_id)
        if contract is None or contract.status != 'active' or contract.assignee_id != int(user_id):
            raise ValueError('Ez a megbízás nem aktív nálad.')
        if contract.creator_id is None:
            raise ValueError('Ehhez a megbízáshoz nincs játékos átvevő.')
        objectives = await self.contracts.objectives(guild_id, contract_id)
        objective = next((row for row in objectives if int(row['objective_id']) == int(objective_id)), None)
        if objective is None or str(objective.get('objective_type')) != 'item_delivery':
            raise ValueError('Ez nem tárgyátadási feladat.')
        if str(objective.get('status')) != 'pending':
            raise ValueError('Ez a tárgyátadás már teljesült.')
        remaining = max(0, int(objective['required_value']) - int(objective['current_value']))
        if remaining < 1:
            raise ValueError('Ez a tárgyátadás már teljesült.')
        item_id = str(objective['target_ref'])
        transfer_id, name, emoji, moved, replay = await self.db.transfer_item_audited(guild_id, user_id, int(contract.creator_id), item_id, remaining, source_ref=f'contract-item:{int(contract_id)}:{int(objective_id)}')
        progressed = await self.contracts.record_item_delivery(guild_id, contract_id, user_id, event_key=f'item_transfer:{transfer_id}', item_id=item_id, quantity=moved)
        settled, paid = await self.contracts.settle_if_ready(guild_id, contract_id)
        return {'contract': settled, 'objective_id': int(objective_id), 'item_id': item_id, 'item_name': name, 'emoji': emoji, 'quantity': moved, 'transfer_id': transfer_id, 'transfer_replay': replay, 'contract_progressed': progressed, 'paid': paid}
