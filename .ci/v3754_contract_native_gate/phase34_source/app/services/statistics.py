from __future__ import annotations
import inspect
import logging
from app.database import Database
GAME_LABELS: dict[str, tuple[str, str]] = {'blackjack': ('🃏', 'Blackjack'), 'coinflip': ('🪙', 'Coinflip'), 'roulette': ('🎡', 'Rulett'), 'slots': ('🎰', 'Nyerőgép'), 'dice': ('🎲', 'Dice'), 'highlow': ('🃏', 'High/Low'), 'rps': ('✂️', 'RPS'), 'chickenfight': ('🐔', 'Chicken Fight')}
logger = logging.getLogger(__name__)

class StatisticsService:
    """Központi, névtér-alapú statisztika API.

    A statok kulcsai ponttal tagolt névteret használnak, pl. ``work.count``
    vagy ``economy.earned``. Új stat hozzáadásához nem kell adatbázis-migráció.
    """

    def __init__(self, database: Database) -> None:
        self.db = database
        self._listeners: list = []

    async def _notify_listeners(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> None:
        for listener in tuple(self._listeners):
            try:
                result = listener(guild_id, user_id, stat_name, amount)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception('Statistics listener failed for %s', stat_name)

    async def get(self, guild_id: int, user_id: int, stat_name: str, default: int=0) -> int:
        value = await self.db.get_user_stat(guild_id, user_id, stat_name)
        return default if value is None else value

    async def increment(self, guild_id: int, user_id: int, stat_name: str, amount: int=1) -> int:
        return await self.add(guild_id, user_id, stat_name, amount)

    async def add(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> int:
        if amount <= 0:
            return await self.db.add_user_stat(guild_id, user_id, stat_name, amount)
        value = await self.db.add_user_stat(guild_id, user_id, stat_name, amount)
        await self._notify_listeners(guild_id, user_id, stat_name, amount)
        return value
