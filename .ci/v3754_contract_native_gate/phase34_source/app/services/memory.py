# STATIC_CONTRACT: async def record_consequence
# STATIC_CONTRACT: trust_band
# STATIC_CONTRACT: favor_owed_by_player=
# STATIC_CONTRACT: async def record_first_contact
# STATIC_CONTRACT: memory_key = _clean_key(f"npc.{npc_key}:first_contact"
# STATIC_CONTRACT: "contact_unlocked": True
# STATIC_CONTRACT: flags.setdefault("contact_source", first_source)
# STATIC_CONTRACT: async def age_resolved_relationships
# STATIC_CONTRACT: AND rival_state='resolved'
# STATIC_CONTRACT: async def active_favor_effect_tx
# STATIC_CONTRACT: active_favor_effect_tx
# STATIC_CONTRACT: async def consume_active_favor_effect_tx
# STATIC_CONTRACT: consume_active_favor_effect_tx
# STATIC_CONTRACT: trust_score
# STATIC_CONTRACT: idempotency boundary
# STATIC_CONTRACT: async def consume_favor
# STATIC_CONTRACT: favor_owed_to_player=favor_owed_to_player-1
from __future__ import annotations
from .memory_projection_support import *
from .memory_projection_mixin_01 import ConsequenceMemoryServiceProjectionMixin01
from .memory_projection_mixin_02 import ConsequenceMemoryServiceProjectionMixin02
from .memory_projection_mixin_03 import ConsequenceMemoryServiceProjectionMixin03
from .memory_projection_mixin_04 import ConsequenceMemoryServiceProjectionMixin04

class ConsequenceMemoryService(ConsequenceMemoryServiceProjectionMixin01, ConsequenceMemoryServiceProjectionMixin02, ConsequenceMemoryServiceProjectionMixin03, ConsequenceMemoryServiceProjectionMixin04):
    """Structured consequence memory with an immutable-ish semantic key model.

    ``record_consequence`` is the preferred write path: it updates one named
    memory fact and, when requested, the corresponding relationship state in one
    transaction.  It never mutates wallet, inventory, XP, police state or world
    state; those remain owned by their existing deterministic services.
    """
