# STATIC_CONTRACT: Lifecycle retries/click replays are idempotent
# STATIC_CONTRACT: source_family: str | None = None
from __future__ import annotations
'Shared Opportunity Resolver / Eligibility orchestration for Yoru RP.\n\nThe existing ``RPWorldService.opportunities()`` remains the canonical candidate\nfactory and player-facing entry point.  This module only normalizes metadata,\nuses recent player choices for deterministic pacing, and ranks the candidates.\nIt does not settle rewards or bypass the owning domain service.\n'
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable
from app import db_backend as aiosqlite
from app.database import Database
from app.services.memory import ConsequenceMemoryService, MemorySnapshot

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
class Opportunity:
    key: str
    emoji: str
    title: str
    description: str
    action_key: str | None
    priority: int
    source_family: str = 'general'
    rarity: str = 'common'
    delivery_channel: str = 'panel'
    expires_at: str | None = None
    requirement_reason: str | None = None
    subject_type: str | None = None
    subject_key: str | None = None
    required_memory_keys: tuple[str, ...] = ()
    required_trust_bands: tuple[str, ...] = ()
    required_relationship_flags: tuple[str, ...] = ()
    required_favor_to_player: int = 0
    required_rival_states: tuple[str, ...] = ()
    repeat_cooldown_hours: int = 0

@dataclass(frozen=True, slots=True)
class OpportunityHistoryEntry:
    event_id: int
    guild_id: int
    user_id: int
    opportunity_key: str
    source_family: str
    action_key: str | None
    cycle_id: str | None
    event_type: str
    created_at: str

class OpportunityResolver:
    """Deterministic relevance/ranking layer above existing opportunity candidates."""

    def __init__(self, database: Database, memory: ConsequenceMemoryService) -> None:
        self.database = database
        self.memory = memory

    @staticmethod
    def source_family(item: Opportunity) -> str:
        if item.source_family and item.source_family != 'general':
            return str(item.source_family)
        key = str(item.key)
        action = str(item.action_key or '')
        if key.startswith(('shelter', 'rental', 'owned_home', 'premium_home')) or action.startswith('housing'):
            return 'housing'
        if key.startswith('training') or action == 'training' or key == 'driving_b':
            return 'training'
        if key.startswith('business') or action == 'business':
            return 'business'
        if key.startswith('organization') or action == 'organization':
            return 'organization'
        if key.startswith('travel_') or action == 'travel':
            return 'travel'
        if key.startswith('world_') or key == 'police_pressure' or action == 'blackmarket':
            return 'world'
        if key.startswith('heist') or action == 'heist':
            return 'heist'
        if key.startswith('crime_') or action.startswith('crime:'):
            return 'crime'
        if key.startswith('street_') or action.startswith('street:'):
            return 'street'
        if key.startswith(('career_', 'current_employment', 'world_job_')) or action == 'career' or action.startswith('job:'):
            return 'career'
        if key.startswith('vehicle') or key == 'first_car' or action == 'vehicles':
            return 'vehicle'
        return 'general'

    @staticmethod
    def rarity(item: Opportunity) -> str:
        if item.rarity and item.rarity != 'common':
            return str(item.rarity)
        if item.key in {'premium_home_private', 'world_black_market', 'heist_local'}:
            return 'rare'
        if item.key.startswith(('business_', 'organization_', 'travel_')):
            return 'uncommon'
        return 'common'

    @staticmethod
    def requirement_reason(item: Opportunity) -> str:
        if item.requirement_reason:
            return str(item.requirement_reason)
        family = OpportunityResolver.source_family(item)
        mapping = {'housing': 'current_housing_progression', 'training': 'qualification_or_active_training', 'business': 'business_state_or_entry_eligibility', 'organization': 'organization_membership', 'travel': 'world_signal_in_other_city', 'world': 'current_world_cycle', 'heist': 'city_police_and_progression_state', 'crime': 'crime_eligibility_and_police_state', 'street': 'street_state_and_cooldown', 'career': 'employment_and_world_demand', 'vehicle': 'vehicle_ownership_and_liquid_assets', 'relationship': 'relationship_memory_and_followup_state'}
        return mapping.get(family, 'current_character_context')

    @staticmethod
    def _is_early_life(finalized_at: str | None) -> bool:
        finalized = _parse(finalized_at)
        if finalized is None:
            return False
        return _utcnow() - finalized <= timedelta(days=7)

    @staticmethod
    def requirements_match(memory: MemorySnapshot, *, required_memory_keys: Iterable[str]=(), subject_type: str | None=None, subject_key: str | None=None, required_trust_bands: Iterable[str]=(), required_relationship_flags: Iterable[str]=(), required_favor_to_player: int=0, required_rival_states: Iterable[str]=()) -> bool:
        required_memory = tuple((str(item).strip().lower() for item in required_memory_keys if str(item).strip()))
        if required_memory and (not all((memory.has(item) for item in required_memory))):
            return False
        normalized_subject_type = str(subject_type).strip().lower() if subject_type else None
        normalized_subject_key = str(subject_key).strip().lower() if subject_key else None
        if (normalized_subject_type is None) != (normalized_subject_key is None):
            return False
        bands = tuple((str(item).strip().lower() for item in required_trust_bands if str(item).strip()))
        flags = tuple((str(item).strip() for item in required_relationship_flags if str(item).strip()))
        favor = max(0, int(required_favor_to_player or 0))
        rivals = tuple((str(item).strip().lower() for item in required_rival_states if str(item).strip()))
        if bands or flags or favor or rivals:
            if normalized_subject_type is None or normalized_subject_key is None:
                return False
            relationship = memory.relationship(normalized_subject_type, normalized_subject_key)
            if relationship is None:
                return False
            if bands and relationship.trust_band not in bands:
                return False
            if flags and (not all((bool(relationship.flags.get(flag)) for flag in flags))):
                return False
            if favor and int(relationship.favor_owed_to_player) < favor:
                return False
            if rivals and relationship.rival_state not in rivals:
                return False
        return True

    async def requirements_eligible(self, guild_id: int, user_id: int, **requirements) -> bool:
        memory = await self.memory.snapshot(guild_id, user_id, fact_limit=50)
        return self.requirements_match(memory, **requirements)

    async def recent_history(self, guild_id: int, user_id: int, *, limit: int=20) -> list[OpportunityHistoryEntry]:
        async with aiosqlite.connect(self.database.path) as db:
            cur = await db.execute('SELECT event_id,guild_id,user_id,opportunity_key,source_family,action_key,cycle_id,event_type,created_at\n                   FROM player_opportunity_history\n                   WHERE guild_id=? AND user_id=?\n                   ORDER BY event_id DESC LIMIT ?', (int(guild_id), int(user_id), max(1, min(100, int(limit)))))
            rows = await cur.fetchall()
        return [OpportunityHistoryEntry(event_id=int(row[0]), guild_id=int(row[1]), user_id=int(row[2]), opportunity_key=str(row[3]), source_family=str(row[4]), action_key=str(row[5]) if row[5] else None, cycle_id=str(row[6]) if row[6] else None, event_type=str(row[7]), created_at=str(row[8])) for row in rows]

    async def record_event(self, guild_id: int, user_id: int, *, opportunity_key: str, action_key: str | None, cycle_id: str | None, source_family: str | None=None, event_type: str='selected') -> int:
        key = str(opportunity_key).strip()[:96]
        if not key:
            raise ValueError('Az opportunity_key nem lehet üres.')
        event_type = str(event_type).strip().lower()
        if event_type not in {'selected', 'completed', 'resolved', 'dismissed'}:
            raise ValueError(f'Ismeretlen opportunity event type: {event_type}')
        family = (str(source_family).strip() if source_family else 'general')[:32] or 'general'
        cycle_value = str(cycle_id)[:32] if cycle_id else None
        now = _iso()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            existing_cur = await db.execute("SELECT event_id FROM player_opportunity_history\n                   WHERE guild_id=? AND user_id=? AND opportunity_key=? AND event_type=?\n                     AND COALESCE(cycle_id,'')=COALESCE(?,'')\n                   ORDER BY event_id ASC LIMIT 1", (int(guild_id), int(user_id), key, event_type, cycle_value))
            existing = await existing_cur.fetchone()
            if existing is not None:
                await db.commit()
                return int(existing[0])
            cursor = await db.execute('INSERT INTO player_opportunity_history(\n                       guild_id,user_id,opportunity_key,source_family,action_key,cycle_id,event_type,created_at\n                   ) VALUES(?,?,?,?,?,?,?,?)', (int(guild_id), int(user_id), key, family, str(action_key)[:96] if action_key else None, cycle_value, event_type, now))
            cutoff_cur = await db.execute('SELECT event_id FROM player_opportunity_history\n                   WHERE guild_id=? AND user_id=?\n                   ORDER BY event_id DESC LIMIT 1 OFFSET 199', (int(guild_id), int(user_id)))
            cutoff_row = await cutoff_cur.fetchone()
            if cutoff_row is not None:
                await db.execute('DELETE FROM player_opportunity_history WHERE guild_id=? AND user_id=? AND event_id<?', (int(guild_id), int(user_id), int(cutoff_row[0])))
            await db.commit()
            return int(cursor.lastrowid or 0)

    async def record_selection(self, guild_id: int, user_id: int, *, opportunity_key: str, action_key: str | None, cycle_id: str | None, source_family: str | None=None) -> int:
        return await self.record_event(guild_id, user_id, opportunity_key=opportunity_key, action_key=action_key, cycle_id=cycle_id, source_family=source_family, event_type='selected')

    async def resolve(self, guild_id: int, user_id: int, *, snapshot, character, candidates: Iterable[Opportunity], limit: int=5) -> list[Opportunity]:
        """Normalize, de-duplicate and rank current candidates.

        No candidate can bypass its owning domain service: this layer only ranks
        already eligible candidates produced by RPWorldService.
        """
        memory: MemorySnapshot = await self.memory.snapshot(guild_id, user_id, fact_limit=50)
        normalized: list[Opportunity] = []
        seen: set[str] = set()
        for raw in candidates:
            key = str(raw.key)
            if key in seen:
                continue
            seen.add(key)
            required_memory = tuple((str(item).strip().lower() for item in raw.required_memory_keys if str(item).strip()))
            subject_type = str(raw.subject_type).strip().lower() if raw.subject_type else None
            subject_key = str(raw.subject_key).strip().lower() if raw.subject_key else None
            required_bands = tuple((str(item).strip().lower() for item in raw.required_trust_bands if str(item).strip()))
            required_flags = tuple((str(item).strip() for item in raw.required_relationship_flags if str(item).strip()))
            required_favor = max(0, int(raw.required_favor_to_player or 0))
            required_rivals = tuple((str(item).strip().lower() for item in raw.required_rival_states if str(item).strip()))
            if not self.requirements_match(memory, required_memory_keys=required_memory, subject_type=subject_type, subject_key=subject_key, required_trust_bands=required_bands, required_relationship_flags=required_flags, required_favor_to_player=required_favor, required_rival_states=required_rivals):
                continue
            family = self.source_family(raw)
            normalized.append(replace(raw, source_family=family, rarity=self.rarity(raw), delivery_channel=str(raw.delivery_channel or 'panel'), expires_at=raw.expires_at or getattr(snapshot, 'expires_at', None), requirement_reason=self.requirement_reason(raw), subject_type=subject_type, subject_key=subject_key, required_memory_keys=required_memory, required_trust_bands=required_bands, required_relationship_flags=required_flags, required_favor_to_player=required_favor, required_rival_states=required_rivals, repeat_cooldown_hours=max(0, min(24 * 30, int(raw.repeat_cooldown_hours or 0)))))
        history = await self.recent_history(guild_id, user_id, limit=100)
        if history:
            now = _utcnow()
            filtered: list[Opportunity] = []
            for item in normalized:
                cooldown = max(0, int(item.repeat_cooldown_hours or 0))
                if cooldown:
                    cutoff = now - timedelta(hours=cooldown)
                    blocked = False
                    for entry in history:
                        if entry.opportunity_key != item.key or entry.event_type not in {'selected', 'completed', 'resolved'}:
                            continue
                        created = _parse(entry.created_at)
                        if created is not None and created >= cutoff:
                            blocked = True
                            break
                    if blocked:
                        continue
                filtered.append(item)
            normalized = filtered
        selected = [entry for entry in history if entry.event_type == 'selected']
        recent_keys = [entry.opportunity_key for entry in selected[:8]]
        recent_families = [entry.source_family for entry in selected[:5]]
        early_life = self._is_early_life(getattr(character, 'finalized_at', None))

        def score(item: Opportunity) -> tuple[int, int, str]:
            value = int(item.priority)
            critical = value >= 90
            if not critical and item.key in recent_keys[:3]:
                value -= 14
            if not critical and item.source_family in recent_families[:3]:
                value -= 4
            if early_life and item.source_family in {'housing', 'training', 'career', 'street'}:
                if item.source_family not in recent_families[:4]:
                    value += 4
            rarity_rank = {'rare': 2, 'uncommon': 1, 'common': 0}.get(item.rarity, 0)
            return (value, rarity_rank, item.key)
        normalized.sort(key=lambda item: (-score(item)[0], -score(item)[1], score(item)[2]))
        return normalized[:max(1, min(10, int(limit)))]
