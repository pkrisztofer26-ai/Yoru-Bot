from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
import asyncio
import random

from app.database import Database
from app.services.economy import CooldownError, EconomyService, JailError
from app.services.casino import CasinoService
from app import economy_config as eco
from app import casino_config as casino_cfg
from app.ui import money


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

    def __init__(self, database: Database, economy: EconomyService, casino: CasinoService | None = None) -> None:
        self.db = database
        self.economy = economy
        self.casino = casino or CasinoService(database)
        self._chicken_locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def _cooldown(self, guild_id: int, user_id: int, column: str, duration: timedelta) -> datetime:
        now = datetime.now(timezone.utc)
        last = await self.db.get_timestamp(guild_id, user_id, column)
        if last and now < last + duration:
            raise CooldownError(last + duration)
        return now

    async def _require_account_age(self, guild_id: int, user_id: int, days: int, label: str) -> None:
        profile = await self.db.get_profile(guild_id, user_id)
        created = datetime.fromisoformat(str(profile["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        ready = created + timedelta(days=days)
        if datetime.now(timezone.utc) < ready:
            raise ValueError(f"A {label} jutalomhoz legalább {days} napos Yoru account kell. Feloldás: <t:{int(ready.timestamp())}:R>.")

    async def weekly(self, guild_id: int, user_id: int) -> tuple[int, datetime]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "weekly")
        await self._require_account_age(guild_id, user_id, await self.economy.guild_settings.get_weekly_min_account_age_days(guild_id), "Weekly")
        cooldown = await self.economy.guild_settings.get_cooldown(guild_id, "weekly")
        now = await self._cooldown(guild_id, user_id, "last_weekly", cooldown)
        reward = random.randint(*(await self.economy.guild_settings.get_reward_range(guild_id, "weekly")))
        reward = await self.economy.apply_prestige_bonus(guild_id, user_id, reward, "weekly")
        await self.db.add_wallet(guild_id, user_id, reward, "weekly")
        await self.db.increment_stat(guild_id, user_id, "weekly_count")
        await self.economy.stats.increment(guild_id, user_id, "weekly.count")
        await self.economy.stats.add(guild_id, user_id, "weekly.earned", reward)
        await self.db.add_progression_xp(guild_id, user_id, eco.PROGRESSION_XP_REWARDS["weekly"], "weekly")
        await self.db.set_timestamp(guild_id, user_id, "last_weekly", now)
        return reward, now + cooldown

    async def monthly(self, guild_id: int, user_id: int) -> tuple[int, datetime]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "monthly")
        await self._require_account_age(guild_id, user_id, await self.economy.guild_settings.get_monthly_min_account_age_days(guild_id), "Monthly")
        cooldown = await self.economy.guild_settings.get_cooldown(guild_id, "monthly")
        now = await self._cooldown(guild_id, user_id, "last_monthly", cooldown)
        reward = random.randint(*(await self.economy.guild_settings.get_reward_range(guild_id, "monthly")))
        reward = await self.economy.apply_prestige_bonus(guild_id, user_id, reward, "monthly")
        await self.db.add_wallet(guild_id, user_id, reward, "monthly")
        await self.db.increment_stat(guild_id, user_id, "monthly_count")
        await self.economy.stats.increment(guild_id, user_id, "monthly.count")
        await self.economy.stats.add(guild_id, user_id, "monthly.earned", reward)
        await self.db.add_progression_xp(guild_id, user_id, eco.PROGRESSION_XP_REWARDS["monthly"], "monthly")
        await self.db.set_timestamp(guild_id, user_id, "last_monthly", now)
        return reward, now + cooldown

    async def interest(self, guild_id: int, user_id: int) -> tuple[int, int, datetime]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "interest")
        await self.economy.guild_settings.require_feature(guild_id, "bank")
        cooldown = await self.economy.guild_settings.get_cooldown(guild_id, "interest")
        now = await self._cooldown(guild_id, user_id, "last_interest", cooldown)
        _, bank = await self.db.get_balance(guild_id, user_id)
        interest_min_bank = await self.economy.guild_settings.get_interest_min_bank(guild_id)
        if bank < interest_min_bank:
            raise ValueError(f"Legalább {money(interest_min_bank)} kell a bankodban a kamathoz.")
        rate, cap = eco.INTEREST_TIERS[-1][1], eco.INTEREST_TIERS[-1][2]
        for minimum, tier_rate, tier_cap in eco.INTEREST_TIERS:
            if bank >= minimum:
                rate, cap = tier_rate, tier_cap
                break
        rate *= await self.economy.guild_settings.get_interest_rate_multiplier(guild_id)
        cap = int(cap * await self.economy.guild_settings.get_interest_cap_multiplier(guild_id))
        booster = await self.db.get_active_booster(guild_id, user_id, "interest_booster")
        if booster:
            # A booster a kamatlábat és a capet is emeli, különben a magasabb
            # bank tierben gyakorlatilag semmit sem érne.
            rate *= booster[0]
            cap = int(cap * booster[0])
        min_reward = await self.economy.guild_settings.get_interest_min_reward(guild_id)
        reward = min(cap, max(min_reward, int(bank * rate)))
        reward = await self.economy.apply_prestige_bonus(guild_id, user_id, reward, "interest")
        new_bank = await self.db.add_bank(guild_id, user_id, reward, "bank_interest")
        await self.economy.stats.increment(guild_id, user_id, "interest.claims")
        await self.economy.stats.add(guild_id, user_id, "interest.earned", reward)
        await self.db.add_progression_xp(guild_id, user_id, eco.PROGRESSION_XP_REWARDS["interest"], "interest")
        await self.db.set_timestamp(guild_id, user_id, "last_interest", now)
        return reward, new_bank, now + cooldown

    async def scratch(self, guild_id: int, user_id: int) -> tuple[str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "economy")
        if not await self.db.consume_item(guild_id, user_id, "lottery_ticket", 1):
            raise ValueError("Nincs Sorsjegyed. Vegyél egyet: `!buy lottery_ticket`.")

        # A luck a ritkább tier esélyét javítja, de nem tolja fel fixen a rollt.
        # Így egy 1.35x booster nem változtatja a jackpot esélyét 1%-ról ~9%-ra.
        luck_factor = 1.0
        luck = await self.db.get_active_booster(guild_id, user_id, "luck_booster")
        guild_luck = await self.db.get_guild_effect(guild_id, "luck_multiplier")
        if luck:
            luck_factor *= 1.0 + (max(1.0, float(luck[0])) - 1.0) * eco.SCRATCH_LUCK_STRENGTH
        if guild_luck:
            luck_factor *= 1.0 + (max(1.0, float(guild_luck[0])) - 1.0) * eco.SCRATCH_LUCK_STRENGTH
        roll = random.random() ** (1.0 / luck_factor)

        label, reward = "💨 Üres", 0
        for threshold, tier_label, minimum, maximum in eco.SCRATCH_TIERS:
            if roll <= threshold:
                label = tier_label
                reward = random.randint(minimum, maximum) if maximum > 0 else 0
                break

        wallet, _ = await self.db.get_balance(guild_id, user_id)
        if reward:
            wallet = await self.db.add_wallet(guild_id, user_id, reward, f"scratch:{label}")
        await self.db.increment_stat(guild_id, user_id, "scratch_count")
        await self.economy.stats.increment(guild_id, user_id, "scratch.count")
        if reward:
            await self.economy.stats.add(guild_id, user_id, "scratch.earned", reward)
            await self.economy.stats.set_max(guild_id, user_id, "scratch.biggest_reward", reward)
        else:
            await self.economy.stats.increment(guild_id, user_id, "scratch.empty")
        return label, reward, wallet

    async def give_item(self, guild_id: int, sender_id: int, receiver_id: int, item_id: str, quantity: int):
        return await self.db.transfer_item(guild_id, sender_id, receiver_id, item_id.lower().strip(), quantity)

    async def rps_visual(self, guild_id: int, user_id: int, choice: str, bet: int) -> ExtrasCasinoResult:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        aliases = {"rock":"rock","r":"rock","ko":"rock","kő":"rock","paper":"paper","p":"paper","papir":"paper","papír":"paper","scissors":"scissors","s":"scissors","ollo":"scissors","olló":"scissors"}
        player = aliases.get(choice.lower().strip())
        if player is None:
            raise ValueError("Válassz: `rock`, `paper` vagy `scissors`.")
        session = await self.casino.begin(
            guild_id, user_id, "rps", bet,
            config={"base_total": casino_cfg.RPS_V2_TOTAL_PAYOUT, "defer_player_lock_release": True, "engine": "rps_visual"},
        )
        try:
            bot = random.choice(["rock", "paper", "scissors"])
            if player == bot:
                payout = bet
                result = "tie"
            else:
                wins = {("rock","scissors"), ("paper","rock"), ("scissors","paper")}
                won = (player, bot) in wins
                total = self.casino.scaled_total_payout(casino_cfg.RPS_V2_TOTAL_PAYOUT, session)
                payout = int(bet * total) if won else 0
                result = "win" if won else "lose"
            settlement = await self.casino.settle(session, payout, result=f"{result}:{player}:{bot}", multiplier=(payout / bet) if bet else 0.0)
            return ExtrasCasinoResult(
                game_id=settlement.game_id, bet=settlement.bet, payout=settlement.payout, profit=settlement.profit,
                wallet=settlement.wallet, multiplier=settlement.multiplier, result=result, details={"player": player, "bot": bot},
            )
        except Exception:
            try: await self.casino.refund(session, "rps_visual_error")
            except ValueError: pass
            raise

    @staticmethod
    def _chicken_frames(won: bool) -> list[tuple[int, int, str]]:
        player_hp = 100
        opponent_hp = 100
        frames: list[tuple[int, int, str]] = [(player_hp, opponent_hp, "FIGHT!")]
        events = ["ATTACK", "DODGE", "CRITICAL", "COUNTER", "ATTACK"]
        for index, event in enumerate(events):
            if index == len(events) - 1:
                if won:
                    opponent_hp = 0
                    player_hp = max(18, player_hp)
                    event = "K.O.!"
                else:
                    player_hp = 0
                    opponent_hp = max(18, opponent_hp)
                    event = "K.O.!"
            elif (index % 2 == 0) == won:
                opponent_hp = max(1, opponent_hp - random.randint(14, 28))
            else:
                player_hp = max(1, player_hp - random.randint(12, 26))
            frames.append((player_hp, opponent_hp, event))
        return frames

    async def chickenfight_visual(self, guild_id: int, user_id: int, bet: int) -> ExtrasCasinoResult:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        lock = self._chicken_locks.setdefault((guild_id, user_id), asyncio.Lock())
        async with lock:
            if await self.db.get_item_quantity(guild_id, user_id, "chicken") < 1:
                raise ValueError("Chicken Fighthoz kell legalább 1 🐔 Chicken az inventorydban.")
            session = await self.casino.begin(
                guild_id, user_id, "chickenfight", bet,
                config={"win_chance": casino_cfg.CHICKEN_WIN_CHANCE, "base_total": casino_cfg.CHICKEN_TOTAL_PAYOUT, "defer_player_lock_release": True, "engine": "chicken_visual"},
            )
            try:
                opponents = ["Kopasz Kakas", "Vasöklű Kotlós", "Éjféli Csőr", "Piros Taraj", "Csirke Terminátor"]
                opponent = random.choice(opponents)
                won = random.random() < casino_cfg.CHICKEN_WIN_CHANCE
                total = self.casino.scaled_total_payout(casino_cfg.CHICKEN_TOTAL_PAYOUT, session)
                payout = int(bet * total) if won else 0
                settlement = await self.casino.settle(session, payout, result=f"{'win' if won else 'lose'}:{opponent}")
                if won:
                    await self.db.increment_stat(guild_id, user_id, "chicken_wins")
                else:
                    consumed = await self.db.consume_item(guild_id, user_id, "chicken", 1)
                    if consumed:
                        await self.economy.stats.increment(guild_id, user_id, "chicken.deaths")
                frames = self._chicken_frames(won)
                return ExtrasCasinoResult(
                    game_id=settlement.game_id, bet=settlement.bet, payout=settlement.payout, profit=settlement.profit,
                    wallet=settlement.wallet, multiplier=settlement.multiplier, result="win" if won else "lose",
                    details={"opponent": opponent, "frames": frames, "won": won},
                )
            except Exception:
                try: await self.casino.refund(session, "chicken_visual_error")
                except ValueError: pass
                raise

    async def chickenfight(self, guild_id: int, user_id: int, bet: int) -> tuple[bool, str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)

        lock = self._chicken_locks.setdefault((guild_id, user_id), asyncio.Lock())
        async with lock:
            if await self.db.get_item_quantity(guild_id, user_id, "chicken") < 1:
                raise ValueError("Chicken Fighthoz kell legalább 1 🐔 Chicken az inventorydban.")
            session = await self.casino.begin(
                guild_id, user_id, "chickenfight", bet,
                config={"win_chance": casino_cfg.CHICKEN_WIN_CHANCE, "base_total": casino_cfg.CHICKEN_TOTAL_PAYOUT},
            )
            try:
                opponents = ["Kopasz Kakas", "Vasöklű Kotlós", "Éjféli Csőr", "Piros Taraj", "Csirke Terminátor"]
                opponent = random.choice(opponents)
                won = random.random() < casino_cfg.CHICKEN_WIN_CHANCE
                total_payout = self.casino.scaled_total_payout(casino_cfg.CHICKEN_TOTAL_PAYOUT, session)
                payout = int(bet * total_payout) if won else 0
                settlement = await self.casino.settle(
                    session,
                    payout,
                    result=f"{'win' if won else 'lose'}:{opponent}",
                )
                if won:
                    await self.db.increment_stat(guild_id, user_id, "chicken_wins")
                else:
                    consumed = await self.db.consume_item(guild_id, user_id, "chicken", 1)
                    if consumed:
                        await self.economy.stats.increment(guild_id, user_id, "chicken.deaths")
                return won, opponent, abs(settlement.profit), settlement.wallet
            except Exception:
                # settle() is idempotent; refund only succeeds while the session is unfinished.
                try:
                    await self.casino.refund(session, "chickenfight_error")
                except ValueError:
                    pass
                raise

    async def highlow(self, guild_id: int, user_id: int, choice: str, bet: int) -> tuple[int, str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        normalized = choice.lower().strip()
        aliases = {"high": "high", "h": "high", "magas": "high", "low": "low", "l": "low", "alacsony": "low"}
        if normalized not in aliases:
            raise ValueError("Válassz: `high` vagy `low`.")
        normalized = aliases[normalized]
        session = await self.casino.begin(guild_id, user_id, "highlow", bet, config={"base_total": casino_cfg.HIGHLOW_TOTAL_PAYOUT})
        try:
            card = random.randint(1, 13)
            if card == 7:
                settlement = await self.casino.settle(session, bet, result=f"tie:{card}", multiplier=1.0)
                return card, "tie", 0, settlement.wallet
            won = (normalized == "high" and card > 7) or (normalized == "low" and card < 7)
            total_payout = self.casino.scaled_total_payout(casino_cfg.HIGHLOW_TOTAL_PAYOUT, session)
            payout = int(bet * total_payout) if won else 0
            settlement = await self.casino.settle(session, payout, result=f"{'win' if won else 'lose'}:{card}")
            return card, "win" if won else "lose", abs(settlement.profit), settlement.wallet
        except Exception:
            try:
                await self.casino.refund(session, "highlow_error")
            except ValueError:
                pass
            raise

    async def rps(self, guild_id: int, user_id: int, choice: str, bet: int) -> tuple[str, str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        aliases = {"rock":"rock","r":"rock","ko":"rock","kő":"rock","paper":"paper","p":"paper","papir":"paper","papír":"paper","scissors":"scissors","s":"scissors","ollo":"scissors","olló":"scissors"}
        player = aliases.get(choice.lower().strip())
        if player is None:
            raise ValueError("Válassz: `rock`, `paper` vagy `scissors`.")
        session = await self.casino.begin(guild_id, user_id, "rps", bet, config={"base_total": casino_cfg.RPS_TOTAL_PAYOUT})
        try:
            bot = random.choice(["rock", "paper", "scissors"])
            if player == bot:
                settlement = await self.casino.settle(session, bet, result=f"tie:{player}:{bot}", multiplier=1.0)
                return player, bot, 0, settlement.wallet
            wins = {("rock","scissors"), ("paper","rock"), ("scissors","paper")}
            won = (player, bot) in wins
            total_payout = self.casino.scaled_total_payout(casino_cfg.RPS_TOTAL_PAYOUT, session)
            payout = int(bet * total_payout) if won else 0
            settlement = await self.casino.settle(session, payout, result=f"{'win' if won else 'lose'}:{player}:{bot}")
            return player, bot, settlement.profit, settlement.wallet
        except Exception:
            try:
                await self.casino.refund(session, "rps_error")
            except ValueError:
                pass
            raise

