from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.ai_director_game_master import AIDirectorGameMasterPacket
from app.providers.ai_director_groq import GroqAIDirectorProvider


class GroqAIDirectorGameMasterProvider(GroqAIDirectorProvider):
    """Non-player review provider for the W22.5 Tier 3 foundation."""

    @staticmethod
    def system_prompt() -> str:
        return (
            "Te a Yoru Tier 3 AI Game Master presentation-only magyar narrátorrétege vagy. "
            "A HOST_FACTS már eldöntött, host-owned történeti tények. Ezeket kizárólag hangulatos, rövid magyar "
            "narrációvá formálhatod. Nem találhatsz ki új szereplőt, helyet, múltbeli eseményt, branch-et, választást, "
            "jutalomról szóló új tényt, mechanikai következményt vagy jövőbeli ígéretet. Nem dönthetsz success/failről, state-ről, "
            "world truth-ról, relationship state-ről, chapter endingről vagy hozzáférésről. Ne írj számot, összeget, "
            "százalékot, parancsot vagy belső rendszerzsargont. Kizárólag title és description mezőt adj vissza."
        )

    @staticmethod
    def user_prompt(packet: AIDirectorGameMasterPacket) -> str:
        facts = "\n".join(f"- {key}: {value}" for key, value in sorted(packet.facts.items()))
        anchors = ", ".join(packet.required_terms) or "nincs"
        return (
            f"STORY_KEY: {packet.story_key}\nFAMILY: {packet.family}\nSEMANTIC_SLOT: {packet.semantic_slot}\n"
            f"HOST_FACTS:\n{facts}\nKÖTELEZŐ ANCHOROK: {anchors}\n\n"
            "DETERMINISZTIKUS SCENARIO V2 FALLBACK / jelentési határ:\n"
            f"TITLE: {packet.fallback_title}\nDESCRIPTION: {packet.fallback_description}\n\n"
            "Adj természetes, tömör magyar történeti presentationt. A fallback és a HOST_FACTS jelentési határán "
            "kívül semmit ne adj hozzá. Különösen tilos új branch, döntés, reward, siker/bukás, NPC-szándék vagy "
            "jövőbeli esemény feltalálása."
        )

    def request_body(self, packet: AIDirectorGameMasterPacket) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": self.user_prompt(packet)},
            ],
            "reasoning_effort": self.reasoning_effort,
            "include_reasoning": False,
            "temperature": 0.1,
            "max_completion_tokens": min(self.max_completion_tokens, 280),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "yoru_ai_director_tier3_game_master_surface",
                    "strict": True,
                    "schema": self.output_schema(),
                },
            },
        }

    async def generate_game_master(self, packet: AIDirectorGameMasterPacket) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, packet)
