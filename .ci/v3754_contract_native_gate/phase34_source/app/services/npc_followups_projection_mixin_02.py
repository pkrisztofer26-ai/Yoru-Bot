from __future__ import annotations
from .npc_followups_projection_support import *

class NPCFollowupServiceProjectionMixin02:

    async def relationship_summaries(self, guild_id: int, user_id: int) -> list[NPCRelationshipSummary]:
        """Return player-facing semantic relationship summaries without raw scores."""
        await self.memory.age_resolved_relationships(guild_id, user_id, older_than_hours=RESOLVED_RELATIONSHIP_AGE_HOURS)
        snapshot = await self.memory.snapshot(guild_id, user_id, fact_limit=120)
        rows: list[NPCRelationshipSummary] = []
        for relationship in snapshot.relationships:
            if relationship.subject_type != 'npc':
                continue
            npc = npc_config.maybe_npc(relationship.subject_key)
            if npc is None:
                continue
            flags = relationship.flags
            has_signal = relationship.rival_state != 'none' or relationship.trust_band != 'neutral' or int(relationship.favor_owed_to_player) > 0 or (int(relationship.favor_owed_by_player) > 0) or bool(flags.get('contact_unlocked')) or any((bool(flags.get(key)) for key in ('player_helped', 'npc_helped', 'agreement_kept', 'agreement_broken')))
            if not has_signal:
                continue
            if relationship.rival_state == 'rival':
                status = 'Rivális'
                note = 'A konfliktus tartós, és későbbi helyzetekben is visszatérhet.'
            elif relationship.rival_state == 'tension':
                status = 'Feszült'
                note = 'Van köztetek rendezetlen ügy.'
            elif int(relationship.favor_owed_to_player) > 0:
                status = 'Szívességgel tartozik'
                note = 'Van egy beváltható szívességed ennél a kapcsolatnál.'
            elif int(relationship.favor_owed_by_player) > 0:
                status = 'Tartozol neki'
                note = 'A kapcsolatban maradt egy viszonzatlan segítség.'
            elif relationship.trust_band == 'trusted':
                status = 'Megbízható kapcsolat'
                note = 'Több korábbi ügy alapján stabil lett köztetek a kapcsolat.'
            elif relationship.trust_band == 'warm':
                status = 'Jó kapcsolat'
                note = 'A korábbi találkozások összességében jól alakultak.'
            elif relationship.trust_band in {'wary', 'hostile'}:
                status = 'Távolságtartó'
                note = 'A korábbi ügyek miatt óvatosabb lett köztetek a viszony.'
            else:
                status = 'Ismerős'
                note = 'Már van közös előzményetek.'
            rows.append(NPCRelationshipSummary(npc.key, npc.display_name, npc.emoji, npc.role_label, status, note))
        order = {'Rivális': 0, 'Feszült': 1, 'Szívességgel tartozik': 2, 'Tartozol neki': 3, 'Megbízható kapcsolat': 4, 'Jó kapcsolat': 5, 'Távolságtartó': 6, 'Ismerős': 7}
        rows.sort(key=lambda item: (order.get(item.status_label, 99), item.npc_name.casefold()))
        return rows

    async def notify_after_consequence(self, guild_id: int, user_id: int, *, npc_key: str, preset_key: str, memory_key: str, relationship: RelationshipState | None) -> None:
        if self.notifications is None or relationship is None:
            return
        npc = npc_config.npc(npc_key)
        event_token = _fingerprint(memory_key, preset_key)
        try:
            if preset_key == 'player_helped' and int(relationship.favor_owed_to_player) > 0:
                await self.notifications.private_opportunity(guild_id, user_id, opportunity_key=f'npc_favor_{npc.key}', event_key=f'favor_available.{event_token}', title=f'🤝 {npc.display_name} visszaadná a segítséget', body=f'Korábban segítettél neki. {npc.display_name} most felajánlotta, hogy utánanéz neked egy kapcsolódó ügynek. A Lehetőségeim között megtalálod.', expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat(), npc_key=npc.key)
            elif preset_key in {'agreement_broken', 'betrayal', 'rival_escalated'}:
                title = f'⚠️ Feszültebb lett a viszony {npc.display_name} és közted'
                body = 'A korábbi ügyeteknek maradt következménye. A Lehetőségeim között később visszatérhet ez a kapcsolat.'
                await self.notifications.relationship_followup(guild_id, user_id, npc_key=npc.key, event_key=f'conflict.{event_token}', title=title, body=body, important=True)
            elif preset_key == 'rival_resolved':
                await self.notifications.relationship_followup(guild_id, user_id, npc_key=npc.key, event_key=f'resolved.{event_token}', title=f'🤝 Rendeztétek a konfliktust {npc.with_name}', body='A korábbi feszültség lezárult. A következő találkozásotoknál már nem ez a vita lesz köztetek.', important=False)
        except Exception:
            log.exception('NPC relationship notification failed guild=%s user=%s npc=%s preset=%s', guild_id, user_id, npc.key, preset_key)
