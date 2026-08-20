from __future__ import annotations
from dataclasses import dataclass
from app import economy_config as eco
from app import casino_config as casino_cfg
from app import jobs_config as jobs_cfg
from app import social_config as social_cfg
from app.repositories.guild_state import GuildStateRepository
from app.services.server_settings import ServerSettingsService

@dataclass(frozen=True, slots=True)
class CasinoRuntimeSettings:
    min_bet: int
    jackpot_min_games: int
    jackpot_min_wager: int
    jackpot_payout_share: float
    jackpot_contribution_rate: float

@dataclass(frozen=True, slots=True)
class CasinoTestRuntimeSettings:
    game: str
    bonus_chance_override: float | None
    force_next_bonus: bool
    force_next_retrigger: bool
    free_play: bool
    animation_speed: float

    @property
    def active(self) -> bool:
        return bool(self.bonus_chance_override is not None or self.force_next_bonus or self.force_next_retrigger or self.free_play or (abs(self.animation_speed - 1.0) > 1e-09))

@dataclass(frozen=True, slots=True)
class JobsRuntimeSettings:
    cooldown_seconds: int
    abandon_cooldown_seconds: int
    session_timeout_seconds: int
    warehouse_memorize_seconds: float
    warehouse_decision_timeout_seconds: float
    scenario_decision_timeout_seconds: float

@dataclass(frozen=True, slots=True)
class CommunityEconomyRuntimeSettings:
    lottery_ticket_price: int
    lottery_payout_share: float
    lottery_min_pot: int
    lottery_max_tickets_per_buy: int
    black_market_price_min: float
    black_market_price_max: float
    black_market_item_count: int
    black_market_stock_min: int
    black_market_stock_max: int

@dataclass(frozen=True, slots=True)
class SocialRuntimeSettings:
    market_tax_rate: float
    market_listing_hours: int
    market_max_active_per_user: int
    market_max_quantity: int
    market_min_unit_price: int
    server_shop_max_items: int
    pvp_min_stake: int
    pvp_challenge_seconds: int
    pvp_rps_seconds: int

class GameplaySettingsService:
    """Guild-scoped gameplay tuning.

    The DB-backed settings are authoritative.  Code constants are only defaults,
    so upgrading Yoru never overwrites a server's configured balance.
    """
    CASINO_KEYS = ('casino_min_bet', 'casino_jackpot_min_games', 'casino_jackpot_min_wager', 'casino_jackpot_payout_share', 'casino_jackpot_contribution_rate')
    JOBS_KEYS = ('jobs_cooldown_seconds', 'jobs_abandon_cooldown_seconds', 'jobs_session_timeout_seconds', 'jobs_warehouse_memorize_seconds', 'jobs_warehouse_decision_timeout_seconds', 'jobs_scenario_decision_timeout_seconds')
    SOCIAL_KEYS = ('social_market_tax_rate', 'social_market_listing_hours', 'social_market_max_active_per_user', 'social_market_max_quantity', 'social_market_min_unit_price', 'social_server_shop_max_items', 'social_pvp_min_stake', 'social_pvp_challenge_seconds', 'social_pvp_rps_seconds')
    COMMUNITY_ECONOMY_KEYS = ('community_lottery_ticket_price', 'community_lottery_payout_share', 'community_lottery_min_pot', 'community_lottery_max_tickets_per_buy', 'community_black_market_price_min', 'community_black_market_price_max', 'community_black_market_item_count', 'community_black_market_stock_min', 'community_black_market_stock_max')

    def __init__(self, db) -> None:
        self.db = db
        self.guild_state_repository = GuildStateRepository(db.path)
        self.state = ServerSettingsService(db)

    async def _float(self, guild_id: int, key: str, default: float) -> float:
        raw = await self.guild_state_repository.get(guild_id, key)
        if raw is None or not str(raw).strip():
            return float(default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    async def _set_float(self, guild_id: int, key: str, value: float | None) -> None:
        await self.guild_state_repository.set(guild_id, key, '' if value is None else f'{float(value):g}')

    async def casino(self, guild_id: int) -> CasinoRuntimeSettings:
        min_bet = await self.state.get_int(guild_id, 'casino_min_bet')
        min_games = await self.state.get_int(guild_id, 'casino_jackpot_min_games')
        min_wager = await self.state.get_int(guild_id, 'casino_jackpot_min_wager')
        return CasinoRuntimeSettings(min_bet=max(1, min(10 ** 15, int(casino_cfg.MIN_BET if min_bet is None else min_bet))), jackpot_min_games=max(0, min(1000000, int(casino_cfg.MONTHLY_JACKPOT_MIN_GAMES if min_games is None else min_games))), jackpot_min_wager=max(0, min(10 ** 18, int(casino_cfg.MONTHLY_JACKPOT_MIN_WAGER if min_wager is None else min_wager))), jackpot_payout_share=max(0.0, min(1.0, await self._float(guild_id, 'casino_jackpot_payout_share', casino_cfg.MONTHLY_JACKPOT_PAYOUT_SHARE))), jackpot_contribution_rate=max(0.0, min(1.0, await self._float(guild_id, 'casino_jackpot_contribution_rate', casino_cfg.MONTHLY_JACKPOT_CONTRIBUTION_RATE))))

    @staticmethod
    def _casino_test_key(game: str, suffix: str) -> str:
        safe_game = ''.join((ch for ch in str(game).lower() if ch.isalnum() or ch == '_'))
        if not safe_game:
            raise ValueError('Hiányzó kaszinó tesztjáték.')
        return f'casino_test_{safe_game}_{suffix}'

    async def casino_test(self, guild_id: int, game: str) -> CasinoTestRuntimeSettings:
        chance_raw = await self.guild_state_repository.get(guild_id, self._casino_test_key(game, 'bonus_chance'))
        chance = None
        if chance_raw is not None and str(chance_raw).strip():
            try:
                chance = max(0.0, min(1.0, float(chance_raw)))
            except (TypeError, ValueError):
                chance = None
        speed = await self._float(guild_id, self._casino_test_key(game, 'animation_speed'), 1.0)
        return CasinoTestRuntimeSettings(game=str(game).lower(), bonus_chance_override=chance, force_next_bonus=await self.state.get_bool(guild_id, self._casino_test_key(game, 'force_next_bonus'), False), force_next_retrigger=await self.state.get_bool(guild_id, self._casino_test_key(game, 'force_next_retrigger'), False), free_play=await self.state.get_bool(guild_id, self._casino_test_key(game, 'free_play'), False), animation_speed=max(0.25, min(4.0, float(speed))))

    async def jobs(self, guild_id: int) -> JobsRuntimeSettings:
        cooldown = await self.state.get_int(guild_id, 'jobs_cooldown_seconds')
        abandon = await self.state.get_int(guild_id, 'jobs_abandon_cooldown_seconds')
        session = await self.state.get_int(guild_id, 'jobs_session_timeout_seconds')
        return JobsRuntimeSettings(cooldown_seconds=max(0, min(7 * 24 * 3600, int(jobs_cfg.JOB_COOLDOWN_SECONDS if cooldown is None else cooldown))), abandon_cooldown_seconds=max(0, min(24 * 3600, int(jobs_cfg.ABANDON_COOLDOWN_SECONDS if abandon is None else abandon))), session_timeout_seconds=max(30, min(3600, int(jobs_cfg.SESSION_TIMEOUT_SECONDS if session is None else session))), warehouse_memorize_seconds=max(2.0, min(60.0, await self._float(guild_id, 'jobs_warehouse_memorize_seconds', jobs_cfg.WAREHOUSE_MEMORIZE_SECONDS))), warehouse_decision_timeout_seconds=max(10.0, min(300.0, await self._float(guild_id, 'jobs_warehouse_decision_timeout_seconds', jobs_cfg.WAREHOUSE_DECISION_TIMEOUT_SECONDS))), scenario_decision_timeout_seconds=max(10.0, min(300.0, await self._float(guild_id, 'jobs_scenario_decision_timeout_seconds', jobs_cfg.DECISION_TIMEOUT_SECONDS))))

    async def community_economy(self, guild_id: int) -> CommunityEconomyRuntimeSettings:
        ticket_price = await self.state.get_int(guild_id, 'community_lottery_ticket_price')
        min_pot = await self.state.get_int(guild_id, 'community_lottery_min_pot')
        max_tickets = await self.state.get_int(guild_id, 'community_lottery_max_tickets_per_buy')
        market_items = await self.state.get_int(guild_id, 'community_black_market_item_count')
        stock_min = await self.state.get_int(guild_id, 'community_black_market_stock_min')
        stock_max = await self.state.get_int(guild_id, 'community_black_market_stock_max')
        price_min = max(0.01, min(1.0, await self._float(guild_id, 'community_black_market_price_min', eco.BLACK_MARKET_PRICE_MULTIPLIER[0])))
        price_max = max(price_min, min(1.0, await self._float(guild_id, 'community_black_market_price_max', eco.BLACK_MARKET_PRICE_MULTIPLIER[1])))
        stock_min_v = max(1, min(1000, int(1 if stock_min is None else stock_min)))
        stock_max_v = max(stock_min_v, min(1000, int(5 if stock_max is None else stock_max)))
        return CommunityEconomyRuntimeSettings(lottery_ticket_price=max(1, min(10 ** 15, int(eco.LOTTERY_TICKET_PRICE if ticket_price is None else ticket_price))), lottery_payout_share=max(0.0, min(1.0, await self._float(guild_id, 'community_lottery_payout_share', eco.LOTTERY_PAYOUT_SHARE))), lottery_min_pot=max(0, min(10 ** 15, int(eco.LOTTERY_MIN_POT if min_pot is None else min_pot))), lottery_max_tickets_per_buy=max(1, min(1000000, int(eco.LOTTERY_MAX_TICKETS_PER_BUY if max_tickets is None else max_tickets))), black_market_price_min=price_min, black_market_price_max=price_max, black_market_item_count=max(1, min(9, int(4 if market_items is None else market_items))), black_market_stock_min=stock_min_v, black_market_stock_max=stock_max_v)
