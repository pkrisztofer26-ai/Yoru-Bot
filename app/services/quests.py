from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random

from app.database import Database
from app import economy_config as eco
from app.progression_config import QUESTS_BY_PERIOD, QUEST_COUNT_PER_PERIOD, QuestDefinition
from app.services.statistics import StatisticsService


@dataclass(frozen=True)
class QuestProgress:
    slot: int
    definition: QuestDefinition
    progress: int
    target: int
    completed: bool
    claimed: bool


class QuestService:
    def __init__(self, database: Database, statistics: StatisticsService) -> None:
        self.db = database
        self.stats = statistics

    @staticmethod
    def period_key(period: str, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        if period == "daily":
            return now.date().isoformat()
        if period == "weekly":
            iso_year, iso_week, _ = now.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        raise ValueError("Ismeretlen quest periódus.")

    @staticmethod
    def reset_at(period: str, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        if period == "daily":
            tomorrow = now.date() + timedelta(days=1)
            return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
        if period == "weekly":
            days = 8 - now.isoweekday()
            next_monday = now.date() + timedelta(days=days)
            return datetime(next_monday.year, next_monday.month, next_monday.day, tzinfo=timezone.utc)
        raise ValueError("Ismeretlen quest periódus.")

    async def _ensure_assignments(self, guild_id: int, user_id: int, period: str) -> str:
        definitions = QUESTS_BY_PERIOD.get(period)
        if not definitions:
            raise ValueError("Ismeretlen quest periódus.")
        key = self.period_key(period)
        existing = await self.db.get_quest_assignments(guild_id, user_id, period, key)
        if existing:
            return key

        seed = f"yoru:{guild_id}:{user_id}:{period}:{key}"
        rng = random.Random(seed)
        selected = rng.sample(list(definitions), k=min(QUEST_COUNT_PER_PERIOD, len(definitions)))
        for slot, definition in enumerate(selected, start=1):
            current = await self.stats.get(guild_id, user_id, definition.stat)
            await self.db.create_quest_assignment(
                guild_id,
                user_id,
                period,
                key,
                slot,
                definition.quest_id,
                current,
                definition.target,
                definition.reward_xp,
                definition.reward_item,
            )
        return key

    async def get_quests(self, guild_id: int, user_id: int, period: str) -> list[QuestProgress]:
        key = await self._ensure_assignments(guild_id, user_id, period)
        rows = await self.db.get_quest_assignments(guild_id, user_id, period, key)
        lookup = {quest.quest_id: quest for quest in QUESTS_BY_PERIOD[period]}
        result: list[QuestProgress] = []
        for slot, quest_id, start_value, target, reward_xp, reward_item, claimed in rows:
            template = lookup.get(quest_id)
            if template is None:
                continue
            # A DB-ben tárolt reward/target az adott ciklus teljes időtartamára fix.
            definition = QuestDefinition(
                quest_id=template.quest_id,
                title=template.title,
                description=template.description,
                emoji=template.emoji,
                stat=template.stat,
                target=target,
                reward_xp=reward_xp,
                reward_item=reward_item,
            )
            current = await self.stats.get(guild_id, user_id, definition.stat)
            progress = max(0, min(target, current - start_value))
            result.append(
                QuestProgress(
                    slot=slot,
                    definition=definition,
                    progress=progress,
                    target=target,
                    completed=progress >= target,
                    claimed=claimed,
                )
            )
        return result

    async def claim(self, guild_id: int, user_id: int, period: str, slot: int) -> tuple[int, str | None]:
        quests = await self.get_quests(guild_id, user_id, period)
        quest = next((entry for entry in quests if entry.slot == slot), None)
        if quest is None:
            raise ValueError("Nincs ilyen quest slot.")
        if quest.claimed:
            raise ValueError("Ezt a quest jutalmat már átvetted.")
        if not quest.completed:
            raise ValueError(f"A quest még nincs kész: {quest.progress}/{quest.target}.")

        key = self.period_key(period)
        if not await self.db.claim_quest_assignment(guild_id, user_id, period, key, slot):
            raise ValueError("Ezt a quest jutalmat már átvetted.")

        await self.db.add_wallet(guild_id, user_id, quest.definition.reward_xp, f"quest:{period}:{quest.definition.quest_id}")
        if quest.definition.reward_item:
            await self.db.add_item(guild_id, user_id, quest.definition.reward_item, 1)
        await self.stats.increment(guild_id, user_id, f"quests.{period}.claimed")
        await self.stats.add(guild_id, user_id, f"quests.{period}.earned", quest.definition.reward_xp)
        xp_reward = int(eco.QUEST_PROGRESSION_XP.get(period, 0))
        if xp_reward > 0:
            await self.db.add_progression_xp(guild_id, user_id, xp_reward, f"quest_{period}")
            await self.stats.add(guild_id, user_id, f"quests.{period}.progression_xp", xp_reward)
        return quest.definition.reward_xp, quest.definition.reward_item

    async def claim_all(self, guild_id: int, user_id: int, period: str) -> tuple[int, list[str], int]:
        quests = await self.get_quests(guild_id, user_id, period)
        total_xp = 0
        items: list[str] = []
        claimed_count = 0
        for quest in quests:
            if not quest.completed or quest.claimed:
                continue
            try:
                xp, item = await self.claim(guild_id, user_id, period, quest.slot)
            except ValueError:
                continue
            total_xp += xp
            claimed_count += 1
            if item:
                items.append(item)
        return total_xp, items, claimed_count
