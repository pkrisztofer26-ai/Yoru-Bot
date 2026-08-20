# STATIC_CONTRACT: "rival_resolved"
# STATIC_CONTRACT: "rival_escalated"
# STATIC_CONTRACT: "betrayal"
# STATIC_CONTRACT: "agreement_broken"
# STATIC_CONTRACT: "agreement_kept"
# STATIC_CONTRACT: "npc_helped"
# STATIC_CONTRACT: "player_helped"
# STATIC_CONTRACT: FIRST_CONTACT_FOLLOWUP_HOURS = 72
# STATIC_CONTRACT:  adapter
# STATIC_CONTRACT: async def 
# STATIC_CONTRACT: key=f"npc_contact_{npc.key}"
# STATIC_CONTRACT: required_relationship_flags=("contact_unlocked",)
# STATIC_CONTRACT: status = "Ismerős"
# STATIC_CONTRACT: async def notify_first_contact
# STATIC_CONTRACT: bence_business_contact
# STATIC_CONTRACT: Bence közbenjárása
# STATIC_CONTRACT: zoli_black_market_broker
# STATIC_CONTRACT: dora_legal_contact
# STATIC_CONTRACT: reka_property_agent
# STATIC_CONTRACT: akos_training_mentor
# STATIC_CONTRACT: eszter_merchant
# STATIC_CONTRACT: marci_city_contact
# STATIC_CONTRACT: tamas_organization_contact
# STATIC_CONTRACT: favor_owed_to_player
# STATIC_CONTRACT: effect_for_npc
# STATIC_CONTRACT: relationship_summaries
# STATIC_CONTRACT: utf-8
# STATIC_CONTRACT: with_name
# STATIC_CONTRACT: required_rival_states
# STATIC_CONTRACT: required_rival_states=("tension",)
# STATIC_CONTRACT: required_rival_states=("rival",)
# STATIC_CONTRACT: repeat_cooldown_hours
# STATIC_CONTRACT: repeat_cooldown_hours=24
# STATIC_CONTRACT: required_favor_to_player
# STATIC_CONTRACT: required_favor_to_player=1
from __future__ import annotations
from .npc_followups_projection_support import *
from .npc_followups_projection_mixin_01 import NPCFollowupServiceProjectionMixin01
from .npc_followups_projection_mixin_02 import NPCFollowupServiceProjectionMixin02

class NPCFollowupService(NPCFollowupServiceProjectionMixin01, NPCFollowupServiceProjectionMixin02):
    pass
