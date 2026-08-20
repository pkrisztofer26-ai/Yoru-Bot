# STATIC_CONTRACT: async def opportunities(
# STATIC_CONTRACT: self.opportunity_resolver.resolve
# STATIC_CONTRACT: async def record_opportunity_selection
# STATIC_CONTRACT: record_opportunity_outcome
# STATIC_CONTRACT: source_family: str | None = None
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import random
import uuid
from app import db_backend as aiosqlite
from app import world_config as cfg
from app import character_config
from app import heist_config
from app import jobs_config
from app.database import Database
from app.services.server_settings import ServerSettingsService
from app.services.memory import ConsequenceMemoryService
from app.services.opportunities import Opportunity, OpportunityResolver

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _iso(value: datetime | None=None) -> str:
    return (value or _utcnow()).isoformat()

def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

@dataclass(frozen=True, slots=True)
class WorldStoryProgress:
    story_key: str
    beat_key: str
    step_number: int
    started_at: str
    updated_at: str

    @property
    def story(self) -> cfg.WorldStory | None:
        return cfg.WORLD_STORY_BY_KEY.get(self.story_key)

    @property
    def beat(self) -> cfg.StoryBeat | None:
        story = self.story
        return story.beat(self.beat_key) if story is not None else None

@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    guild_id: int
    cycle_id: str
    national_key: str
    city_event_keys: dict[str, str]
    started_at: str
    expires_at: str
    story_key: str | None = None
    story_beat_key: str | None = None
    story_step: int = 0
    story_started_at: str | None = None

    @property
    def national(self) -> cfg.Situation:
        return cfg.NATIONAL_BY_KEY.get(self.national_key, cfg.NATIONAL_SITUATIONS[0])

    def city_situation(self, city_key: str) -> cfg.Situation:
        choices = cfg.CITY_SITUATIONS.get(city_key, ())
        if not choices:
            return cfg.Situation('quiet', '🏙️', 'Nyugodt helyi helyzet', 'Jelenleg nincs kiugró helyi esemény.')
        key = self.city_event_keys.get(city_key)
        return cfg.CITY_BY_KEY.get(city_key, {}).get(str(key), choices[0])

    @property
    def story(self) -> cfg.WorldStory | None:
        if not self.story_key:
            return None
        return cfg.WORLD_STORY_BY_KEY.get(self.story_key)

    @property
    def story_beat(self) -> cfg.StoryBeat | None:
        story = self.story
        if story is None or not self.story_beat_key:
            return None
        return story.beat(self.story_beat_key)

    @property
    def story_is_major(self) -> bool:
        beat = self.story_beat
        return bool(self.national.major_activity or (beat is not None and beat.major_activity))

@dataclass(frozen=True, slots=True)
class JobInfluence:
    multiplier: float
    note: str | None

@dataclass(frozen=True, slots=True)
class CrimeInfluence:
    multiplier: float
    note: str | None

@dataclass(frozen=True, slots=True)
class BusinessInfluence:
    multiplier: float
    note: str | None

from app.services.world_projection_mixin_01 import RPWorldServiceProjectionMixin01

class RPWorldService(RPWorldServiceProjectionMixin01):
    """Persistent hidden world-state and national story layer for Yoru RP.

    A world cycle is stable per guild. National stories can span multiple cycles,
    branch, resolve, and leave an internal history without exposing raw tuning or
    success percentages to players.
    """

    def __init__(self, database: Database, memory: ConsequenceMemoryService | None=None) -> None:
        self.database = database
        self.settings = ServerSettingsService(database)
        self.memory = memory or ConsequenceMemoryService(database)
        self.opportunity_resolver = OpportunityResolver(database, self.memory)
        self.npc_followups = None

    def bind_npc_followups(self, followups) -> None:
        self.npc_followups = followups

    @staticmethod
    def _story_row_to_progress(row) -> WorldStoryProgress | None:
        if row is None:
            return None
        return WorldStoryProgress(story_key=str(row[0]), beat_key=str(row[1]), step_number=int(row[2]), started_at=str(row[3]), updated_at=str(row[4]))

    @classmethod
    def _row_to_snapshot(cls, row, story_row=None) -> WorldSnapshot:
        try:
            city_events = json.loads(str(row[3]) or '{}')
        except json.JSONDecodeError:
            city_events = {}
        progress = cls._story_row_to_progress(story_row)
        return WorldSnapshot(guild_id=int(row[0]), cycle_id=str(row[1]), national_key=str(row[2]), city_event_keys=city_events, started_at=str(row[4]), expires_at=str(row[5]), story_key=progress.story_key if progress else None, story_beat_key=progress.beat_key if progress else None, story_step=progress.step_number if progress else 0, story_started_at=progress.started_at if progress else None)

    @staticmethod
    def _pick_different(rng: random.Random, items, previous_key: str | None):
        pool = [item for item in items if item.key != previous_key] or list(items)
        return rng.choice(pool)

    @staticmethod
    async def _load_story_progress(db, guild_id: int) -> WorldStoryProgress | None:
        cur = await db.execute('SELECT story_key,beat_key,step_number,started_at,updated_at FROM rp_world_story_state WHERE guild_id=?', (guild_id,))
        return RPWorldService._story_row_to_progress(await cur.fetchone())

    @staticmethod
    async def _save_story_progress(db, guild_id: int, progress: WorldStoryProgress | None) -> None:
        await db.execute('DELETE FROM rp_world_story_state WHERE guild_id=?', (guild_id,))
        if progress is not None:
            await db.execute('INSERT INTO rp_world_story_state(guild_id,story_key,beat_key,step_number,started_at,updated_at) VALUES(?,?,?,?,?,?)', (guild_id, progress.story_key, progress.beat_key, progress.step_number, progress.started_at, progress.updated_at))

    @staticmethod
    def _story_start(rng: random.Random, previous_key: str | None, now_iso: str) -> tuple[cfg.Situation, WorldStoryProgress] | None:
        candidates = []
        for story in cfg.WORLD_STORIES:
            beat = story.beat(story.start_beat)
            if beat is not None and beat.situation_key in cfg.NATIONAL_BY_KEY and (beat.situation_key != previous_key):
                candidates.append((story, beat))
        if not candidates:
            return None
        story, beat = rng.choice(candidates)
        return (cfg.NATIONAL_BY_KEY[beat.situation_key], WorldStoryProgress(story_key=story.key, beat_key=beat.key, step_number=1, started_at=now_iso, updated_at=now_iso))

    @staticmethod
    def _next_national(rng: random.Random, previous_key: str | None, progress: WorldStoryProgress | None, now_iso: str) -> tuple[cfg.Situation, WorldStoryProgress | None]:
        story_ended = False
        if progress is not None:
            story = progress.story
            beat = progress.beat
            if story is not None and beat is not None and beat.next_beats:
                next_key = rng.choice(beat.next_beats)
                next_beat = story.beat(next_key)
                if next_beat is not None and next_beat.situation_key in cfg.NATIONAL_BY_KEY:
                    return (cfg.NATIONAL_BY_KEY[next_beat.situation_key], WorldStoryProgress(story_key=story.key, beat_key=next_beat.key, step_number=progress.step_number + 1, started_at=progress.started_at, updated_at=now_iso))
            story_ended = True
        if not story_ended and rng.random() < cfg.WORLD_STORY_START_CHANCE:
            started = RPWorldService._story_start(rng, previous_key, now_iso)
            if started is not None:
                return started
        return (RPWorldService._pick_different(rng, cfg.NATIONAL_STANDALONE_SITUATIONS, previous_key), None)

    async def ensure_current(self, guild_id: int) -> WorldSnapshot:
        now = _utcnow()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            cur = await db.execute('SELECT guild_id,cycle_id,national_key,city_events_json,started_at,expires_at FROM rp_world_state WHERE guild_id=?', (guild_id,))
            row = await cur.fetchone()
            story_progress = await self._load_story_progress(db, guild_id)
            if row is not None:
                expires = _parse(str(row[5]))
                if expires is not None and expires > now:
                    await db.commit()
                    story_row = None if story_progress is None else (story_progress.story_key, story_progress.beat_key, story_progress.step_number, story_progress.started_at, story_progress.updated_at)
                    return self._row_to_snapshot(row, story_row)
            previous_national = str(row[2]) if row is not None else None
            try:
                previous_cities = json.loads(str(row[3]) or '{}') if row is not None else {}
            except json.JSONDecodeError:
                previous_cities = {}
            rng = random.SystemRandom()
            started = _iso(now)
            national, next_story = self._next_national(rng, previous_national, story_progress, started)
            city_map: dict[str, str] = {}
            for city_key in character_config.STARTING_CITY_KEYS:
                items = cfg.CITY_SITUATIONS.get(city_key, ())
                if not items:
                    continue
                picked = self._pick_different(rng, items, str(previous_cities.get(city_key) or ''))
                city_map[city_key] = picked.key
            cycle_id = uuid.uuid4().hex[:16]
            expires = _iso(now + timedelta(hours=cfg.WORLD_CYCLE_HOURS))
            payload = json.dumps(city_map, ensure_ascii=False, sort_keys=True)
            await db.execute('INSERT INTO rp_world_state(guild_id,cycle_id,national_key,city_events_json,started_at,expires_at,updated_at)\n                   VALUES(?,?,?,?,?,?,?)\n                   ON CONFLICT(guild_id) DO UPDATE SET\n                       cycle_id=excluded.cycle_id,national_key=excluded.national_key,\n                       city_events_json=excluded.city_events_json,started_at=excluded.started_at,\n                       expires_at=excluded.expires_at,updated_at=excluded.updated_at', (guild_id, cycle_id, national.key, payload, started, expires, started))
            await self._save_story_progress(db, guild_id, next_story)
            if next_story is not None:
                await db.execute('INSERT INTO rp_world_story_history(\n                           guild_id,cycle_id,story_key,beat_key,step_number,national_key,recorded_at\n                       ) VALUES(?,?,?,?,?,?,?)', (guild_id, cycle_id, next_story.story_key, next_story.beat_key, next_story.step_number, national.key, started))
            await db.commit()
            return WorldSnapshot(guild_id, cycle_id, national.key, city_map, started, expires, next_story.story_key if next_story else None, next_story.beat_key if next_story else None, next_story.step_number if next_story else 0, next_story.started_at if next_story else None)

