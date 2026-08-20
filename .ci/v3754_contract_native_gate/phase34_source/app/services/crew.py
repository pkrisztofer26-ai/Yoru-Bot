# STATIC_CONTRACT: event_key=f"crew_deposit_tx:
# STATIC_CONTRACT: event_type="contribution_recorded"
# STATIC_CONTRACT:  adapter
# STATIC_CONTRACT: organization_membership
# STATIC_CONTRACT: organization_membership(
from __future__ import annotations
import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from app import crew_config as cfg
from app.database import Database
from app.repositories.guild_state import GuildStateRepository
from app.services.statistics import StatisticsService
from app.services.server_settings import ServerSettingsService

@dataclass(frozen=True)
class CrewInfo:
    crew_id: int
    guild_id: int
    name: str
    owner_id: int
    bank: int
    level: int
    total_contributed: int
    description: str
    discord_role_id: int | None
    created_at: datetime
    member_count: int

    @property
    def member_cap(self) -> int:
        return cfg.member_cap(self.level)

    @property
    def upgrade_cost(self) -> int | None:
        return cfg.upgrade_cost(self.level)

@dataclass(frozen=True)
class CrewMember:
    user_id: int
    role: str
    contributed: int
    joined_at: datetime

@dataclass(frozen=True)
class CrewMembership:
    crew: CrewInfo
    member: CrewMember

class CrewService:
    ROLE_RANK = {'member': 0, 'officer': 1, 'leader': 2}

    def __init__(self, database: Database, statistics: StatisticsService) -> None:
        self.db = database
        self.guild_state_repository = GuildStateRepository(database.path)
        self.stats = statistics
        self.settings = ServerSettingsService(database)
        self.faction = None
        self.bot = None
        self.characters = None
        self.contracts = None

    def bind_contracts(self, contract_service) -> None:
        self.contracts = contract_service

    @staticmethod
    def _parse_dt(raw: str) -> datetime:
        value = datetime.fromisoformat(raw)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def _crew_from_dict(self, data: dict[str, object]) -> CrewInfo:
        return CrewInfo(crew_id=int(data['crew_id']), guild_id=int(data['guild_id']), name=str(data['name']), owner_id=int(data['owner_id']), bank=int(data['bank']), level=int(data['level']), total_contributed=int(data['total_contributed']), description=str(data.get('description') or ''), discord_role_id=int(data['discord_role_id']) if data.get('discord_role_id') else None, created_at=self._parse_dt(str(data['created_at'])), member_count=int(data.get('member_count', 0)))

    def _member_from_dict(self, data: dict[str, object]) -> CrewMember:
        return CrewMember(user_id=int(data['user_id']), role=str(data['role']), contributed=int(data['contributed']), joined_at=self._parse_dt(str(data['joined_at'])))

    async def get_membership(self, guild_id: int, user_id: int) -> CrewMembership | None:
        row = await self.db.get_crew_membership(guild_id, user_id)
        if row is None:
            return None
        crew_data, member_data = row
        return CrewMembership(self._crew_from_dict(crew_data), self._member_from_dict(member_data))

    async def get_crew(self, guild_id: int, crew_id: int) -> CrewInfo | None:
        row = await self.db.get_crew(guild_id, crew_id)
        return self._crew_from_dict(row) if row else None

    async def deposit(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, CrewInfo]:
        membership = await self.get_membership(guild_id, user_id)
        if membership is None:
            raise ValueError('Nem vagy Szervezet tagja.')
        wallet, bank, transaction_id = await self.db.deposit_to_crew_audited(guild_id, membership.crew.crew_id, user_id, int(amount))
        await self.stats.increment(guild_id, user_id, 'crew.deposits')
        await self.stats.add(guild_id, user_id, 'crew.contributed', int(amount))
        crew = await self.get_crew(guild_id, membership.crew.crew_id)
        if crew is None:
            raise RuntimeError('A Szervezet nem tölthető be.')
        if self.contracts is not None and transaction_id > 0:
            try:
                await self.contracts.record_matching_domain_event(guild_id, user_id, event_key=f'crew_deposit_tx:{transaction_id}', event_type='contribution_recorded', target_ref=f'crew:{membership.crew.crew_id}', delta=int(amount), payload={'transaction_id': transaction_id, 'crew_id': membership.crew.crew_id, 'amount': int(amount)})
            except Exception:
                pass
        return (wallet, bank, crew)
