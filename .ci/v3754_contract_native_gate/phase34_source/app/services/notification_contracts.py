# STATIC_CONTRACT: category="contract"
from __future__ import annotations
'Gameplay notification intents for the future Yoru Telefon UX.\n\nThis is not a second notification backend.  It validates semantic delivery\nintents, then delegates persistence, dedupe, DM preference and Inbox behavior to\nthe existing NotificationService.\n'
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Protocol
from app import npc_config
_KEY_RE = re.compile('^[a-z0-9][a-z0-9_.:-]{0,95}$')
_INTERNAL_TERMS = ('trust_score', 'favor_owed_to_player', 'favor_owed_by_player', 'relationship_flags', 'crime_rep', 'raw reputation')

@dataclass(frozen=True, slots=True)
class GameplayNotificationIntent:
    intent_key: str
    category: str
    severity: str
    title: str
    body: str
    action_type: str | None = None
    action_ref: str | int | None = None
    action_label: str | None = None
    expires_at: datetime | str | None = None
    subject_type: str | None = None
    subject_key: str | None = None
    allow_dm: bool = True
    force_dm: bool = False

class NotificationDeliveryBackend(Protocol):

    async def notify(self, **kwargs: Any) -> dict[str, Any]:
        ...

class GameplayNotificationContract:
    ALLOWED_CATEGORIES = frozenset({'relationship', 'opportunity', 'contract', 'world', 'authority', 'economy', 'organization', 'heist'})
    ALLOWED_SEVERITIES = frozenset({'info', 'important', 'critical'})
    ALLOWED_SUBJECT_TYPES = frozenset({'npc', 'faction', 'organization', 'world', 'contract', 'character'})

    def __init__(self, notifications: NotificationDeliveryBackend) -> None:
        self.notifications = notifications

    @staticmethod
    def _clean_key(value: str, *, label: str) -> str:
        clean = str(value).strip().lower()
        if not _KEY_RE.fullmatch(clean):
            raise ValueError(f'Érvénytelen {label}: {value!r}')
        return clean

    @classmethod
    def validate(cls, intent: GameplayNotificationIntent) -> GameplayNotificationIntent:
        key = cls._clean_key(intent.intent_key, label='notification intent key')
        category = str(intent.category).strip().lower()
        severity = str(intent.severity).strip().lower()
        if category not in cls.ALLOWED_CATEGORIES:
            raise ValueError(f'Nem támogatott gameplay notification category: {category}')
        if severity not in cls.ALLOWED_SEVERITIES:
            raise ValueError(f'Nem támogatott gameplay notification severity: {severity}')
        title = str(intent.title).strip()
        body = str(intent.body).strip()
        if not title or not body:
            raise ValueError('A gameplay notification title/body nem lehet üres.')
        leaked = next((term for term in _INTERNAL_TERMS if term in f'{title} {body}'.casefold()), None)
        if leaked:
            raise ValueError(f'Player-facing notification nem tartalmazhat belső state mezőt: {leaked}')
        subject_type = str(intent.subject_type).strip().lower() if intent.subject_type else None
        subject_key = str(intent.subject_key).strip().lower() if intent.subject_key else None
        if (subject_type is None) != (subject_key is None):
            raise ValueError('subject_type és subject_key csak együtt adható meg.')
        if subject_type is not None:
            if subject_type not in cls.ALLOWED_SUBJECT_TYPES:
                raise ValueError(f'Nem támogatott notification subject type: {subject_type}')
            cls._clean_key(subject_key or '', label='notification subject key')
            if subject_type == 'npc':
                npc_config.npc(subject_key or '')
        return GameplayNotificationIntent(intent_key=key, category=category, severity=severity, title=title, body=body, action_type=str(intent.action_type).strip().lower() if intent.action_type else None, action_ref=intent.action_ref, action_label=str(intent.action_label).strip() if intent.action_label else None, expires_at=intent.expires_at, subject_type=subject_type, subject_key=subject_key, allow_dm=bool(intent.allow_dm), force_dm=bool(intent.force_dm))

    async def deliver(self, guild_id: int, user_id: int, intent: GameplayNotificationIntent) -> dict:
        checked = self.validate(intent)
        subject_suffix = f':{checked.subject_type}:{checked.subject_key}' if checked.subject_type else ''
        event_key = f'gameplay:{checked.intent_key}{subject_suffix}'
        return await self.notifications.notify(guild_id=guild_id, user_id=user_id, category=checked.category, severity=checked.severity, event_key=event_key, title=checked.title, body=checked.body, expires_at=checked.expires_at, action_type=checked.action_type, action_ref=checked.action_ref, action_label=checked.action_label, allow_dm=checked.allow_dm, force_dm=checked.force_dm)

    async def relationship_followup(self, guild_id: int, user_id: int, *, npc_key: str, event_key: str, title: str, body: str, important: bool=False) -> dict:
        npc = npc_config.npc(npc_key)
        return await self.deliver(guild_id, user_id, GameplayNotificationIntent(intent_key=f'relationship.{npc.key}.{event_key}', category='relationship', severity='important' if important else 'info', title=title, body=body, action_type='relationship', action_ref=npc.key, action_label='Megnyitás', subject_type='npc', subject_key=npc.key))

    async def private_opportunity(self, guild_id: int, user_id: int, *, opportunity_key: str, event_key: str, title: str, body: str, expires_at: datetime | str, npc_key: str | None=None) -> dict:
        subject_type = 'npc' if npc_key else None
        subject_key = npc_config.npc(npc_key).key if npc_key else None
        return await self.deliver(guild_id, user_id, GameplayNotificationIntent(intent_key=f'opportunity.{opportunity_key}.{event_key}', category='opportunity', severity='important', title=title, body=body, expires_at=expires_at, action_type='opportunity', action_ref=opportunity_key, action_label='Lehetőségeim', subject_type=subject_type, subject_key=subject_key))

    async def contract_update(self, guild_id: int, user_id: int, *, contract_id: int, event_key: str, title: str, body: str, expires_at: datetime | str | None=None, important: bool=False) -> dict:
        return await self.deliver(guild_id, user_id, GameplayNotificationIntent(intent_key=f'contract.{int(contract_id)}.{event_key}', category='contract', severity='important' if important else 'info', title=title, body=body, expires_at=expires_at, action_type='contract', action_ref=int(contract_id), action_label='Megbízás', subject_type='contract', subject_key=f'contract-{int(contract_id)}'))
