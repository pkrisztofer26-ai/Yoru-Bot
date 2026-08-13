from __future__ import annotations

from dataclasses import dataclass

from app import economy_config as eco
from app import casino_config as casino_cfg
from app import jobs_config as jobs_cfg
from app import social_config as social_cfg
from app.services.server_settings import ServerSettingsService


@dataclass(frozen=True, slots=True)
class PrestigeRuntimeSettings:
    enabled: bool
    level_base: int
    level_step: int
    wealth_base: int
    wealth_growth: float
    income_bonus_per_rank: float
    income_bonus_cap: float


@dataclass(frozen=True, slots=True)
class QuestRuntimeSettings:
    enabled: bool
    daily_enabled: bool
    weekly_enabled: bool
    count_per_period: int
    target_multiplier: float
    money_multiplier: float
    daily_progression_xp: int
    weekly_progression_xp: int


@dataclass(frozen=True, slots=True)
class ProgressionRuntimeSettings:
    xp_multiplier: float
    invest_enabled: bool
    invest_cooldown_hours: float
    invest_min_amount: int


@dataclass(frozen=True, slots=True)
class CasinoRuntimeSettings:
    min_bet: int
    jackpot_min_games: int
    jackpot_min_wager: int
    jackpot_payout_share: float
    jackpot_contribution_rate: float


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
    event_min_hours: float
    event_max_hours: float
    event_duration_hours: float
    work_multiplier: float
    crime_multiplier: float
    luck_multiplier: float
    black_market_price_min: float
    black_market_price_max: float
    black_market_duration_minutes: int
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

    PRESTIGE_KEYS = (
        "prestige_enabled",
        "prestige_level_base",
        "prestige_level_step",
        "prestige_wealth_base",
        "prestige_wealth_growth",
        "prestige_income_bonus_per_rank",
        "prestige_income_bonus_cap",
    )
    QUEST_KEYS = (
        "quests_enabled",
        "quests_daily_enabled",
        "quests_weekly_enabled",
        "quests_count_per_period",
        "quests_target_multiplier",
        "quests_money_multiplier",
        "quests_daily_progression_xp",
        "quests_weekly_progression_xp",
    )
    PROGRESSION_KEYS = (
        "progression_xp_multiplier_percent",
        "progression_invest_enabled",
        "progression_invest_cooldown_hours",
        "progression_invest_min_amount",
    )
    CASINO_KEYS = (
        "casino_min_bet",
        "casino_jackpot_min_games",
        "casino_jackpot_min_wager",
        "casino_jackpot_payout_share",
        "casino_jackpot_contribution_rate",
    )
    JOBS_KEYS = (
        "jobs_cooldown_seconds",
        "jobs_abandon_cooldown_seconds",
        "jobs_session_timeout_seconds",
        "jobs_warehouse_memorize_seconds",
        "jobs_warehouse_decision_timeout_seconds",
        "jobs_scenario_decision_timeout_seconds",
    )
    SOCIAL_KEYS = (
        "social_market_tax_rate",
        "social_market_listing_hours",
        "social_market_max_active_per_user",
        "social_market_max_quantity",
        "social_market_min_unit_price",
        "social_server_shop_max_items",
        "social_pvp_min_stake",
        "social_pvp_challenge_seconds",
        "social_pvp_rps_seconds",
    )
    COMMUNITY_ECONOMY_KEYS = (
        "community_lottery_ticket_price", "community_lottery_payout_share",
        "community_lottery_min_pot", "community_lottery_max_tickets_per_buy",
        "community_economy_event_min_hours", "community_economy_event_max_hours",
        "community_economy_event_duration_hours", "community_economy_work_multiplier",
        "community_economy_crime_multiplier", "community_economy_luck_multiplier",
        "community_black_market_price_min", "community_black_market_price_max",
        "community_black_market_duration_minutes", "community_black_market_item_count",
        "community_black_market_stock_min", "community_black_market_stock_max",
    )

    def __init__(self, db) -> None:
        self.db = db
        self.state = ServerSettingsService(db)

    async def _float(self, guild_id: int, key: str, default: float) -> float:
        raw = await self.db.get_guild_state(guild_id, key)
        if raw is None or not str(raw).strip():
            return float(default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    async def _set_float(self, guild_id: int, key: str, value: float | None) -> None:
        await self.db.set_guild_state(guild_id, key, "" if value is None else f"{float(value):g}")

    async def prestige(self, guild_id: int) -> PrestigeRuntimeSettings:
        enabled = await self.state.get_bool(guild_id, "prestige_enabled", True)
        level_base_raw = await self.state.get_int(guild_id, "prestige_level_base")
        level_base = eco.PRESTIGE_LEVEL_BASE if level_base_raw is None else int(level_base_raw)
        level_step_raw = await self.state.get_int(guild_id, "prestige_level_step")
        level_step = eco.PRESTIGE_LEVEL_STEP if level_step_raw is None else int(level_step_raw)
        wealth_base_raw = await self.state.get_int(guild_id, "prestige_wealth_base")
        wealth_base = eco.PRESTIGE_WEALTH_BASE if wealth_base_raw is None else int(wealth_base_raw)
        wealth_growth = await self._float(guild_id, "prestige_wealth_growth", eco.PRESTIGE_WEALTH_GROWTH)
        per_rank = await self._float(guild_id, "prestige_income_bonus_per_rank", eco.PRESTIGE_INCOME_BONUS_PER_LEVEL)
        cap = await self._float(guild_id, "prestige_income_bonus_cap", eco.PRESTIGE_INCOME_BONUS_CAP)
        return PrestigeRuntimeSettings(
            enabled=enabled,
            level_base=max(1, min(10_000, int(level_base))),
            level_step=max(0, min(2_000, int(level_step))),
            wealth_base=max(0, min(10**15, int(wealth_base))),
            wealth_growth=max(1.0, min(10.0, float(wealth_growth))),
            income_bonus_per_rank=max(0.0, min(1.0, float(per_rank))),
            income_bonus_cap=max(0.0, min(5.0, float(cap))),
        )

    async def set_prestige(
        self,
        guild_id: int,
        *,
        enabled: bool | None = None,
        level_base: int | None = None,
        level_step: int | None = None,
        wealth_base: int | None = None,
        wealth_growth: float | None = None,
        income_bonus_per_rank: float | None = None,
        income_bonus_cap: float | None = None,
    ) -> None:
        if enabled is not None:
            await self.state.set_bool(guild_id, "prestige_enabled", bool(enabled))
        if level_base is not None:
            if not 1 <= int(level_base) <= 10_000:
                raise ValueError("Prestige alap Level: 1–10000.")
            await self.state.set_int(guild_id, "prestige_level_base", int(level_base))
        if level_step is not None:
            if not 0 <= int(level_step) <= 2_000:
                raise ValueError("Prestige Level lépcső: 0–2000.")
            await self.state.set_int(guild_id, "prestige_level_step", int(level_step))
        if wealth_base is not None:
            if not 0 <= int(wealth_base) <= 10**15:
                raise ValueError("Prestige alap vagyon: 0–1 quadrillion.")
            await self.state.set_int(guild_id, "prestige_wealth_base", int(wealth_base))
        if wealth_growth is not None:
            if not 1.0 <= float(wealth_growth) <= 10.0:
                raise ValueError("Prestige vagyon növekedés: 1.00×–10.00×.")
            await self._set_float(guild_id, "prestige_wealth_growth", float(wealth_growth))
        if income_bonus_per_rank is not None:
            if not 0.0 <= float(income_bonus_per_rank) <= 1.0:
                raise ValueError("Prestige income/rank: 0–100%.")
            await self._set_float(guild_id, "prestige_income_bonus_per_rank", float(income_bonus_per_rank))
        if income_bonus_cap is not None:
            if not 0.0 <= float(income_bonus_cap) <= 5.0:
                raise ValueError("Prestige income cap: 0–500%.")
            await self._set_float(guild_id, "prestige_income_bonus_cap", float(income_bonus_cap))

    async def reset_prestige(self, guild_id: int) -> None:
        for key in self.PRESTIGE_KEYS:
            await self.db.set_guild_state(guild_id, key, "")

    async def quests(self, guild_id: int) -> QuestRuntimeSettings:
        count_raw = await self.state.get_int(guild_id, "quests_count_per_period")
        daily_xp_raw = await self.state.get_int(guild_id, "quests_daily_progression_xp")
        weekly_xp_raw = await self.state.get_int(guild_id, "quests_weekly_progression_xp")
        return QuestRuntimeSettings(
            enabled=await self.state.get_bool(guild_id, "quests_enabled", True),
            daily_enabled=await self.state.get_bool(guild_id, "quests_daily_enabled", True),
            weekly_enabled=await self.state.get_bool(guild_id, "quests_weekly_enabled", True),
            count_per_period=max(1, min(10, int(3 if count_raw is None else count_raw))),
            target_multiplier=max(0.25, min(5.0, await self._float(guild_id, "quests_target_multiplier", 1.0))),
            money_multiplier=max(0.0, min(10.0, await self._float(guild_id, "quests_money_multiplier", 1.0))),
            daily_progression_xp=max(0, min(100_000, int(eco.QUEST_PROGRESSION_XP["daily"] if daily_xp_raw is None else daily_xp_raw))),
            weekly_progression_xp=max(0, min(100_000, int(eco.QUEST_PROGRESSION_XP["weekly"] if weekly_xp_raw is None else weekly_xp_raw))),
        )

    async def set_quests(
        self,
        guild_id: int,
        *,
        enabled: bool | None = None,
        daily_enabled: bool | None = None,
        weekly_enabled: bool | None = None,
        count_per_period: int | None = None,
        target_multiplier: float | None = None,
        money_multiplier: float | None = None,
        daily_progression_xp: int | None = None,
        weekly_progression_xp: int | None = None,
    ) -> None:
        if enabled is not None:
            await self.state.set_bool(guild_id, "quests_enabled", bool(enabled))
        if daily_enabled is not None:
            await self.state.set_bool(guild_id, "quests_daily_enabled", bool(daily_enabled))
        if weekly_enabled is not None:
            await self.state.set_bool(guild_id, "quests_weekly_enabled", bool(weekly_enabled))
        if count_per_period is not None:
            if not 1 <= int(count_per_period) <= 10:
                raise ValueError("Quest darabszám: 1–10.")
            await self.state.set_int(guild_id, "quests_count_per_period", int(count_per_period))
        if target_multiplier is not None:
            if not 0.25 <= float(target_multiplier) <= 5.0:
                raise ValueError("Quest target szorzó: 0.25×–5.00×.")
            await self._set_float(guild_id, "quests_target_multiplier", float(target_multiplier))
        if money_multiplier is not None:
            if not 0.0 <= float(money_multiplier) <= 10.0:
                raise ValueError("Quest pénz szorzó: 0×–10×.")
            await self._set_float(guild_id, "quests_money_multiplier", float(money_multiplier))
        if daily_progression_xp is not None:
            if not 0 <= int(daily_progression_xp) <= 100_000:
                raise ValueError("Daily quest progression XP: 0–100000.")
            await self.state.set_int(guild_id, "quests_daily_progression_xp", int(daily_progression_xp))
        if weekly_progression_xp is not None:
            if not 0 <= int(weekly_progression_xp) <= 100_000:
                raise ValueError("Weekly quest progression XP: 0–100000.")
            await self.state.set_int(guild_id, "quests_weekly_progression_xp", int(weekly_progression_xp))

    async def reset_quests(self, guild_id: int) -> None:
        for key in self.QUEST_KEYS:
            await self.db.set_guild_state(guild_id, key, "")

    async def progression(self, guild_id: int) -> ProgressionRuntimeSettings:
        xp_raw = await self.state.get_int(guild_id, "progression_xp_multiplier_percent")
        invest_min_raw = await self.state.get_int(guild_id, "progression_invest_min_amount")
        return ProgressionRuntimeSettings(
            xp_multiplier=max(0.0, min(10.0, float(100 if xp_raw is None else xp_raw) / 100.0)),
            invest_enabled=await self.state.get_bool(guild_id, "progression_invest_enabled", True),
            invest_cooldown_hours=max(0.0, min(168.0, await self._float(guild_id, "progression_invest_cooldown_hours", eco.INVEST_COOLDOWN_HOURS))),
            invest_min_amount=max(1, min(10**15, int(eco.INVEST_MIN_AMOUNT if invest_min_raw is None else invest_min_raw))),
        )

    async def set_progression(
        self,
        guild_id: int,
        *,
        xp_multiplier_percent: int | None = None,
        invest_enabled: bool | None = None,
        invest_cooldown_hours: float | None = None,
        invest_min_amount: int | None = None,
    ) -> None:
        if xp_multiplier_percent is not None:
            if not 0 <= int(xp_multiplier_percent) <= 1000:
                raise ValueError("Progression XP szorzó: 0–1000%.")
            await self.state.set_int(guild_id, "progression_xp_multiplier_percent", int(xp_multiplier_percent))
        if invest_enabled is not None:
            await self.state.set_bool(guild_id, "progression_invest_enabled", bool(invest_enabled))
        if invest_cooldown_hours is not None:
            if not 0.0 <= float(invest_cooldown_hours) <= 168.0:
                raise ValueError("Invest cooldown: 0–168 óra.")
            await self._set_float(guild_id, "progression_invest_cooldown_hours", float(invest_cooldown_hours))
        if invest_min_amount is not None:
            if not 1 <= int(invest_min_amount) <= 10**15:
                raise ValueError("Invest minimum: 1–1 quadrillion.")
            await self.state.set_int(guild_id, "progression_invest_min_amount", int(invest_min_amount))

    async def reset_progression(self, guild_id: int) -> None:
        for key in self.PROGRESSION_KEYS:
            await self.db.set_guild_state(guild_id, key, "")

    async def casino(self, guild_id: int) -> CasinoRuntimeSettings:
        min_bet = await self.state.get_int(guild_id, "casino_min_bet")
        min_games = await self.state.get_int(guild_id, "casino_jackpot_min_games")
        min_wager = await self.state.get_int(guild_id, "casino_jackpot_min_wager")
        return CasinoRuntimeSettings(
            min_bet=max(1, min(10**15, int(casino_cfg.MIN_BET if min_bet is None else min_bet))),
            jackpot_min_games=max(0, min(1_000_000, int(casino_cfg.MONTHLY_JACKPOT_MIN_GAMES if min_games is None else min_games))),
            jackpot_min_wager=max(0, min(10**18, int(casino_cfg.MONTHLY_JACKPOT_MIN_WAGER if min_wager is None else min_wager))),
            jackpot_payout_share=max(0.0, min(1.0, await self._float(guild_id, "casino_jackpot_payout_share", casino_cfg.MONTHLY_JACKPOT_PAYOUT_SHARE))),
            jackpot_contribution_rate=max(0.0, min(1.0, await self._float(guild_id, "casino_jackpot_contribution_rate", casino_cfg.MONTHLY_JACKPOT_CONTRIBUTION_RATE))),
        )

    async def set_casino(self, guild_id: int, *, min_bet: int | None = None, jackpot_min_games: int | None = None, jackpot_min_wager: int | None = None, jackpot_payout_share: float | None = None, jackpot_contribution_rate: float | None = None) -> None:
        if min_bet is not None:
            if not 1 <= int(min_bet) <= 10**15: raise ValueError("Casino minimum tét: 1–1 quadrillion.")
            await self.state.set_int(guild_id, "casino_min_bet", int(min_bet))
        if jackpot_min_games is not None:
            if not 0 <= int(jackpot_min_games) <= 1_000_000: raise ValueError("Jackpot minimum játék: 0–1000000.")
            await self.state.set_int(guild_id, "casino_jackpot_min_games", int(jackpot_min_games))
        if jackpot_min_wager is not None:
            if not 0 <= int(jackpot_min_wager) <= 10**18: raise ValueError("Jackpot minimum wager: 0–1e18.")
            await self.state.set_int(guild_id, "casino_jackpot_min_wager", int(jackpot_min_wager))
        if jackpot_payout_share is not None:
            if not 0.0 <= float(jackpot_payout_share) <= 1.0: raise ValueError("Jackpot payout share: 0–100%.")
            await self._set_float(guild_id, "casino_jackpot_payout_share", float(jackpot_payout_share))
        if jackpot_contribution_rate is not None:
            if not 0.0 <= float(jackpot_contribution_rate) <= 1.0: raise ValueError("Jackpot contribution: 0–100%.")
            await self._set_float(guild_id, "casino_jackpot_contribution_rate", float(jackpot_contribution_rate))

    async def reset_casino(self, guild_id: int) -> None:
        for key in self.CASINO_KEYS: await self.db.set_guild_state(guild_id, key, "")

    async def jobs(self, guild_id: int) -> JobsRuntimeSettings:
        cooldown = await self.state.get_int(guild_id, "jobs_cooldown_seconds")
        abandon = await self.state.get_int(guild_id, "jobs_abandon_cooldown_seconds")
        session = await self.state.get_int(guild_id, "jobs_session_timeout_seconds")
        return JobsRuntimeSettings(
            cooldown_seconds=max(0, min(7*24*3600, int(jobs_cfg.JOB_COOLDOWN_SECONDS if cooldown is None else cooldown))),
            abandon_cooldown_seconds=max(0, min(24*3600, int(jobs_cfg.ABANDON_COOLDOWN_SECONDS if abandon is None else abandon))),
            session_timeout_seconds=max(30, min(3600, int(jobs_cfg.SESSION_TIMEOUT_SECONDS if session is None else session))),
            warehouse_memorize_seconds=max(2.0, min(60.0, await self._float(guild_id, "jobs_warehouse_memorize_seconds", jobs_cfg.WAREHOUSE_MEMORIZE_SECONDS))),
            warehouse_decision_timeout_seconds=max(10.0, min(300.0, await self._float(guild_id, "jobs_warehouse_decision_timeout_seconds", jobs_cfg.WAREHOUSE_DECISION_TIMEOUT_SECONDS))),
            scenario_decision_timeout_seconds=max(10.0, min(300.0, await self._float(guild_id, "jobs_scenario_decision_timeout_seconds", jobs_cfg.DECISION_TIMEOUT_SECONDS))),
        )

    async def set_jobs(self, guild_id: int, *, cooldown_seconds: int | None = None, abandon_cooldown_seconds: int | None = None, session_timeout_seconds: int | None = None, warehouse_memorize_seconds: float | None = None, warehouse_decision_timeout_seconds: float | None = None, scenario_decision_timeout_seconds: float | None = None) -> None:
        if cooldown_seconds is not None:
            if not 0 <= int(cooldown_seconds) <= 7*24*3600: raise ValueError("Jobs cooldown: 0–7 nap.")
            await self.state.set_int(guild_id, "jobs_cooldown_seconds", int(cooldown_seconds))
        if abandon_cooldown_seconds is not None:
            if not 0 <= int(abandon_cooldown_seconds) <= 24*3600: raise ValueError("Jobs abandon cooldown: 0–24 óra.")
            await self.state.set_int(guild_id, "jobs_abandon_cooldown_seconds", int(abandon_cooldown_seconds))
        if session_timeout_seconds is not None:
            if not 30 <= int(session_timeout_seconds) <= 3600: raise ValueError("Jobs session timeout: 30–3600 mp.")
            await self.state.set_int(guild_id, "jobs_session_timeout_seconds", int(session_timeout_seconds))
        if warehouse_memorize_seconds is not None:
            if not 2.0 <= float(warehouse_memorize_seconds) <= 60.0: raise ValueError("Raktáros memóriaidő: 2–60 mp.")
            await self._set_float(guild_id, "jobs_warehouse_memorize_seconds", float(warehouse_memorize_seconds))
        if warehouse_decision_timeout_seconds is not None:
            if not 10.0 <= float(warehouse_decision_timeout_seconds) <= 300.0: raise ValueError("Raktáros döntési idő: 10–300 mp.")
            await self._set_float(guild_id, "jobs_warehouse_decision_timeout_seconds", float(warehouse_decision_timeout_seconds))
        if scenario_decision_timeout_seconds is not None:
            if not 10.0 <= float(scenario_decision_timeout_seconds) <= 300.0: raise ValueError("Jobs scenario döntési idő: 10–300 mp.")
            await self._set_float(guild_id, "jobs_scenario_decision_timeout_seconds", float(scenario_decision_timeout_seconds))

    async def reset_jobs(self, guild_id: int) -> None:
        for key in self.JOBS_KEYS: await self.db.set_guild_state(guild_id, key, "")

    async def social(self, guild_id: int) -> SocialRuntimeSettings:
        listing_hours = await self.state.get_int(guild_id, "social_market_listing_hours")
        max_active = await self.state.get_int(guild_id, "social_market_max_active_per_user")
        max_qty = await self.state.get_int(guild_id, "social_market_max_quantity")
        min_price = await self.state.get_int(guild_id, "social_market_min_unit_price")
        shop_max = await self.state.get_int(guild_id, "social_server_shop_max_items")
        pvp_min = await self.state.get_int(guild_id, "social_pvp_min_stake")
        pvp_challenge = await self.state.get_int(guild_id, "social_pvp_challenge_seconds")
        pvp_rps = await self.state.get_int(guild_id, "social_pvp_rps_seconds")
        return SocialRuntimeSettings(
            market_tax_rate=max(0.0, min(0.50, await self._float(guild_id, "social_market_tax_rate", social_cfg.PLAYER_MARKET_TAX_RATE))),
            market_listing_hours=max(1, min(24*365, int(social_cfg.PLAYER_MARKET_LISTING_HOURS if listing_hours is None else listing_hours))),
            market_max_active_per_user=max(1, min(1000, int(social_cfg.PLAYER_MARKET_MAX_ACTIVE_PER_USER if max_active is None else max_active))),
            market_max_quantity=max(1, min(1_000_000, int(social_cfg.PLAYER_MARKET_MAX_QUANTITY if max_qty is None else max_qty))),
            market_min_unit_price=max(1, min(10**15, int(social_cfg.PLAYER_MARKET_MIN_UNIT_PRICE if min_price is None else min_price))),
            server_shop_max_items=max(1, min(1000, int(social_cfg.SERVER_SHOP_MAX_ITEMS if shop_max is None else shop_max))),
            pvp_min_stake=max(1, min(10**15, int(social_cfg.PVP_MIN_STAKE if pvp_min is None else pvp_min))),
            pvp_challenge_seconds=max(15, min(3600, int(social_cfg.PVP_CHALLENGE_SECONDS if pvp_challenge is None else pvp_challenge))),
            pvp_rps_seconds=max(15, min(3600, int(social_cfg.PVP_RPS_SECONDS if pvp_rps is None else pvp_rps))),
        )

    async def set_social(self, guild_id: int, *, market_tax_rate: float | None = None, market_listing_hours: int | None = None, market_max_active_per_user: int | None = None, market_max_quantity: int | None = None, market_min_unit_price: int | None = None, server_shop_max_items: int | None = None, pvp_min_stake: int | None = None, pvp_challenge_seconds: int | None = None, pvp_rps_seconds: int | None = None) -> None:
        if market_tax_rate is not None:
            if not 0.0 <= float(market_tax_rate) <= 0.50: raise ValueError("Player Market adó: 0–50%.")
            await self._set_float(guild_id, "social_market_tax_rate", float(market_tax_rate))
        for key, value, lo, hi, label in (
            ("social_market_listing_hours", market_listing_hours, 1, 24*365, "Listing idő"),
            ("social_market_max_active_per_user", market_max_active_per_user, 1, 1000, "Aktív listing/user"),
            ("social_market_max_quantity", market_max_quantity, 1, 1_000_000, "Listing max quantity"),
            ("social_market_min_unit_price", market_min_unit_price, 1, 10**15, "Minimum egységár"),
            ("social_server_shop_max_items", server_shop_max_items, 1, 1000, "Server Shop max item"),
            ("social_pvp_min_stake", pvp_min_stake, 1, 10**15, "PvP minimum tét"),
            ("social_pvp_challenge_seconds", pvp_challenge_seconds, 15, 3600, "PvP challenge idő"),
            ("social_pvp_rps_seconds", pvp_rps_seconds, 15, 3600, "RPS döntési idő"),
        ):
            if value is not None:
                if not lo <= int(value) <= hi: raise ValueError(f"{label}: {lo}–{hi}.")
                await self.state.set_int(guild_id, key, int(value))

    async def reset_social(self, guild_id: int) -> None:
        for key in self.SOCIAL_KEYS: await self.db.set_guild_state(guild_id, key, "")

    async def community_economy(self, guild_id: int) -> CommunityEconomyRuntimeSettings:
        ticket_price = await self.state.get_int(guild_id, "community_lottery_ticket_price")
        min_pot = await self.state.get_int(guild_id, "community_lottery_min_pot")
        max_tickets = await self.state.get_int(guild_id, "community_lottery_max_tickets_per_buy")
        market_duration = await self.state.get_int(guild_id, "community_black_market_duration_minutes")
        market_items = await self.state.get_int(guild_id, "community_black_market_item_count")
        stock_min = await self.state.get_int(guild_id, "community_black_market_stock_min")
        stock_max = await self.state.get_int(guild_id, "community_black_market_stock_max")
        event_min = max(0.05, min(168.0, await self._float(guild_id, "community_economy_event_min_hours", eco.GUILD_ECONOMY_EVENT_MIN_HOURS)))
        event_max = max(event_min, min(168.0, await self._float(guild_id, "community_economy_event_max_hours", eco.GUILD_ECONOMY_EVENT_MAX_HOURS)))
        price_min = max(0.01, min(1.0, await self._float(guild_id, "community_black_market_price_min", eco.BLACK_MARKET_PRICE_MULTIPLIER[0])))
        price_max = max(price_min, min(1.0, await self._float(guild_id, "community_black_market_price_max", eco.BLACK_MARKET_PRICE_MULTIPLIER[1])))
        stock_min_v = max(1, min(1000, int(1 if stock_min is None else stock_min)))
        stock_max_v = max(stock_min_v, min(1000, int(5 if stock_max is None else stock_max)))
        return CommunityEconomyRuntimeSettings(
            lottery_ticket_price=max(1, min(10**15, int(eco.LOTTERY_TICKET_PRICE if ticket_price is None else ticket_price))),
            lottery_payout_share=max(0.0, min(1.0, await self._float(guild_id, "community_lottery_payout_share", eco.LOTTERY_PAYOUT_SHARE))),
            lottery_min_pot=max(0, min(10**15, int(eco.LOTTERY_MIN_POT if min_pot is None else min_pot))),
            lottery_max_tickets_per_buy=max(1, min(1_000_000, int(eco.LOTTERY_MAX_TICKETS_PER_BUY if max_tickets is None else max_tickets))),
            event_min_hours=event_min, event_max_hours=event_max,
            event_duration_hours=max(0.05, min(168.0, await self._float(guild_id, "community_economy_event_duration_hours", eco.GUILD_ECONOMY_EVENT_DURATION_HOURS))),
            work_multiplier=max(0.0, min(10.0, await self._float(guild_id, "community_economy_work_multiplier", eco.GUILD_EVENT_WORK_MULTIPLIER))),
            crime_multiplier=max(0.0, min(10.0, await self._float(guild_id, "community_economy_crime_multiplier", eco.GUILD_EVENT_CRIME_MULTIPLIER))),
            luck_multiplier=max(0.0, min(10.0, await self._float(guild_id, "community_economy_luck_multiplier", eco.GUILD_EVENT_LUCK_MULTIPLIER))),
            black_market_price_min=price_min, black_market_price_max=price_max,
            black_market_duration_minutes=max(1, min(1440, int(eco.BLACK_MARKET_DURATION_MINUTES if market_duration is None else market_duration))),
            black_market_item_count=max(1, min(9, int(4 if market_items is None else market_items))),
            black_market_stock_min=stock_min_v, black_market_stock_max=stock_max_v,
        )

    async def set_community_economy(self, guild_id: int, **values) -> None:
        int_rules = {
            "lottery_ticket_price": ("community_lottery_ticket_price", 1, 10**15),
            "lottery_min_pot": ("community_lottery_min_pot", 0, 10**15),
            "lottery_max_tickets_per_buy": ("community_lottery_max_tickets_per_buy", 1, 1_000_000),
            "black_market_duration_minutes": ("community_black_market_duration_minutes", 1, 1440),
            "black_market_item_count": ("community_black_market_item_count", 1, 9),
            "black_market_stock_min": ("community_black_market_stock_min", 1, 1000),
            "black_market_stock_max": ("community_black_market_stock_max", 1, 1000),
        }
        float_rules = {
            "lottery_payout_share": ("community_lottery_payout_share", 0.0, 1.0),
            "event_min_hours": ("community_economy_event_min_hours", 0.05, 168.0),
            "event_max_hours": ("community_economy_event_max_hours", 0.05, 168.0),
            "event_duration_hours": ("community_economy_event_duration_hours", 0.05, 168.0),
            "work_multiplier": ("community_economy_work_multiplier", 0.0, 10.0),
            "crime_multiplier": ("community_economy_crime_multiplier", 0.0, 10.0),
            "luck_multiplier": ("community_economy_luck_multiplier", 0.0, 10.0),
            "black_market_price_min": ("community_black_market_price_min", 0.01, 1.0),
            "black_market_price_max": ("community_black_market_price_max", 0.01, 1.0),
        }
        unknown = set(values) - set(int_rules) - set(float_rules)
        if unknown:
            raise ValueError(f"Ismeretlen Community Economy setting: {sorted(unknown)[0]}")
        current = await self.community_economy(guild_id)
        event_min = float(values.get("event_min_hours", current.event_min_hours))
        event_max = float(values.get("event_max_hours", current.event_max_hours))
        price_min = float(values.get("black_market_price_min", current.black_market_price_min))
        price_max = float(values.get("black_market_price_max", current.black_market_price_max))
        stock_min = int(values.get("black_market_stock_min", current.black_market_stock_min))
        stock_max = int(values.get("black_market_stock_max", current.black_market_stock_max))
        if event_max < event_min:
            raise ValueError("Community event max idő nem lehet kisebb a minimumnál.")
        if price_max < price_min:
            raise ValueError("Feketepiac max árszorzó nem lehet kisebb a minimumnál.")
        if stock_max < stock_min:
            raise ValueError("Feketepiac max stock nem lehet kisebb a minimumnál.")
        for name, value in values.items():
            if value is None:
                continue
            if name in int_rules:
                key, lo, hi = int_rules[name]
                if not lo <= int(value) <= hi:
                    raise ValueError(f"{name}: {lo}–{hi}.")
                await self.state.set_int(guild_id, key, int(value))
            else:
                key, lo, hi = float_rules[name]
                if not lo <= float(value) <= hi:
                    raise ValueError(f"{name}: {lo}–{hi}.")
                await self._set_float(guild_id, key, float(value))

    async def reset_community_economy(self, guild_id: int) -> None:
        for key in self.COMMUNITY_ECONOMY_KEYS:
            await self.db.set_guild_state(guild_id, key, "")

