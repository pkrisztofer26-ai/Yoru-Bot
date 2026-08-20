from __future__ import annotations
from dataclasses import dataclass
import asyncio
from datetime import datetime, timezone
import secrets
from app.core.runtime import TaskSupervisor, spawn_background
from app import casino_config as cfg
from app.database import Database
from app.services.gameplay_settings import GameplaySettingsService
from app.text_hu import format_hu_relative

@dataclass(slots=True)
class CasinoSession:
    game_id: str
    guild_id: int
    user_id: int
    game: str
    bet: int
    wallet_after: int
    config: dict
    status: str = 'ACTIVE'

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
            from app.services.economy_events_settings import EconomyEventsSettingsService
            guild_settings = EconomyEventsSettingsService(database)
        self.guild_settings = guild_settings
        self.gameplay_settings = GameplaySettingsService(database)
        self._settlement_listener = None
        self._player_game_lock = asyncio.Lock()
        self._active_player_games: dict[tuple[int, int], str] = {}
        self._task_supervisor: TaskSupervisor | None = None

    def _spawn_background(self, coro, *, name: str) -> asyncio.Task:
        return spawn_background(coro, supervisor=self._task_supervisor, name=name, scope='service:casino')

    async def _claim_player_game(self, guild_id: int, user_id: int, game_id: str) -> None:
        key = (int(guild_id), int(user_id))
        async with self._player_game_lock:
            current = self._active_player_games.get(key)
            if current is not None and current != game_id:
                raise ValueError('Már fut egy kaszinójátékod. Várd meg, amíg befejeződik.')
            self._active_player_games[key] = game_id

    async def release_player_game(self, game_id: str) -> None:
        """Release the process-local player slot owned by ``game_id``."""
        async with self._player_game_lock:
            stale = [key for key, value in self._active_player_games.items() if value == game_id]
            for key in stale:
                self._active_player_games.pop(key, None)

    async def _ensure_available(self, guild_id: int, user_id: int) -> None:
        await self.guild_settings.require_feature(guild_id, 'gambling')
        until = await self.db.get_jail_until(guild_id, user_id)
        if until and until > datetime.now(timezone.utc):
            raise ValueError(f'Börtönben vagy még: {format_hu_relative(until)}')

    async def validate_bet(self, guild_id: int, bet: int) -> None:
        runtime = await self.gameplay_settings.casino(guild_id)
        if int(bet) < runtime.min_bet:
            raise ValueError(f'A minimum tét {runtime.min_bet:,}.'.replace(',', ' '))

    @staticmethod
    def game_prefix(game: str) -> str:
        return cfg.GAME_ID_PREFIXES.get(game, game[:3].upper() or 'GM')

    def new_game_id(self, game: str) -> str:
        return f'{self.game_prefix(game)}-{secrets.randbelow(90000000) + 10000000}'

    async def history(self, guild_id: int, user_id: int, *, limit: int=cfg.CASINO_HISTORY_PAGE_SIZE, offset: int=0) -> list[dict]:
        return await self.db.get_casino_history(guild_id, user_id, limit=limit, offset=offset)
