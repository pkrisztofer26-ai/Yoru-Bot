from __future__ import annotations

from datetime import datetime, timedelta, timezone
import asyncio
import random

from app.database import Database
from app.services.economy import CooldownError, EconomyService, JailError
from app import economy_config as eco


class ExtrasService:
    WEEKLY_COOLDOWN = eco.WEEKLY_COOLDOWN
    MONTHLY_COOLDOWN = eco.MONTHLY_COOLDOWN
    INTEREST_COOLDOWN = eco.INTEREST_COOLDOWN

    def __init__(self, database: Database, economy: EconomyService) -> None:
        self.db = database
        self.economy = economy
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
        await self._require_account_age(guild_id, user_id, eco.WEEKLY_MIN_ACCOUNT_AGE_DAYS, "Weekly")
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
        await self._require_account_age(guild_id, user_id, eco.MONTHLY_MIN_ACCOUNT_AGE_DAYS, "Monthly")
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
        if bank < eco.INTEREST_MIN_BANK:
            raise ValueError(f"Legalább {money(eco.INTEREST_MIN_BANK)} kell a bankodban a kamathoz.")
        rate, cap = eco.INTEREST_TIERS[-1][1], eco.INTEREST_TIERS[-1][2]
        for minimum, tier_rate, tier_cap in eco.INTEREST_TIERS:
            if bank >= minimum:
                rate, cap = tier_rate, tier_cap
                break
        booster = await self.db.get_active_booster(guild_id, user_id, "interest_booster")
        if booster:
            # A booster a kamatlábat és a capet is emeli, különben a magasabb
            # bank tierben gyakorlatilag semmit sem érne.
            rate *= booster[0]
            cap = int(cap * booster[0])
        reward = min(cap, max(eco.INTEREST_MIN_REWARD, int(bank * rate)))
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

    async def chickenfight(self, guild_id: int, user_id: int, bet: int) -> tuple[bool, str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        if bet < eco.GAMBLING_MIN_BET:
            raise ValueError(f"A minimum tét {money(eco.GAMBLING_MIN_BET)}.")

        lock = self._chicken_locks.setdefault((guild_id, user_id), asyncio.Lock())
        async with lock:
            if await self.db.get_item_quantity(guild_id, user_id, "chicken") < 1:
                raise ValueError("Chicken Fighthoz kell legalább 1 🐔 Chicken az inventorydban.")
            opponents = ["Kopasz Kakas", "Vasöklű Kotlós", "Éjféli Csőr", "Piros Taraj", "Csirke Terminátor"]
            opponent = random.choice(opponents)
            won = random.random() < eco.CHICKEN_WIN_CHANCE
            payout_scale = await self.economy.guild_settings.get_gambling_payout_multiplier(guild_id)
            total_payout = 1.0 + (eco.CHICKEN_TOTAL_PAYOUT - 1.0) * payout_scale
            profit = int(bet * (total_payout - 1.0)) if won else -bet
            wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "chickenfight", won)
            if won:
                await self.db.increment_stat(guild_id, user_id, "chicken_wins")
            else:
                # A Chicken most valódi fogyó harci eszköz: vereségnél meghal.
                consumed = await self.db.consume_item(guild_id, user_id, "chicken", 1)
                if consumed:
                    await self.economy.stats.increment(guild_id, user_id, "chicken.deaths")
            return won, opponent, abs(profit), wallet

    async def highlow(self, guild_id: int, user_id: int, choice: str, bet: int) -> tuple[int, str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        normalized = choice.lower().strip()
        aliases = {"high": "high", "h": "high", "magas": "high", "low": "low", "l": "low", "alacsony": "low"}
        if normalized not in aliases:
            raise ValueError("Válassz: `high` vagy `low`.")
        normalized = aliases[normalized]
        if bet < eco.GAMBLING_MIN_BET:
            raise ValueError(f"A minimum tét {money(eco.GAMBLING_MIN_BET)}.")
        card = random.randint(1, 13)
        if card == 7:
            wallet = await self.db.settle_gamble(guild_id, user_id, bet, 0, "highlow_tie", False)
            return card, "tie", 0, wallet
        won = (normalized == "high" and card > 7) or (normalized == "low" and card < 7)
        payout_scale = await self.economy.guild_settings.get_gambling_payout_multiplier(guild_id)
        total_payout = 1.0 + (eco.HIGHLOW_TOTAL_PAYOUT - 1.0) * payout_scale
        profit = int(bet * (total_payout - 1.0)) if won else -bet
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "highlow", won)
        return card, "win" if won else "lose", abs(profit), wallet

    async def rps(self, guild_id: int, user_id: int, choice: str, bet: int) -> tuple[str, str, int, int]:
        await self.economy.prepare_context(guild_id)
        await self.economy.guild_settings.require_feature(guild_id, "gambling")
        await self.economy.require_not_jailed(guild_id, user_id)
        aliases = {"rock":"rock","r":"rock","ko":"rock","kő":"rock","paper":"paper","p":"paper","papir":"paper","papír":"paper","scissors":"scissors","s":"scissors","ollo":"scissors","olló":"scissors"}
        player = aliases.get(choice.lower().strip())
        if player is None:
            raise ValueError("Válassz: `rock`, `paper` vagy `scissors`.")
        if bet < eco.GAMBLING_MIN_BET:
            raise ValueError(f"A minimum tét {money(eco.GAMBLING_MIN_BET)}.")
        bot = random.choice(["rock", "paper", "scissors"])
        if player == bot:
            wallet = await self.db.settle_gamble(guild_id, user_id, bet, 0, "rps_tie", False)
            return player, bot, 0, wallet
        wins = {("rock","scissors"), ("paper","rock"), ("scissors","paper")}
        won = (player, bot) in wins
        payout_scale = await self.economy.guild_settings.get_gambling_payout_multiplier(guild_id)
        total_payout = 1.0 + (eco.RPS_TOTAL_PAYOUT - 1.0) * payout_scale
        profit = int(bet * (total_payout - 1.0)) if won else -bet
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "rps", won)
        return player, bot, profit, wallet
