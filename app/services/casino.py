from __future__ import annotations

from dataclasses import dataclass
import asyncio
from datetime import datetime, timezone
import secrets

from app import casino_config as cfg
from app.database import Database


@dataclass(slots=True)
class CasinoSession:
    game_id: str
    guild_id: int
    user_id: int
    game: str
    bet: int
    wallet_after: int
    config: dict
    status: str = "ACTIVE"


@dataclass(slots=True)
class CasinoSettlement:
    game_id: str
    game: str
    bet: int
    payout: int
    profit: int
    multiplier: float
    wallet: int
    result: str
    jackpot_contribution: int = 0
    idempotent: bool = False


class CasinoService:
    """Shared Casino V2 session / money / audit engine.

    Game implementations decide the RNG/gameplay.  This service owns the money
    lifecycle so prefix/slash/UI entry points cannot accidentally diverge.
    """

    def __init__(self, database: Database, guild_settings=None) -> None:
        self.db = database
        if guild_settings is None:
            # Lazy import keeps the money/session engine testable without loading Discord UI modules.
            from app.services.economy_events_settings import EconomyEventsSettingsService
            guild_settings = EconomyEventsSettingsService(database)
        self.guild_settings = guild_settings
        self._settlement_listener = None
        # One active Casino game per player/guild. The in-memory guard covers
        # client-side animations that continue after the money settlement has
        # already committed (Slots/Roulette), while the DB reservation remains
        # the second line of defence against double-spend races.
        self._player_game_lock = asyncio.Lock()
        self._active_player_games: dict[tuple[int, int], str] = {}



    async def _claim_player_game(self, guild_id: int, user_id: int, game_id: str) -> None:
        key = (int(guild_id), int(user_id))
        async with self._player_game_lock:
            current = self._active_player_games.get(key)
            if current is not None and current != game_id:
                raise ValueError("Már fut egy Casino játékod. Várd meg, amíg befejeződik.")
            self._active_player_games[key] = game_id

    async def release_player_game(self, game_id: str) -> None:
        """Release the process-local player slot owned by ``game_id``."""
        async with self._player_game_lock:
            stale = [key for key, value in self._active_player_games.items() if value == game_id]
            for key in stale:
                self._active_player_games.pop(key, None)

    async def active_player_game(self, guild_id: int, user_id: int) -> str | None:
        async with self._player_game_lock:
            return self._active_player_games.get((int(guild_id), int(user_id)))

    def set_settlement_listener(self, listener) -> None:
        """Register an async best-effort listener for newly settled games.

        The money transaction is committed before the listener runs. Logging/UI
        failures must never roll back or duplicate a casino payout.
        """
        self._settlement_listener = listener

    async def _ensure_available(self, guild_id: int, user_id: int) -> None:
        await self.guild_settings.prepare_currency(guild_id)
        await self.guild_settings.require_feature(guild_id, "gambling")
        until = await self.db.get_jail_until(guild_id, user_id)
        if until and until > datetime.now(timezone.utc):
            raise ValueError(f"Börtönben vagy még: <t:{int(until.timestamp())}:R>")

    @staticmethod
    def validate_bet(bet: int) -> None:
        if bet < cfg.MIN_BET:
            raise ValueError(f"A minimum tét {cfg.MIN_BET:,}.".replace(",", " "))

    @staticmethod
    def game_prefix(game: str) -> str:
        return cfg.GAME_ID_PREFIXES.get(game, game[:3].upper() or "GM")

    def new_game_id(self, game: str) -> str:
        # 8 random decimal digits keep IDs readable in support/debug chats while
        # making collisions negligible.  The DB PK is still the final guard.
        return f"{self.game_prefix(game)}-{secrets.randbelow(90_000_000) + 10_000_000}"

    async def begin(self, guild_id: int, user_id: int, game: str, bet: int, *, config: dict | None = None) -> CasinoSession:
        await self._ensure_available(guild_id, user_id)
        self.validate_bet(bet)
        payout_scale = await self.guild_settings.get_gambling_payout_multiplier(guild_id)
        snapshot = {
            **(config or {}),
            "payout_scale": float(payout_scale),
            "jackpot_rate": float(cfg.MONTHLY_JACKPOT_CONTRIBUTION_RATE),
        }
        last_error: Exception | None = None
        for _ in range(5):
            game_id = self.new_game_id(game)
            try:
                await self._claim_player_game(guild_id, user_id, game_id)
                row = await self.db.reserve_casino_session(game_id, guild_id, user_id, game, bet, snapshot)
                return CasinoSession(
                    game_id=game_id,
                    guild_id=guild_id,
                    user_id=user_id,
                    game=game,
                    bet=bet,
                    wallet_after=int(row["wallet_after"]),
                    config=snapshot,
                )
            except ValueError as exc:
                await self.release_player_game(game_id)
                last_error = exc
                if "Game ID" not in str(exc):
                    raise
        raise RuntimeError("Nem sikerült egyedi Casino Game ID-t generálni.") from last_error

    @staticmethod
    def scaled_total_payout(base_total: float, session: CasinoSession | dict) -> float:
        config = session.config if isinstance(session, CasinoSession) else dict(session.get("config", {}))
        scale = float(config.get("payout_scale", 1.0))
        return 1.0 + (float(base_total) - 1.0) * scale

    async def reserve_extra(
        self,
        game_id: str,
        amount: int,
        *,
        entry_type: str = "BET_EXTRA",
        entry_key: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        return await self.db.add_casino_reservation(
            game_id, amount, entry_type=entry_type, entry_key=entry_key, metadata=metadata
        )

    async def mark_waiting(self, game_id: str) -> None:
        await self.db.set_casino_session_status(game_id, "WAITING_INPUT")

    async def settle(
        self,
        session: CasinoSession | str,
        payout: int,
        *,
        result: str,
        multiplier: float | None = None,
        house_loss_eligible: bool | None = None,
    ) -> CasinoSettlement:
        if isinstance(session, CasinoSession):
            game_id = session.game_id
            config = session.config
            game = session.game
            bet = session.bet
        else:
            game_id = session
            row = await self.db.get_casino_session(game_id)
            if row is None:
                raise ValueError("A Casino session nem található.")
            config = row.get("config", {})
            game = str(row["game"])
            bet = int(row["bet"])
        if multiplier is None:
            multiplier = (float(payout) / float(bet)) if bet > 0 else 0.0
        if house_loss_eligible is None:
            house_loss_eligible = game in cfg.HOUSE_GAMES
        data = await self.db.settle_casino_session(
            game_id,
            int(payout),
            result=result,
            multiplier=float(multiplier),
            jackpot_rate=float(config.get("jackpot_rate", cfg.MONTHLY_JACKPOT_CONTRIBUTION_RATE)),
            house_loss_eligible=bool(house_loss_eligible),
        )
        settlement = CasinoSettlement(
            game_id=game_id,
            game=game,
            bet=int(data["bet"]),
            payout=int(data["payout"]),
            profit=int(data["profit"]),
            multiplier=float(data["multiplier"]),
            wallet=int(data["wallet_after"]),
            result=str(data["result"]),
            jackpot_contribution=int(data.get("jackpot_contribution", 0)),
            idempotent=bool(data.get("idempotent", False)),
        )
        if self._settlement_listener is not None and not settlement.idempotent:
            try:
                await self._settlement_listener(settlement)
            except Exception:
                # Audit delivery is deliberately best-effort. The DB ledger is
                # the source of truth and the settlement is already committed.
                pass
        # Slots/Roulette keep the slot until their client-side animation has
        # been replaced by a static final frame. All other games release as
        # soon as their settlement is final.
        if not bool(config.get("defer_player_lock_release", False)):
            await self.release_player_game(game_id)
        return settlement

    async def refund(self, session: CasinoSession | str, reason: str = "cancelled") -> dict:
        game_id = session.game_id if isinstance(session, CasinoSession) else session
        try:
            return await self.db.refund_casino_session(game_id, reason)
        finally:
            await self.release_player_game(game_id)

    async def recover_after_restart(self) -> list[dict]:
        recovered = await self.db.recover_open_casino_sessions()
        async with self._player_game_lock:
            self._active_player_games.clear()
        return recovered

    async def history(self, guild_id: int, user_id: int, *, limit: int = cfg.CASINO_HISTORY_PAGE_SIZE, offset: int = 0) -> list[dict]:
        return await self.db.get_casino_history(guild_id, user_id, limit=limit, offset=offset)

    async def summary(self, guild_id: int, user_id: int) -> dict:
        return await self.db.get_casino_summary(guild_id, user_id)

    async def monthly_jackpot(self, guild_id: int, user_id: int | None = None, month: str | None = None) -> dict:
        return await self.db.get_monthly_casino_jackpot(guild_id, user_id, month)

    async def pending_jackpot_months(self, guild_id: int, before_month: str) -> list[str]:
        return await self.db.get_pending_casino_jackpot_months(guild_id, before_month)

    async def jackpot_eligible(self, guild_id: int, month: str) -> list[dict]:
        return await self.db.get_casino_jackpot_eligible(
            guild_id, month, min_games=cfg.MONTHLY_JACKPOT_MIN_GAMES, min_wager=cfg.MONTHLY_JACKPOT_MIN_WAGER,
        )

    async def jackpot_history(self, guild_id: int, limit: int = cfg.MONTHLY_JACKPOT_HISTORY_LIMIT) -> list[dict]:
        return await self.db.get_casino_jackpot_history(guild_id, limit)

    async def finalize_jackpot(self, guild_id: int, month: str, *, winner_id: int | None, eligible_players: int, rollover_month: str) -> dict:
        return await self.db.finalize_monthly_casino_jackpot(
            guild_id, month, winner_id=winner_id, eligible_players=eligible_players,
            payout_share=cfg.MONTHLY_JACKPOT_PAYOUT_SHARE, rollover_month=rollover_month,
        )
