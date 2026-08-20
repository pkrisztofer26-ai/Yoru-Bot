from __future__ import annotations
from .npc_followups_projection_support import *

class NPCFollowupServiceProjectionMixin01:

    def __init__(self, memory: ConsequenceMemoryService, adapters: MemoryAdapterService, notifications: GameplayNotificationContract | None=None) -> None:
        self.memory = memory
        self.adapters = adapters
        self.notifications = notifications

    @staticmethod
    def definition(npc_key: str) -> NPCFollowupDefinition:
        key = npc_config.npc(npc_key).key
        definition = FOLLOWUPS.get(key)
        if definition is None:
            raise ValueError('Ehhez az NPC-hez még nincs follow-up contract.')
        return definition

    async def candidates(self, guild_id: int, user_id: int) -> list[Opportunity]:
        await self.memory.age_resolved_relationships(guild_id, user_id, older_than_hours=RESOLVED_RELATIONSHIP_AGE_HOURS)
        snapshot = await self.memory.snapshot(guild_id, user_id, fact_limit=80)
        offers: list[Opportunity] = []
        for npc_key, definition in FOLLOWUPS.items():
            relationship = snapshot.relationship('npc', npc_key)
            if relationship is None:
                continue
            npc = npc_config.npc(npc_key)
            if relationship.rival_state == 'tension':
                offers.append(Opportunity(key=f'npc_tension_{npc.key}', emoji='⚠️', title=f'Rendezd a konfliktust {npc.with_name}', description=f'Maradt köztetek feszültség. Most megpróbálhatod tisztázni {npc.with_name}.', action_key=f'relationship:tension:{npc.key}', priority=92, source_family='relationship', rarity='uncommon', delivery_channel='phone', requirement_reason='npc_tension_followup', subject_type='npc', subject_key=npc.key, required_rival_states=('tension',)))
                continue
            if relationship.rival_state == 'rival':
                offers.append(Opportunity(key=f'npc_rival_{npc.key}', emoji='⚔️', title=f'Elmérgesedett a viszony {npc.with_name}', description=f'A konfliktus {npc.with_name} már tartósabb. Későbbi helyzetekben is visszatérhet.', action_key=f'relationship:rival:{npc.key}', priority=86, source_family='relationship', rarity='rare', delivery_channel='phone', requirement_reason='persistent_npc_rival', subject_type='npc', subject_key=npc.key, required_rival_states=('rival',), repeat_cooldown_hours=24))
                continue
            if int(relationship.favor_owed_to_player) > 0:
                offers.append(Opportunity(key=f'npc_favor_{npc.key}', emoji='🤝', title=definition.favor_title, description=definition.favor_body, action_key=f'favor:{npc.key}', priority=94, source_family='relationship', rarity='uncommon', delivery_channel='phone', requirement_reason='npc_favor_available', subject_type='npc', subject_key=npc.key, required_favor_to_player=1))
                continue
            contact_at = _parse_iso(relationship.flags.get('contact_unlocked_at'))
            contact_recent = bool(relationship.flags.get('contact_unlocked') and contact_at is not None and (datetime.now(timezone.utc) - contact_at <= timedelta(hours=FIRST_CONTACT_FOLLOWUP_HOURS)))
            relationship_signal = any((bool(relationship.flags.get(key)) for key in ('player_helped', 'npc_helped', 'agreement_kept')))
            if contact_recent and (not relationship_signal) and (relationship.trust_band == 'neutral'):
                offers.append(Opportunity(key=f'npc_contact_{npc.key}', emoji=npc.emoji, title=f'Új kapcsolat: {npc.display_name}', description=f'{npc.display_name} ({npc.role_label}) mostantól a Kapcsolatok között is megjelenhet. A hozzá tartozó későbbi ügyek innen is visszatérhetnek.', action_key=definition.destination_action, priority=76, source_family='relationship', rarity='uncommon', delivery_channel='phone', requirement_reason='npc_contact_unlocked', subject_type='npc', subject_key=npc.key, required_relationship_flags=('contact_unlocked',), repeat_cooldown_hours=FIRST_CONTACT_FOLLOWUP_HOURS))
                continue
            if relationship.trust_band in {'warm', 'trusted'} and relationship_signal:
                offers.append(Opportunity(key=f'npc_followup_{npc.key}', emoji=npc.emoji, title=definition.followup_title, description=definition.followup_body, action_key=definition.destination_action, priority=74, source_family='relationship', rarity='uncommon', delivery_channel='phone', requirement_reason='known_npc_followup', subject_type='npc', subject_key=npc.key, required_trust_bands=('warm', 'trusted'), repeat_cooldown_hours=24))
        return offers

    async def redeem_favor(self, guild_id: int, user_id: int, *, npc_key: str, cycle_id: str) -> FavorRedemptionResult:
        npc = npc_config.npc(npc_key)
        definition = self.definition(npc.key)
        current = await self.memory.relationship(guild_id, user_id, 'npc', npc.key)
        if current.rival_state in {'tension', 'rival'}:
            raise ValueError('Ezt a szívességet a köztetek lévő konfliktus miatt most nem tudod beváltani.')
        token = _fingerprint(npc.key, str(cycle_id), 'favor')
        memory_key = f'npc.{npc.key}:favor_redeemed:{token}'
        effect = npc_favor_config.effect_for_npc(npc.key)
        state_key = f'favor_effect.{effect.key}' if effect is not None else 'favor_redeemed'
        value = {'npc_key': npc.key, 'cycle_id': str(cycle_id), 'destination': definition.destination_action}
        if effect is not None:
            value.update({'effect_key': effect.key, 'effect_domain': effect.domain})
        fact, relationship, newly_consumed = await self.memory.consume_favor(guild_id, user_id, subject_type='npc', subject_key=npc.key, memory_key=memory_key, state_key=state_key, direction='to_player', value=value)
        if newly_consumed and self.notifications is not None:
            try:
                effect_note = f' {effect.player_description}' if effect is not None else f' {definition.destination_hint}'
                await self.notifications.relationship_followup(guild_id, user_id, npc_key=npc.key, event_key=f'favor_redeemed.{token}', title=f'🤝 {npc.display_name} visszaad egy szívességet', body=f'Beváltottál egy korábbi szívességet.{effect_note}', important=False)
            except Exception:
                log.exception('Favor redemption notification failed guild=%s user=%s npc=%s', guild_id, user_id, npc.key)
        return FavorRedemptionResult(npc_key=npc.key, npc_name=npc.display_name, destination_action=definition.destination_action, destination_label=definition.destination_label, remaining_favors=int(relationship.favor_owed_to_player), memory_key=fact.memory_key, newly_consumed=bool(newly_consumed), effect_key=effect.key if effect is not None else None, effect_label=effect.label if effect is not None else None, effect_description=effect.player_description if effect is not None else None)

    async def resolve_tension(self, guild_id: int, user_id: int, *, npc_key: str, cycle_id: str) -> TensionResolutionResult:
        npc = npc_config.npc(npc_key)
        relationship = await self.memory.relationship(guild_id, user_id, 'npc', npc.key)
        if relationship.rival_state == 'resolved':
            return TensionResolutionResult(npc.key, npc.display_name, 'resolved', str(relationship.last_memory_key or ''))
        if relationship.rival_state != 'tension':
            if relationship.rival_state == 'rival':
                raise ValueError('Ez a konfliktus már nem rendezhető egy gyors beszélgetéssel.')
            raise ValueError('Nincs olyan tisztázatlan konfliktus, amit most rendezhetnél.')
        token = _fingerprint(npc.key, str(cycle_id), str(relationship.last_memory_key or 'tension'), 'resolve')
        fact, updated = await self.adapters.npc_consequence(guild_id, user_id, npc_key=npc.key, event_key=f'tension_resolved:{token}', preset_key='rival_resolved', value={'cycle_id': str(cycle_id), 'resolution': 'player_opened_conversation'})
        state = updated.rival_state if updated is not None else 'resolved'
        return TensionResolutionResult(npc.key, npc.display_name, state, fact.memory_key)
