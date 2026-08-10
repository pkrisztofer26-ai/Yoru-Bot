from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import random

from app.database import Database
from app import economy_config as eco


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

    def _validate_bet(self, bet: int) -> None:
        if bet < self.MIN_BET:
            raise ValueError(f"A minimum tét ${self.MIN_BET:,}.".replace(",", " "))

    async def _ensure_available(self, guild_id: int, user_id: int) -> None:
        until = await self.db.get_jail_until(guild_id, user_id)
        if until and until > datetime.now(timezone.utc):
            raise ValueError(f"Börtönben vagy még: <t:{int(until.timestamp())}:R>")

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
        profit = int(bet * (eco.COINFLIP_TOTAL_PAYOUT - 1.0)) if won else -bet
        wallet = await self.db.settle_gamble(guild_id, user_id, bet, profit, "coinflip", won)
        return GambleResult(won, profit, wallet, f"🪙 **{rolled.upper()}**")

    async def dice(self, guild_id: int, user_id: int, guess: int, bet: int) -> GambleResult:
        await self._ensure_available(guild_id, user_id)
        self._validate_bet(bet)
        if guess < 1 or guess > 6:
            raise ValueError("A tipped 1 és 6 közötti szám legyen.")
        rolled = random.randint(1, 6)
        won = guess == rolled
        profit = int(bet * (eco.DICE_TOTAL_PAYOUT - 1.0)) if won else -bet
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
            profit = int(bet * (eco.ROULETTE_SINGLE_TOTAL_PAYOUT - 1.0)) if won else -bet
        else:
            kind = aliases[selected]
            won = (
                (kind == color)
                or (kind == "even" and rolled != 0 and rolled % 2 == 0)
                or (kind == "odd" and rolled % 2 == 1)
                or (kind == "low" and 1 <= rolled <= 18)
                or (kind == "high" and 19 <= rolled <= 36)
            )
            total_payout = eco.ROULETTE_SINGLE_TOTAL_PAYOUT if kind == "green" else eco.ROULETTE_EVEN_TOTAL_PAYOUT
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
