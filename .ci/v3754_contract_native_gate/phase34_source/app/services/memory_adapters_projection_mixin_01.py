from __future__ import annotations
from .memory_adapters_projection_support import *

class MemoryAdapterServiceProjectionMixin01:

    def __init__(self, memory: ConsequenceMemoryService) -> None:
        self.memory = memory
        self.followups: NPCFollowupNotifier | None = None

    def bind_followups(self, followups: NPCFollowupNotifier | None) -> None:
        self.followups = followups

    async def npc_first_contact(self, guild_id: int, user_id: int, *, npc_key: str, source_key: str, occurred_at: str, value: dict[str, Any] | None=None) -> tuple[MemoryFact, RelationshipState, bool]:
        npc = npc_config.npc(npc_key)
        clean_source = str(source_key).strip().lower()
        allowed = npc_config.first_contact_sources(npc.key)
        if clean_source not in allowed:
            raise ValueError(f'Nem engedélyezett first-contact source {npc.key}: {source_key}')
        fact, relationship, newly_unlocked = await self.memory.record_first_contact(guild_id, user_id, npc_key=npc.key, source_key=clean_source, occurred_at=occurred_at, value=value)
        if newly_unlocked and self.followups is not None:
            try:
                await self.followups.notify_first_contact(guild_id, user_id, npc_key=npc.key, source_key=clean_source, memory_key=fact.memory_key)
            except Exception:
                log.exception('NPC first-contact notification failed guild=%s user=%s npc=%s source=%s', guild_id, user_id, npc.key, clean_source)
        return (fact, relationship, newly_unlocked)

    async def training_enrolled(self, guild_id: int, user_id: int, *, course_key: str, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        return await self.npc_first_contact(guild_id, user_id, npc_key='akos_training_mentor', source_key='training_enrolled', occurred_at=occurred_at, value={'course_key': str(course_key)})

    async def housing_purchased(self, guild_id: int, user_id: int, *, tier_key: str, city_key: str, property_id: int | None, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        return await self.npc_first_contact(guild_id, user_id, npc_key='reka_property_agent', source_key='housing_purchase', occurred_at=occurred_at, value={'tier_key': str(tier_key), 'city_key': str(city_key), 'property_id': property_id})

    async def travel_completed(self, guild_id: int, user_id: int, *, from_city_key: str, to_city_key: str, mode_key: str, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        return await self.npc_first_contact(guild_id, user_id, npc_key='marci_city_contact', source_key='travel_completed', occurred_at=occurred_at, value={'from_city_key': str(from_city_key), 'to_city_key': str(to_city_key), 'mode_key': str(mode_key)})

    async def black_market_purchased(self, guild_id: int, user_id: int, *, item_id: str, quantity: int, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        return await self.npc_first_contact(guild_id, user_id, npc_key='zoli_black_market_broker', source_key='black_market_purchase', occurred_at=occurred_at, value={'item_id': str(item_id), 'quantity': int(quantity)})

    async def player_market_trade(self, guild_id: int, user_id: int, *, listing_id: int, role: str, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        clean_role = str(role).strip().lower()
        if clean_role not in {'buyer', 'seller'}:
            raise ValueError(f'Ismeretlen player-market szerep: {role}')
        return await self.npc_first_contact(guild_id, user_id, npc_key='eszter_merchant', source_key='player_market_trade', occurred_at=occurred_at, value={'listing_id': int(listing_id), 'role': clean_role})

    async def organization_membership(self, guild_id: int, user_id: int, *, crew_id: int, event: str, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        clean_event = str(event).strip().lower()
        if clean_event not in {'created', 'joined'}:
            raise ValueError(f'Ismeretlen organization contact event: {event}')
        source_key = 'organization_created' if clean_event == 'created' else 'organization_joined'
        return await self.npc_first_contact(guild_id, user_id, npc_key='tamas_organization_contact', source_key=source_key, occurred_at=occurred_at, value={'crew_id': int(crew_id), 'event': clean_event})

    async def police_incident(self, guild_id: int, user_id: int, *, source_key: str, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        return await self.npc_first_contact(guild_id, user_id, npc_key='dora_legal_contact', source_key=source_key, occurred_at=occurred_at)

    async def business_property_purchased(self, guild_id: int, user_id: int, *, property_id: int, city: str, occurred_at: str) -> tuple[MemoryFact, RelationshipState, bool]:
        return await self.npc_first_contact(guild_id, user_id, npc_key='eszter_merchant', source_key='business_property_purchased', occurred_at=occurred_at, value={'property_id': int(property_id), 'city': str(city)})

    async def career_hired(self, guild_id: int, user_id: int, *, career_key: str, city_key: str, hired_at: str, source_history_event_id: int | None=None) -> MemoryFact:
        token = source_history_event_id or _fingerprint(career_key, city_key, hired_at)
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'career.hired:{token}', category='contract', subject_type='contract', subject_key=f'career.{str(career_key).strip().lower()}', state_key='career_hired', value={'career_key': str(career_key), 'city_key': str(city_key), 'hired_at': str(hired_at)}, source_history_event_id=source_history_event_id, occurred_at=hired_at)
        return fact

    async def career_quit(self, guild_id: int, user_id: int, *, career_key: str, city_key: str, hired_at: str, ended_at: str, source_history_event_id: int | None=None) -> MemoryFact:
        token = source_history_event_id or _fingerprint(career_key, hired_at, ended_at)
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'career.quit:{token}', category='contract', subject_type='contract', subject_key=f'career.{str(career_key).strip().lower()}', state_key='career_quit', value={'career_key': str(career_key), 'city_key': str(city_key), 'hired_at': str(hired_at), 'ended_at': str(ended_at)}, source_history_event_id=source_history_event_id, occurred_at=ended_at)
        return fact

    async def training_completed(self, guild_id: int, user_id: int, *, course_key: str, completed_at: str, source_history_event_id: int | None=None) -> MemoryFact:
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'training.completed:{str(course_key).strip().lower()}', category='story', subject_type='character', subject_key='training', state_key=f'qualification_{str(course_key).strip().lower()}', value={'course_key': str(course_key), 'completed_at': str(completed_at)}, source_history_event_id=source_history_event_id, occurred_at=completed_at)
        await self.npc_first_contact(guild_id, user_id, npc_key='akos_training_mentor', source_key='training_completed', occurred_at=completed_at, value={'course_key': str(course_key)})
        return fact

    async def business_license_purchased(self, guild_id: int, user_id: int, *, paid: int, base_price: int, discount_saved: int, favor_effect_key: str | None, occurred_at: str) -> MemoryFact:
        token = _fingerprint('business_license', guild_id, user_id, occurred_at, paid)
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'business.license:{token}', category='contract', subject_type='contract', subject_key='business.license', state_key='license_purchased', value={'paid': int(paid), 'base_price': int(base_price), 'discount_saved': int(discount_saved), 'favor_effect_key': favor_effect_key}, occurred_at=occurred_at)
        await self.npc_first_contact(guild_id, user_id, npc_key='bence_business_contact', source_key='business_license_purchased', occurred_at=occurred_at, value={'paid': int(paid)})
        return fact

    async def vehicle_repaired(self, guild_id: int, user_id: int, *, vehicle_id: int, model_key: str, old_condition_key: str, new_condition_key: str, paid: int, base_price: int, discount_saved: int, favor_effect_key: str | None, occurred_at: str) -> MemoryFact:
        token = _fingerprint(vehicle_id, old_condition_key, new_condition_key, occurred_at)
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'vehicle.repair:{token}', category='story', subject_type='character', subject_key='vehicles', state_key='vehicle_repaired', value={'vehicle_id': int(vehicle_id), 'model_key': str(model_key), 'old_condition_key': str(old_condition_key), 'new_condition_key': str(new_condition_key), 'paid': int(paid), 'base_price': int(base_price), 'discount_saved': int(discount_saved), 'favor_effect_key': favor_effect_key}, occurred_at=occurred_at)
        return fact

    async def crime_resolved(self, guild_id: int, user_id: int, *, event_key: str, success: bool, scenario: str, amount: int, jailed: bool, occurred_at: str) -> MemoryFact:
        token = _fingerprint('crime', event_key, guild_id, user_id)
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'crime.result:{token}', category='story', subject_type='character', subject_key='crime', state_key='crime_resolved', value={'success': bool(success), 'scenario': str(scenario), 'amount': int(amount), 'jailed': bool(jailed)}, occurred_at=occurred_at)
        if success:
            await self.npc_first_contact(guild_id, user_id, npc_key='zoli_black_market_broker', source_key='crime_success', occurred_at=occurred_at, value={'scenario': str(scenario)})
        return fact

    async def heist_resolved(self, guild_id: int, user_id: int, *, lobby_id: int, target_key: str, status: str, payout: int, fine: int, caught: bool, occurred_at: str) -> MemoryFact:
        fact, _ = await self.memory.record_consequence(guild_id, user_id, memory_key=f'heist.result:{int(lobby_id)}:{int(user_id)}', category='story', subject_type='character', subject_key='heist', state_key='heist_resolved', value={'lobby_id': int(lobby_id), 'target_key': str(target_key), 'status': str(status), 'payout': int(payout), 'fine': int(fine), 'caught': bool(caught)}, occurred_at=occurred_at)
        return fact
