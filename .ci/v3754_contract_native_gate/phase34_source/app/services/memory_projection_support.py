from __future__ import annotations
__all__ = ['Any', 'Database', 'MemoryFact', 'MemorySnapshot', 'RelationshipState', '_KEY_RE', '_MEMORY_CATEGORIES', '_RIVAL_STATES', '_SUBJECT_TYPES', '_clean_key', '_iso', '_loads_dict', '_parse', '_safe_json_dict', '_utcnow', 'aiosqlite', 'dataclass', 'datetime', 'json', 're', 'timedelta', 'timezone']
'Canonical machine-readable consequence and relationship memory for Yoru RP.\n\n``character_history`` remains the player-facing life timeline.  This module owns\nstructured state that systems can safely query when deciding what should happen\nnext.  Keeping the two roles separate prevents UI prose from becoming gameplay\nauthority and avoids inventing a second history feed.\n'
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any
from app import db_backend as aiosqlite
from app.database import Database
_KEY_RE = re.compile('^[a-z0-9][a-z0-9_.:-]{0,63}$')
_MEMORY_CATEGORIES = frozenset({'decision', 'relationship', 'favor', 'agreement', 'rival', 'story', 'contract'})
_SUBJECT_TYPES = frozenset({'npc', 'faction', 'organization', 'world', 'contract', 'character', 'system'})
_RIVAL_STATES = frozenset({'none', 'tension', 'rival', 'resolved'})

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

def _clean_key(raw: str, *, label: str) -> str:
    value = str(raw).strip().lower()
    if not _KEY_RE.fullmatch(value):
        raise ValueError(f'Érvénytelen {label}: {raw!r}')
    return value

def _safe_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}

def _loads_dict(raw: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw or '{}'))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

@dataclass(frozen=True, slots=True)
class MemoryFact:
    memory_id: int
    guild_id: int
    user_id: int
    memory_key: str
    category: str
    subject_type: str
    subject_key: str
    state_key: str
    value: dict[str, Any]
    active: bool
    source_history_event_id: int | None
    occurred_at: str
    expires_at: str | None
    created_at: str
    updated_at: str

    @property
    def expired(self) -> bool:
        expires = _parse(self.expires_at)
        return bool(expires is not None and expires <= _utcnow())

@dataclass(frozen=True, slots=True)
class RelationshipState:
    guild_id: int
    user_id: int
    subject_type: str
    subject_key: str
    trust_score: int
    favor_owed_to_player: int
    favor_owed_by_player: int
    rival_state: str
    flags: dict[str, Any]
    last_memory_key: str | None
    created_at: str
    updated_at: str

    @property
    def trust_band(self) -> str:
        """Hidden score -> coarse semantic band. Raw numbers are not player UI."""
        score = int(self.trust_score)
        if score <= -60:
            return 'hostile'
        if score <= -20:
            return 'wary'
        if score < 20:
            return 'neutral'
        if score < 60:
            return 'warm'
        return 'trusted'

@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    facts: tuple[MemoryFact, ...]
    relationships: tuple[RelationshipState, ...]

    def has(self, memory_key: str) -> bool:
        wanted = str(memory_key).strip().lower()
        return any((item.memory_key == wanted and item.active and (not item.expired) for item in self.facts))

    def relationship(self, subject_type: str, subject_key: str) -> RelationshipState | None:
        wanted_type = str(subject_type).strip().lower()
        wanted_key = str(subject_key).strip().lower()
        for item in self.relationships:
            if item.subject_type == wanted_type and item.subject_key == wanted_key:
                return item
        return None
