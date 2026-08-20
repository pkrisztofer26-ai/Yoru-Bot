from __future__ import annotations
from .memory_adapters_projection_support import *

class MemoryAdapterServiceProjectionMixin02:

    async def npc_consequence(self, guild_id: int, user_id: int, *, npc_key: str, event_key: str, preset_key: str, value: dict[str, Any] | None=None, occurred_at: str | None=None, source_history_event_id: int | None=None) -> tuple[MemoryFact, RelationshipState | None]:
        npc = npc_config.npc(npc_key)
        preset = NPC_CONSEQUENCE_PRESETS.get(str(preset_key).strip().lower())
        if preset is None:
            raise ValueError(f'Ismeretlen NPC consequence preset: {preset_key}')
        clean_event = str(event_key).strip().lower()
        if not clean_event:
            raise ValueError('Az NPC consequence event_key nem lehet üres.')
        if any((ch not in 'abcdefghijklmnopqrstuvwxyz0123456789_.:-' for ch in clean_event)):
            raise ValueError('Az NPC consequence event_key csak stabil technikai kulcs lehet.')
        if len(clean_event) > 28:
            clean_event = f'{clean_event[:11]}-{_fingerprint(clean_event, length=12)}'
        payload = {'npc_key': npc.key, 'role_key': npc.role_key, 'preset': preset.key}
        if value:
            payload.update(dict(value))
        fact, relationship = await self.memory.record_consequence(guild_id, user_id, memory_key=f'npc.{npc.key}:{clean_event}', category='rival' if preset.rival_state in {'tension', 'rival', 'resolved'} else 'relationship', subject_type='npc', subject_key=npc.key, state_key=preset.state_key, value=payload, trust_delta=preset.trust_delta, favor_to_player_delta=preset.favor_to_player_delta, favor_by_player_delta=preset.favor_by_player_delta, rival_state=preset.rival_state, relationship_flags=dict(preset.flags), source_history_event_id=source_history_event_id, occurred_at=occurred_at)
        if self.followups is not None:
            try:
                await self.followups.notify_after_consequence(guild_id, user_id, npc_key=npc.key, preset_key=preset.key, memory_key=fact.memory_key, relationship=relationship)
            except Exception:
                log.exception('NPC follow-up notification failed guild=%s user=%s npc=%s preset=%s', guild_id, user_id, npc.key, preset.key)
        return (fact, relationship)
