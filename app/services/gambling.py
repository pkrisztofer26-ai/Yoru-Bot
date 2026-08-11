from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import random

from app.database import Database
from app import economy_config as eco
from app.services.economy_events_settings import EconomyEventsSettingsService
from app.ui import money


@dataclass(slots=True)
class GambleResult:
    won: bool
    profit: int
    wallet: int
    display: str


class GamblingService:
    MIN_BET = eco.GAMBLING_MIN_BET

    RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

    def __init__(self, database: Database) -> None:
        self.db = database
        self.guild_settings = EconomyEventsSettingsService(database)

    def _validate_bet(self, bet: int) -> None:
        if bet < self.MIN_BET:
            raise ValueError(f"A minimum tét {money(self.MIN_BET)}.")

    async def _ensure_available(self, guild_id: int, user_id: int) -> None:
        await self.guild_settings.prepare_currency(guild_id)
        await self.guild_settings.require_feature(guild_id, "gambling")
        until = await self.db.get_jail_until(guild_id, user_id)
        if until and until > datetime.now(timezone.utc):
            raise ValueError(f"Börtönben vagy még: <t:{int(until.timestamp())}:R>")

    async def payout_total(self, guild_id: int, base_total: float) -> float:
        scale = await self.guild_settings.get_gambling_payout_multiplier(guild_id)
        # A szorzó a nyerő profit részét skálázza, így 1.00× pontosan a
        # v3.10.1 payoutokat adja vissza, és a tét visszafizetése nem duplázódik.
        return 1.0 + (float(base_total) - 1.0) * scale

    async def coinflip(self, guild_id: int, user_id: int, choice: str, bet: int) -> GambleResult:
        await self._ensure_available(guild_id, user_id)
        self._validate_bet(bet)
        normalized = choice.lower().strip()
        aliases = {"fej": "fej", "heads": "fej", "h": "fej", "írás": "írás", "iras": "írás", "tails": "írás", "t": "írás"}
        if normalized not in aliases:
            raise ValueError("A választás `fej` vagy `írás` legyen.")
        selected = aliases[normalized]
        rolled = random.choice(["fej", "írás"])
        won = selected == rolled
        total_payout = await self.payout_total(guild_id, eco.COINFLIP_TOTAL_PAYOUT)
        profit = int(bet * (total_payout - 1.0)) if won else -bet
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "coinflip", won)
        return GambleResult(won, profit, wallet, f"🪙 **{rolled.upper()}**")

    async def dice(self, guild_id: int, user_id: int, guess: int, bet: int) -> GambleResult:
        await self._ensure_available(guild_id, user_id)
        self._validate_bet(bet)
        if guess < 1 or guess > 6:
            raise ValueError("A tipped 1 és 6 közötti szám legyen.")
        rolled = random.randint(1, 6)
        won = guess == rolled
        total_payout = await self.payout_total(guild_id, eco.DICE_TOTAL_PAYOUT)
        profit = int(bet * (total_payout - 1.0)) if won else -bet
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "dice", won)
        return GambleResult(won, profit, wallet, f"🎲 Dobás: **{rolled}** • tipped: **{guess}**")

    async def slots(self, guild_id: int, user_id: int, bet: int) -> GambleResult:
        await self._ensure_available(guild_id, user_id)
        self._validate_bet(bet)
        symbols = list(eco.SLOTS_SYMBOLS)
        weights = list(eco.SLOTS_WEIGHTS)
        reels = random.choices(symbols, weights=weights, k=3)
        total_payout = 0.0
        if reels[0] == reels[1] == reels[2]:
            total_payout = eco.SLOTS_TRIPLE_TOTAL_PAYOUT[reels[0]]
        elif len(set(reels)) == 2:
            total_payout = eco.SLOTS_PAIR_TOTAL_PAYOUT
        if total_payout > 0:
            total_payout = await self.payout_total(guild_id, total_payout)
        profit = int(bet * total_payout) - bet
        won = profit > 0
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "slots", won)
        return GambleResult(won, profit, wallet, "┃ " + " ┃ ".join(reels) + " ┃")

    async def roulette(self, guild_id: int, user_id: int, choice: str, bet: int) -> GambleResult:
        await self._ensure_available(guild_id, user_id)
        self._validate_bet(bet)
        selected = choice.lower().strip()
        aliases = {
            "piros": "red", "red": "red", "r": "red",
            "fekete": "black", "black": "black", "b": "black",
            "zöld": "green", "zold": "green", "green": "green", "g": "green",
            "páros": "even", "paros": "even", "even": "even",
            "páratlan": "odd", "paratlan": "odd", "odd": "odd",
            "alacsony": "low", "low": "low", "1-18": "low",
            "magas": "high", "high": "high", "19-36": "high",
        }
        number_choice: int | None = None
        if selected.isdigit() and 0 <= int(selected) <= 36:
            number_choice = int(selected)
        elif selected not in aliases:
            raise ValueError("Válassz: `piros`, `fekete`, `zöld`, `páros`, `páratlan`, `alacsony`, `magas`, vagy egy számot 0–36 között.")

        rolled = random.randint(0, 36)
        color = "green" if rolled == 0 else ("red" if rolled in self.RED_NUMBERS else "black")
        if number_choice is not None:
            won = rolled == number_choice
            total_payout = await self.payout_total(guild_id, eco.ROULETTE_SINGLE_TOTAL_PAYOUT)
            profit = int(bet * (total_payout - 1.0)) if won else -bet
        else:
            kind = aliases[selected]
            won = (
                (kind == color)
                or (kind == "even" and rolled != 0 and rolled % 2 == 0)
                or (kind == "odd" and rolled % 2 == 1)
                or (kind == "low" and 1 <= rolled <= 18)
                or (kind == "high" and 19 <= rolled <= 36)
            )
            base_total = eco.ROULETTE_SINGLE_TOTAL_PAYOUT if kind == "green" else eco.ROULETTE_EVEN_TOTAL_PAYOUT
            total_payout = await self.payout_total(guild_id, base_total)
            profit = int(bet * (total_payout - 1.0)) if won else -bet
        emoji = "🟢" if color == "green" else ("🔴" if color == "red" else "⚫")
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "roulette", won)
        return GambleResult(won, profit, wallet, f"{emoji} A golyó a **{rolled}** mezőn állt meg.")

    async def reserve_blackjack(self, guild_id: int, user_id: int, bet: int) -> int:
        await self._ensure_available(guild_id, user_id)
        self._validate_bet(bet)
        return await self.db.reserve_gamble(guild_id, user_id, bet, "blackjack")

    async def resolve_blackjack(self, guild_id: int, user_id: int, bet: int, payout: int) -> int:
        return await self.db.resolve_reserved_gamble(guild_id, user_id, bet, payout, "blackjack")
