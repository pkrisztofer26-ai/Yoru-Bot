from __future__ import annotations
__all__ = ['Any', 'ConsequenceMemoryService', 'MemoryFact', 'NPCConsequencePreset', 'NPCFollowupNotifier', 'NPC_CONSEQUENCE_PRESETS', 'Protocol', 'RelationshipState', '_fingerprint', 'dataclass', 'hashlib', 'log', 'logging', 'npc_config']
'Deterministic gameplay -> ConsequenceMemory adapters.\n\nAdapters are intentionally thin.  They may only be called after the owning\nservice has already settled its authoritative state.  A memory write is derived\nstate and must never become a prerequisite for wallet, inventory, career,\nqualification or other settlement.\n'
from dataclasses import dataclass
import hashlib
import logging
from typing import Any, Protocol
from app import npc_config
from app.services.memory import ConsequenceMemoryService, MemoryFact, RelationshipState
log = logging.getLogger('vaultbot.memory_adapters')

class NPCFollowupNotifier(Protocol):

    async def notify_after_consequence(self, guild_id: int, user_id: int, *, npc_key: str, preset_key: str, memory_key: str, relationship: RelationshipState | None) -> None:
        ...

    async def notify_first_contact(self, guild_id: int, user_id: int, *, npc_key: str, source_key: str, memory_key: str) -> None:
        ...

@dataclass(frozen=True, slots=True)
class NPCConsequencePreset:
    key: str
    state_key: str
    trust_delta: int = 0
    favor_to_player_delta: int = 0
    favor_by_player_delta: int = 0
    rival_state: str | None = None
    flags: tuple[tuple[str, bool], ...] = ()
NPC_CONSEQUENCE_PRESETS: dict[str, NPCConsequencePreset] = {'player_helped': NPCConsequencePreset('player_helped', 'player_helped', trust_delta=10, favor_to_player_delta=1, flags=(('player_helped', True),)), 'npc_helped': NPCConsequencePreset('npc_helped', 'npc_helped', trust_delta=6, favor_by_player_delta=1, flags=(('npc_helped', True),)), 'agreement_kept': NPCConsequencePreset('agreement_kept', 'agreement_kept', trust_delta=6, flags=(('agreement_kept', True),)), 'agreement_broken': NPCConsequencePreset('agreement_broken', 'agreement_broken', trust_delta=-12, flags=(('agreement_broken', True),)), 'betrayal': NPCConsequencePreset('betrayal', 'betrayal', trust_delta=-30, rival_state='tension', flags=(('betrayed_player', True),)), 'rival_escalated': NPCConsequencePreset('rival_escalated', 'rival_escalated', trust_delta=-20, rival_state='rival', flags=(('persistent_rival', True),)), 'rival_resolved': NPCConsequencePreset('rival_resolved', 'rival_resolved', trust_delta=12, rival_state='resolved', flags=(('persistent_rival', False),))}

def _fingerprint(*parts: Any, length: int=16) -> str:
    raw = '|'.join((str(part) for part in parts))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]
