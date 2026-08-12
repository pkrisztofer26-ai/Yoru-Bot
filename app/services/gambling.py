from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import random
import secrets

from app import casino_config as casino_cfg
from app.casino_games import (
    RouletteBet,
    SlotSpin,
    evaluate_roulette_bets,
    parse_roulette_choice,
    roulette_result_emoji,
    run_slots_feature,
)
from app.database import Database
from app.services.casino import CasinoService, CasinoSession, CasinoSettlement
from app.ui import money


@dataclass(slots=True)
class GambleResult:
    won: bool
    profit: int
    wallet: int
    display: str
    game_id: str = ""
    payout: int = 0
    multiplier: float = 0.0
    jackpot_contribution: int = 0
    details: dict = field(default_factory=dict)


@dataclass(slots=True)
class QuickGameResult:
    game_id: str
    game: str
    bet: int
    payout: int
    profit: int
    wallet: int
    multiplier: float
    jackpot_contribution: int
    result: str
    details: dict = field(default_factory=dict)


@dataclass(slots=True)
class SlotsGameResult:
    game_id: str
    bet: int
    payout: int
    profit: int
    wallet: int
    multiplier: float
    jackpot_contribution: int
    spins: list[SlotSpin]


@dataclass(slots=True)
class RoulettePlayerState:
    user_id: int
    session_id: str
    bets: list[RouletteBet] = field(default_factory=list)
    settlement: CasinoSettlement | None = None
    winning_bets: list[RouletteBet] = field(default_factory=list)

    @property
    def total_bet(self) -> int:
        return sum(bet.amount for bet in self.bets)


@dataclass(slots=True)
class RouletteRound:
    round_id: str
    guild_id: int
    created_at: datetime
    closes_at: datetime
    status: str = "BETTING"
    players: dict[int, RoulettePlayerState] = field(default_factory=dict)
    result_number: int | None = None
    animation_numbers: list[int] = field(default_factory=list)
    settled_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    @property
    def total_bet(self) -> int:
        return sum(player.total_bet for player in self.players.values())

    @property
    def bet_count(self) -> int:
        return sum(len(player.bets) for player in self.players.values())


class GamblingService:
    MIN_BET = casino_cfg.MIN_BET
    RED_NUMBERS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

    def __init__(self, database: Database, casino: CasinoService | None = None) -> None:
        self.db = database
        self.casino = casino or CasinoService(database)
        self.guild_settings = self.casino.guild_settings
        self._roulette_rounds: dict[int, RouletteRound] = {}
        self._roulette_locks: dict[int, asyncio.Lock] = {}

    def _validate_bet(self, bet: int) -> None:
        if bet < self.MIN_BET:
            raise ValueError(f"A minimum tét {money(self.MIN_BET)}.")

    async def _ensure_available(self, guild_id: int, user_id: int) -> None:
        await self.casino._ensure_available(guild_id, user_id)

    async def payout_total(self, guild_id: int, base_total: float) -> float:
        """Backwards-compatible helper for non-session callers."""
        scale = await self.guild_settings.get_gambling_payout_multiplier(guild_id)
        return 1.0 + (float(base_total) - 1.0) * scale

    async def _settle_quick(self, session: CasinoSession, payout: int, display: str) -> GambleResult:
        settlement = await self.casino.settle(
            session,
            payout,
            result=display,
            multiplier=(float(payout) / float(session.bet)) if session.bet else 0.0,
        )
        return GambleResult(
            settlement.profit > 0,
            settlement.profit,
            settlement.wallet,
            display,
            game_id=settlement.game_id,
            payout=settlement.payout,
            multiplier=settlement.multiplier,
            jackpot_contribution=settlement.jackpot_contribution,
        )

    async def coinflip_visual(self, guild_id: int, user_id: int, choice: str, bet: int) -> QuickGameResult:
        normalized = choice.lower().strip()
        aliases = {"fej": "fej", "heads": "fej", "h": "fej", "írás": "írás", "iras": "írás", "tails": "írás", "t": "írás"}
        if normalized not in aliases:
            raise ValueError("A választás `fej` vagy `írás` legyen.")
        selected = aliases[normalized]
        session = await self.casino.begin(
            guild_id, user_id, "coinflip", bet,
            config={"base_total": casino_cfg.COINFLIP_V2_TOTAL_PAYOUT, "defer_player_lock_release": True, "engine": "coinflip_visual"},
        )
        try:
            rolled = random.choice(["fej", "írás"])
            won = selected == rolled
            total = self.casino.scaled_total_payout(casino_cfg.COINFLIP_V2_TOTAL_PAYOUT, session)
            payout = int(bet * total) if won else 0
            settlement = await self.casino.settle(session, payout, result=f"{'win' if won else 'lose'}:{selected}:{rolled}")
            return QuickGameResult(
                game_id=settlement.game_id, game="coinflip", bet=settlement.bet, payout=settlement.payout,
                profit=settlement.profit, wallet=settlement.wallet, multiplier=settlement.multiplier,
                jackpot_contribution=settlement.jackpot_contribution, result=settlement.result,
                details={"choice": selected, "rolled": rolled},
            )
        except Exception:
            try:
                await self.casino.refund(session, "coinflip_visual_error")
            except ValueError:
                pass
            raise

    async def dice_visual(self, guild_id: int, user_id: int, mode: str, bet: int, guess: int | None = None) -> QuickGameResult:
        aliases = {
            "exact": "exact", "number": "exact", "szam": "exact", "szám": "exact",
            "high": "high", "magas": "high", "low": "low", "alacsony": "low",
            "odd": "odd", "paratlan": "odd", "páratlan": "odd",
            "even": "even", "paros": "even", "páros": "even",
            "over": "over7", "over7": "over7", "under": "under7", "under7": "under7",
            "seven": "seven", "7": "seven", "exact7": "seven",
        }
        normalized = aliases.get(str(mode).lower().strip())
        if normalized is None:
            raise ValueError("Dice mód: exact, high, low, odd, even, over7, under7 vagy seven.")
        if normalized == "exact" and (guess is None or int(guess) < 1 or int(guess) > 6):
            raise ValueError("Exact módnál adj meg egy 1–6 közötti számot.")
        two_dice = normalized in {"over7", "under7", "seven"}
        session = await self.casino.begin(
            guild_id, user_id, "dice", bet,
            config={"engine": "dice_visual", "mode": normalized, "defer_player_lock_release": True},
        )
        try:
            dice = (random.randint(1, 6), random.randint(1, 6)) if two_dice else (random.randint(1, 6),)
            total_value = sum(dice)
            if normalized == "exact":
                won = dice[0] == int(guess)
                base_total = casino_cfg.DICE_V2_EXACT_TOTAL_PAYOUT
            elif normalized == "high":
                won = dice[0] >= 4; base_total = casino_cfg.DICE_V2_EVEN_TOTAL_PAYOUT
            elif normalized == "low":
                won = dice[0] <= 3; base_total = casino_cfg.DICE_V2_EVEN_TOTAL_PAYOUT
            elif normalized == "odd":
                won = dice[0] % 2 == 1; base_total = casino_cfg.DICE_V2_EVEN_TOTAL_PAYOUT
            elif normalized == "even":
                won = dice[0] % 2 == 0; base_total = casino_cfg.DICE_V2_EVEN_TOTAL_PAYOUT
            elif normalized == "over7":
                won = total_value > 7; base_total = casino_cfg.DICE_V2_OVER_UNDER_TOTAL_PAYOUT
            elif normalized == "under7":
                won = total_value < 7; base_total = casino_cfg.DICE_V2_OVER_UNDER_TOTAL_PAYOUT
            else:
                won = total_value == 7; base_total = casino_cfg.DICE_V2_EXACT_SEVEN_TOTAL_PAYOUT
            total = self.casino.scaled_total_payout(base_total, session)
            payout = int(bet * total) if won else 0
            result_text = f"{'win' if won else 'lose'}:{normalized}:{','.join(map(str,dice))}"
            settlement = await self.casino.settle(session, payout, result=result_text)
            return QuickGameResult(
                game_id=settlement.game_id, game="dice", bet=settlement.bet, payout=settlement.payout,
                profit=settlement.profit, wallet=settlement.wallet, multiplier=settlement.multiplier,
                jackpot_contribution=settlement.jackpot_contribution, result=settlement.result,
                details={"mode": normalized, "guess": guess, "dice": dice, "total": total_value},
            )
        except Exception:
            try:
                await self.casino.refund(session, "dice_visual_error")
            except ValueError:
                pass
            raise

    async def coinflip(self, guild_id: int, user_id: int, choice: str, bet: int) -> GambleResult:
        normalized = choice.lower().strip()
        aliases = {"fej": "fej", "heads": "fej", "h": "fej", "írás": "írás", "iras": "írás", "tails": "írás", "t": "írás"}
        if normalized not in aliases:
            raise ValueError("A választás `fej` vagy `írás` legyen.")
        selected = aliases[normalized]
        session = await self.casino.begin(guild_id, user_id, "coinflip", bet, config={"base_total": casino_cfg.COINFLIP_TOTAL_PAYOUT})
        try:
            rolled = random.choice(["fej", "írás"])
            won = selected == rolled
            total_payout = self.casino.scaled_total_payout(casino_cfg.COINFLIP_TOTAL_PAYOUT, session)
            payout = int(bet * total_payout) if won else 0
            return await self._settle_quick(session, payout, f"🪙 **{rolled.upper()}**")
        except Exception:
            await self.casino.refund(session, "coinflip_error")
            raise

    async def dice(self, guild_id: int, user_id: int, guess: int, bet: int) -> GambleResult:
        if guess < 1 or guess > 6:
            raise ValueError("A tipped 1 és 6 közötti szám legyen.")
        session = await self.casino.begin(guild_id, user_id, "dice", bet, config={"base_total": casino_cfg.DICE_TOTAL_PAYOUT})
        try:
            rolled = random.randint(1, 6)
            won = guess == rolled
            total_payout = self.casino.scaled_total_payout(casino_cfg.DICE_TOTAL_PAYOUT, session)
            payout = int(bet * total_payout) if won else 0
            return await self._settle_quick(session, payout, f"🎲 Dobás: **{rolled}** • tipped: **{guess}**")
        except Exception:
            await self.casino.refund(session, "dice_error")
            raise

    # ------------------------------------------------------------------ Slots V2
    async def slots_v2(self, guild_id: int, user_id: int, bet: int) -> SlotsGameResult:
        session = await self.casino.begin(
            guild_id,
            user_id,
            "slots",
            bet,
            config={"engine": "slots_v2", "paylines": len(casino_cfg.SLOTS_V2_PAYLINES), "defer_player_lock_release": True},
        )
        try:
            spins = run_slots_feature(bet)
            raw_payout = sum(spin.payout for spin in spins)
            scale = float(session.config.get("payout_scale", 1.0))
            # The guild gambling multiplier scales *winning profit*, not the
            # returned stake. Partial slot returns stay partial returns, while
            # a >1x feature only scales the amount above the original stake.
            if raw_payout > bet:
                payout = bet + int(round((raw_payout - bet) * scale))
            else:
                payout = max(0, int(raw_payout))
            line_count = sum(len(spin.line_wins) for spin in spins)
            free_count = max(0, len(spins) - 1)
            result = f"Slots • {line_count} nyerő line • {free_count} free spin"
            settlement = await self.casino.settle(
                session.game_id,
                payout,
                result=result,
                multiplier=(payout / bet) if bet else 0.0,
            )
            return SlotsGameResult(
                game_id=settlement.game_id,
                bet=settlement.bet,
                payout=settlement.payout,
                profit=settlement.profit,
                wallet=settlement.wallet,
                multiplier=settlement.multiplier,
                jackpot_contribution=settlement.jackpot_contribution,
                spins=spins,
            )
        except Exception:
            await self.casino.refund(session, "slots_v2_error")
            raise

    async def slots(self, guild_id: int, user_id: int, bet: int) -> GambleResult:
        """Compatibility wrapper; player entry points use ``slots_v2`` directly."""
        result = await self.slots_v2(guild_id, user_id, bet)
        last = result.spins[-1]
        display = "\n".join(" ".join(row) for row in last.grid)
        return GambleResult(
            result.profit > 0, result.profit, result.wallet, display,
            game_id=result.game_id, payout=result.payout, multiplier=result.multiplier,
            jackpot_contribution=result.jackpot_contribution,
        )

    # --------------------------------------------------------------- Roulette
    async def reserve_roulette_bet(
        self,
        guild_id: int,
        user_id: int,
        choice: str,
        bet: int,
        *,
        session_id: str | None = None,
        bet_index: int = 1,
    ) -> tuple[str, RouletteBet]:
        """Reserve one bet for a player-specific multi-bet roulette table."""
        self._validate_bet(bet)
        kind, number = parse_roulette_choice(choice)
        roulette_bet = RouletteBet(kind=kind, amount=int(bet), number=number)
        if session_id is None:
            session = await self.casino.begin(
                guild_id,
                user_id,
                "roulette",
                bet,
                config={"engine": "roulette_individual_multibet", "defer_player_lock_release": True},
            )
            await self.casino.mark_waiting(session.game_id)
            return session.game_id, roulette_bet

        row = await self.db.get_casino_session(session_id)
        if row is None or str(row.get("game")) != "roulette":
            raise ValueError("A Roulette session nem található.")
        if int(row.get("guild_id", 0)) != int(guild_id) or int(row.get("user_id", 0)) != int(user_id):
            raise ValueError("Ez nem a te Roulette játékod.")
        if str(row.get("status")) not in {"ACTIVE", "WAITING_INPUT"}:
            raise ValueError("Ez a Roulette kör már lezárult.")
        await self.casino.reserve_extra(
            session_id,
            bet,
            entry_type="BET_EXTRA",
            entry_key=f"roulette:bet:{int(bet_index)}",
            metadata={"kind": kind, "number": number},
        )
        return session_id, roulette_bet

    async def settle_roulette_bets(
        self,
        session_id: str,
        bets: list[RouletteBet],
        *,
        forced_number: int | None = None,
    ) -> GambleResult:
        if not bets:
            raise ValueError("Tegyél legalább egy fogadást a pörgetés előtt.")
        row = await self.db.get_casino_session(session_id)
        if row is None or str(row.get("game")) != "roulette":
            raise ValueError("A Roulette session nem található.")
        rolled = random.randint(0, 36) if forced_number is None else int(forced_number)
        if not 0 <= rolled <= 36:
            raise ValueError("A Roulette eredményének 0 és 36 között kell lennie.")
        total_bet = int(row.get("bet", 0))
        scale = float(row.get("config", {}).get("payout_scale", 1.0))
        payout, wins = evaluate_roulette_bets(bets, rolled, payout_scale=scale)
        settlement = await self.casino.settle(
            session_id,
            payout,
            result=f"{roulette_result_emoji(rolled)} Roulette: {rolled} • {len(bets)} bet",
            multiplier=(payout / total_bet) if total_bet else 0.0,
        )
        return GambleResult(
            settlement.profit > 0,
            settlement.profit,
            settlement.wallet,
            f"{roulette_result_emoji(rolled)} A golyó a **{rolled}** mezőn állt meg.",
            game_id=settlement.game_id,
            payout=settlement.payout,
            multiplier=settlement.multiplier,
            jackpot_contribution=settlement.jackpot_contribution,
            details={
                "number": rolled,
                "bets": bets,
                "winning_bets": wins,
                "total_bet": total_bet,
            },
        )

    async def refund_roulette_session(self, session_id: str, reason: str = "roulette_cancelled") -> dict:
        return await self.casino.refund(session_id, reason)

    # Legacy shared-round helpers remain for DB/test compatibility.
    def _roulette_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._roulette_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._roulette_locks[guild_id] = lock
        return lock

    @staticmethod
    def _new_roulette_round_id() -> str:
        return f"RT-{secrets.randbelow(900000) + 100000}"

    def current_roulette_round(self, guild_id: int) -> RouletteRound | None:
        return self._roulette_rounds.get(guild_id)

    async def place_roulette_bet(self, guild_id: int, user_id: int, choice: str, bet: int) -> RouletteRound:
        self._validate_bet(bet)
        kind, number = parse_roulette_choice(choice)
        lock = self._roulette_lock(guild_id)
        async with lock:
            now = datetime.now(timezone.utc)
            round_state = self._roulette_rounds.get(guild_id)
            if round_state is not None and round_state.status == "BETTING" and round_state.closes_at <= now:
                # Never replace an expired-but-not-yet-settled round: doing so
                # could orphan its reserved sessions before the resolver task runs.
                raise ValueError("A fogadás lezárult; a kerék mindjárt pörög. Várd meg az eredményt.")
            created_new = round_state is None or round_state.status != "BETTING"
            if created_new:
                round_state = RouletteRound(
                    round_id=self._new_roulette_round_id(),
                    guild_id=guild_id,
                    created_at=now,
                    closes_at=now + timedelta(seconds=casino_cfg.ROULETTE_V2_BETTING_SECONDS),
                )
                self._roulette_rounds[guild_id] = round_state

            player = round_state.players.get(user_id)
            if player is not None and len(player.bets) >= casino_cfg.ROULETTE_V2_MAX_BETS_PER_PLAYER:
                raise ValueError(f"Egy körben legfelj {casino_cfg.ROULETTE_V2_MAX_BETS_PER_PLAYER} külön fogadásod lehet.")

            roulette_bet = RouletteBet(kind=kind, amount=int(bet), number=number)
            if player is None:
                try:
                    session = await self.casino.begin(
                        guild_id,
                        user_id,
                        "roulette",
                        bet,
                        config={"engine": "roulette_v2", "round_id": round_state.round_id},
                    )
                except Exception:
                    if created_new and not round_state.players:
                        self._roulette_rounds.pop(guild_id, None)
                    raise
                await self.casino.mark_waiting(session.game_id)
                player = RoulettePlayerState(user_id=user_id, session_id=session.game_id)
                round_state.players[user_id] = player
                if created_new and round_state.task is None:
                    round_state.task = asyncio.create_task(self._auto_resolve_roulette(guild_id, round_state.round_id))
            else:
                await self.casino.reserve_extra(
                    player.session_id,
                    bet,
                    entry_type="BET_EXTRA",
                    entry_key=f"roulette:{round_state.round_id}:{len(player.bets) + 1}",
                    metadata={"kind": kind, "number": number},
                )
            player.bets.append(roulette_bet)
            return round_state

    async def _auto_resolve_roulette(self, guild_id: int, round_id: str) -> None:
        round_state = self._roulette_rounds.get(guild_id)
        if round_state is None or round_state.round_id != round_id:
            return
        delay = max(0.0, (round_state.closes_at - datetime.now(timezone.utc)).total_seconds())
        await asyncio.sleep(delay)
        try:
            await self.resolve_roulette_round(guild_id, round_id)
        except Exception:
            # Any unsettled player sessions are recovered/refunded by the
            # Casino Core on restart; runtime failures are refunded here too.
            current = self._roulette_rounds.get(guild_id)
            if current and current.round_id == round_id:
                for player in current.players.values():
                    try:
                        await self.casino.refund(player.session_id, "roulette_round_error")
                    except ValueError:
                        pass
                current.status = "CANCELLED"
                current.settled_event.set()

    async def resolve_roulette_round(self, guild_id: int, round_id: str | None = None, *, forced_number: int | None = None) -> RouletteRound:
        lock = self._roulette_lock(guild_id)
        async with lock:
            round_state = self._roulette_rounds.get(guild_id)
            if round_state is None or (round_id is not None and round_state.round_id != round_id):
                raise ValueError("Nincs ilyen aktív roulette kör.")
            if round_state.status in {"SETTLED", "CANCELLED"}:
                return round_state
            if round_state.status != "BETTING":
                return round_state
            round_state.status = "SPINNING"
            rolled = random.randint(0, 36) if forced_number is None else int(forced_number)
            if not 0 <= rolled <= 36:
                raise ValueError("A roulette eredményének 0 és 36 között kell lennie.")
            round_state.result_number = rolled
            decoys = [random.randint(0, 36) for _ in range(max(1, casino_cfg.ROULETTE_V2_SPIN_FRAMES - 1))]
            round_state.animation_numbers = decoys + [rolled]

        # Settle outside the round lock: DB transactions are already atomic and
        # we do not want UI bet attempts to deadlock behind multiple payouts.
        for player in round_state.players.values():
            row = await self.db.get_casino_session(player.session_id)
            scale = float((row or {}).get("config", {}).get("payout_scale", 1.0))
            payout, wins = evaluate_roulette_bets(player.bets, rolled, payout_scale=scale)
            player.winning_bets = wins
            player.settlement = await self.casino.settle(
                player.session_id,
                payout,
                result=f"{roulette_result_emoji(rolled)} Roulette: {rolled}",
                multiplier=(payout / player.total_bet) if player.total_bet else 0.0,
            )

        async with lock:
            round_state.status = "SETTLED"
            round_state.settled_event.set()
        asyncio.create_task(self._expire_roulette_round(guild_id, round_state.round_id))
        return round_state

    async def _expire_roulette_round(self, guild_id: int, round_id: str) -> None:
        await asyncio.sleep(casino_cfg.ROULETTE_V2_RESULT_GRACE_SECONDS)
        lock = self._roulette_lock(guild_id)
        async with lock:
            current = self._roulette_rounds.get(guild_id)
            if current is not None and current.round_id == round_id and current.status in {"SETTLED", "CANCELLED"}:
                self._roulette_rounds.pop(guild_id, None)

    async def roulette(self, guild_id: int, user_id: int, choice: str, bet: int) -> GambleResult:
        """Compatibility one-bet roulette wrapper on the individual multi-bet engine."""
        session_id, roulette_bet = await self.reserve_roulette_bet(guild_id, user_id, choice, bet)
        try:
            return await self.settle_roulette_bets(session_id, [roulette_bet])
        except Exception:
            try:
                await self.casino.refund(session_id, "roulette_error")
            except ValueError:
                pass
            raise

    # -------------------------------------------------------------- Blackjack V2
    async def reserve_blackjack(self, guild_id: int, user_id: int, bet: int) -> CasinoSession:
        return await self.casino.begin(
            guild_id,
            user_id,
            "blackjack",
            bet,
            config={
                "engine": "blackjack_v2",
                "win_total": casino_cfg.BLACKJACK_WIN_TOTAL_PAYOUT,
                "natural_total": casino_cfg.BLACKJACK_NATURAL_TOTAL_PAYOUT,
                "insurance_total": casino_cfg.BLACKJACK_INSURANCE_TOTAL_PAYOUT,
            },
        )

    async def reserve_blackjack_extra(self, session: CasinoSession | str, amount: int, *, key: str, kind: str) -> dict:
        game_id = session.game_id if isinstance(session, CasinoSession) else session
        return await self.casino.reserve_extra(
            game_id,
            amount,
            entry_type="BET_EXTRA",
            entry_key=key,
            metadata={"kind": kind},
        )

    async def resolve_blackjack(self, session: CasinoSession | str, payout: int, result: str = "blackjack") -> CasinoSettlement:
        # Use the game ID so Double/Split/Insurance extra reservations are read
        # from the current DB bet instead of the original in-memory base stake.
        game_id = session.game_id if isinstance(session, CasinoSession) else session
        row = await self.db.get_casino_session(game_id)
        current_bet = int((row or {}).get("bet", 0))
        return await self.casino.settle(
            game_id,
            payout,
            result=result,
            multiplier=(payout / current_bet) if current_bet else 0.0,
        )
