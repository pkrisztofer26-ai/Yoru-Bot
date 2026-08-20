# STATIC_CONTRACT: crime_resolved
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import logging
import random
from app.database import Database
from app.repositories.activity import ActivityRepository
from app.repositories.shop_catalog import ShopCatalogRepository
from app.scenarios.adapters import passive_definition
from app.scenarios.config import SCENARIO_V2_ENABLED_KEY
from app.scenarios.engine import ScenarioEngine
from app.scenarios.models import ScenarioChoice, ScenarioContext, ScenarioDefinition
from app import economy_config as eco
from app.services.statistics import StatisticsService
from app.services.police import PoliceService, PoliceState
from app.services.characters import CharacterService
from app.services.world import RPWorldService
from app.services.economy_events_settings import EconomyEventsSettingsService
from app.services.server_settings import ServerSettingsService
from app.ui import money
from app.text_hu import format_hu_relative
log = logging.getLogger('vaultbot.economy')

class EconomyService:
    DAILY_COOLDOWN = eco.DAILY_COOLDOWN
    BEG_COOLDOWN = eco.BEG_COOLDOWN
    SEARCH_COOLDOWN = eco.SEARCH_COOLDOWN
    WORK_COOLDOWN = eco.WORK_COOLDOWN
    CRIME_COOLDOWN = eco.CRIME_COOLDOWN
    ROB_COOLDOWN = eco.ROB_COOLDOWN
    SLUT_COOLDOWN = eco.SLUT_COOLDOWN

    def __init__(self, database: Database, statistics: StatisticsService, police: PoliceService | None=None, characters: CharacterService | None=None, world: RPWorldService | None=None, scenarios: ScenarioEngine | None=None) -> None:
        self.db = database
        self.activity_repository = ActivityRepository(database.path)
        self.shop_catalog = ShopCatalogRepository(database.path)
        self.stats = statistics
        self.police = police
        self.characters = characters
        self.world = world
        self.scenarios = scenarios
        self.scenario_settings = ServerSettingsService(database)
        self.guild_settings = EconomyEventsSettingsService(database)
        if self.scenarios is not None:
            self._register_work_scenarios()
            self._register_crime_catalog()
        self._interest_checks: dict[tuple[int, int], datetime] = {}
        self.bot = None
        self.memory_adapters = None

    def _register_work_scenarios(self) -> None:
        if self.scenarios is None:
            return
        for index, (label, minimum, maximum) in enumerate(eco.WORK_JOBS, start=1):
            key = f'work_{index:02d}'
            if self.scenarios.registry.maybe_get('casual_work', key) is not None:
                continue
            self.scenarios.registry.register(passive_definition(key=key, family='casual_work', domain='economy', title=str(label), prompt=str(label), tags=('work', 'casual'), semantic_key=key, metadata={'legacy_label': str(label), 'minimum': int(minimum), 'maximum': int(maximum)}))

    def _register_crime_catalog(self) -> None:
        """Register the existing v3.72 crime pool for validation/audit only.

        Crime settlement/selection is intentionally NOT migrated in the first
        v3.73 pilot wave; EconomyService.crime remains authoritative until its
        own dedicated migration/regression gate.
        """
        if self.scenarios is None:
            return
        for index, (label, chance) in enumerate(eco.CRIME_SCENARIOS, start=1):
            key = f'crime_{index:02d}'
            if self.scenarios.registry.maybe_get('casual_crime', key) is not None:
                continue
            self.scenarios.registry.register(ScenarioDefinition(key=key, family='casual_crime', domain='crime', title=str(label), prompt=str(label), choices=(ScenarioChoice(key='attempt', label='Megpróbálod', success_chance=float(chance), default=True),), tags=('crime', 'casual'), semantic_key=key, source='deterministic', metadata={'legacy_label': str(label), 'legacy_chance': float(chance), 'catalog_only': True}))

    async def _scenario_v2_enabled(self, guild_id: int) -> bool:
        return self.scenarios is not None and await self.scenario_settings.get_bool(guild_id, SCENARIO_V2_ENABLED_KEY, True)

    async def prepare_context(self, guild_id: int) -> None:
        await self.guild_settings.prepare_currency(guild_id)

    async def settle_bank_interest(self, guild_id: int, user_id: int, *, force_check: bool=False) -> int:
        """Automatically settle one due bank-interest period.

        The old manual /interest claim is retired. Existing ``last_interest``
        timestamps and server tuning remain valid, so no migration/reset is
        required. A user never receives retroactive interest for time spent
        below the configured minimum balance, and a first encounter only starts
        the automatic interval.
        """
        now = datetime.now(timezone.utc)
        cache_key = (int(guild_id), int(user_id))
        checked = self._interest_checks.get(cache_key)
        if not force_check and checked is not None and (now - checked < timedelta(seconds=60)):
            return 0
        self._interest_checks[cache_key] = now
        if len(self._interest_checks) >= 4096:
            cutoff = now - timedelta(minutes=5)
            self._interest_checks = {key: stamp for key, stamp in self._interest_checks.items() if stamp >= cutoff}
        try:
            await self.guild_settings.require_feature(guild_id, 'bank')
            await self.guild_settings.require_feature(guild_id, 'interest')
        except ValueError:
            return 0
        cooldown = await self.guild_settings.get_cooldown(guild_id, 'interest')
        last = await self.db.get_timestamp(guild_id, user_id, 'last_interest')
        if last is None:
            await self.db.set_timestamp(guild_id, user_id, 'last_interest', now)
            return 0
        if now < last + cooldown:
            return 0
        _wallet, bank = await self.db.get_balance(guild_id, user_id)
        minimum_bank = await self.guild_settings.get_interest_min_bank(guild_id)
        if bank < minimum_bank:
            await self.db.set_timestamp(guild_id, user_id, 'last_interest', now)
            return 0
        rate, cap = (eco.INTEREST_TIERS[-1][1], eco.INTEREST_TIERS[-1][2])
        for minimum, tier_rate, tier_cap in eco.INTEREST_TIERS:
            if bank >= minimum:
                rate, cap = (tier_rate, tier_cap)
                break
        rate *= await self.guild_settings.get_interest_rate_multiplier(guild_id)
        cap = int(cap * await self.guild_settings.get_interest_cap_multiplier(guild_id))
        minimum_reward = await self.guild_settings.get_interest_min_reward(guild_id)
        reward = min(cap, max(minimum_reward, int(bank * rate)))
        if reward > 0:
            await self.db.add_bank(guild_id, user_id, reward, 'bank_interest_auto')
            await self.stats.increment(guild_id, user_id, 'interest.automatic')
            await self.stats.add(guild_id, user_id, 'interest.earned', reward)
        await self.db.set_timestamp(guild_id, user_id, 'last_interest', now)
        return reward

    async def require_access(self, guild_id: int, feature: str, channel_id: int | None=None, category_id: int | None=None) -> None:
        await self.guild_settings.require_access(guild_id, feature, channel_id, category_id)

    async def deposit(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
        await self.guild_settings.require_feature(guild_id, 'bank')
        await self.settle_bank_interest(guild_id, user_id, force_check=True)
        return await self.db.move_wallet_to_bank(guild_id, user_id, amount)

    async def leaderboard(self, guild_id: int, category: str='money', limit: int=10):
        await self.prepare_context(guild_id)
        if category in {'activity', 'activity_xp', 'chat', 'chatxp', 'voice'}:
            return await self.activity_repository.leaderboard(guild_id, category, limit)
        return await self.db.leaderboard(guild_id, category, limit)

    async def history(self, guild_id: int, user_id: int, limit: int=10):
        await self.prepare_context(guild_id)
        return await self.db.get_transactions(guild_id, user_id, limit)

    async def jail_status(self, guild_id: int, user_id: int) -> datetime | None:
        until = await self.db.get_jail_until(guild_id, user_id)
        now = datetime.now(timezone.utc)
        if until and until > now:
            return until
        if until:
            await self.db.set_jail_until(guild_id, user_id, None)
        return None

    async def require_not_jailed(self, guild_id: int, user_id: int) -> None:
        until = await self.jail_status(guild_id, user_id)
        if until:
            raise JailError(until)

    async def _check_cooldown(self, guild_id: int, user_id: int, column: str, cooldown: timedelta) -> datetime:
        now = datetime.now(timezone.utc)
        last = await self.db.get_timestamp(guild_id, user_id, column)
        if last and now < last + cooldown:
            raise CooldownError(last + cooldown)
        return now

    async def search(self, guild_id: int, user_id: int) -> tuple[int, str, datetime, tuple[str, str, str] | None]:
        await self.guild_settings.require_feature(guild_id, 'search')
        cooldown = await self.guild_settings.get_cooldown(guild_id, 'search')
        now = await self._check_cooldown(guild_id, user_id, 'last_search', cooldown)
        places = eco.SEARCH_PLACES
        place, minimum, maximum = random.choice(places)
        reward = random.randint(minimum, maximum)
        await self.db.add_wallet(guild_id, user_id, reward, f'search:{place}')
        dropped: tuple[str, str, str] | None = None
        roll = random.random()
        cursor = 0.0
        for item_id, chance in eco.SEARCH_ITEM_DROPS:
            cursor += chance
            if roll < cursor:
                info = await self.shop_catalog.get_item(item_id)
                if info:
                    name, emoji, _price, _rarity, _category = info
                    await self.db.add_item(guild_id, user_id, item_id, 1)
                    await self.stats.increment(guild_id, user_id, 'search.items_found')
                    await self.stats.increment(guild_id, user_id, f'search.item.{item_id}')
                    dropped = (item_id, name, emoji)
                break
        await self.db.increment_stat(guild_id, user_id, 'search_count')
        await self.stats.increment(guild_id, user_id, 'search.count')
        await self.stats.add(guild_id, user_id, 'search.earned', reward)
        await self.stats.set_max(guild_id, user_id, 'search.biggest_reward', reward)
        await self.db.set_timestamp(guild_id, user_id, 'last_search', now)
        return (reward, place, now + cooldown, dropped)

class CooldownError(Exception):

    def __init__(self, ready_at: datetime) -> None:
        super().__init__('A művelet még várakozási időn van.')
        self.ready_at = ready_at

class JailError(Exception):

    def __init__(self, ready_at: datetime) -> None:
        super().__init__('A felhasználó börtönben van.')
        self.ready_at = ready_at
