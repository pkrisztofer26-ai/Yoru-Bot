from __future__ import annotations

"""Test-guild-only Groq renderer for bounded Tier 2 context packets."""

import asyncio
from typing import Any, Mapping

from app.ai_director_context import AIDirectorContextPacket
from app.providers.ai_director_groq import GroqAIDirectorProvider


class GroqAIDirectorContextProvider(GroqAIDirectorProvider):
    @staticmethod
    def system_prompt() -> str:
        return (
            "Te a Yoru Tier 2 Context AI szigorúan presentation-only magyar narrátorrétege vagy. "
            "Csak a HOST_FACTS-ban megadott, már létező tényeket fogalmazhatod át. Nem találhatsz ki új "
            "szereplőt, helyet, eseményt, ajánlatot, tippet vagy következményt. Nem dönthetsz pénzről, "
            "jutalomról, esélyről, siker/bukásról, cooldownról, inventoryról, XP-ről, police/heatről, "
            "settlementről, choice-ról vagy branchről. Ne írj számokat, összegeket, százalékot vagy ígéretet. "
            "Player-facing szövegben ne használj belső technikai szavakat, például canonical, authority, mechanikai, "
            "validator, fallback, provider vagy contract. Kerüld a szóismétlést és a magyartalan szerkezeteket; ugyanazt az igét ne ismételd rövid távolságon belül. Kizárólag természetes magyar title és rövid description mezőt adj vissza."
        )

    @staticmethod
    def user_prompt(packet: AIDirectorContextPacket) -> str:
        facts = "\n".join(f"- {key}: {value}" for key, value in sorted(packet.facts.items()))
        anchors = ", ".join(packet.required_terms) or "nincs"
        return (
            f"CONTEXT_KEY: {packet.context_key}\nDOMAIN: {packet.domain}\nSEMANTIC_SLOT: {packet.semantic_slot}\n"
            f"HOST_FACTS:\n{facts}\nKÖTELEZŐ ANCHOROK: {anchors}\n\n"
            "DETERMINISZTIKUS FALLBACK / jelentési határ:\n"
            f"TITLE: {packet.fallback_title}\nDESCRIPTION: {packet.fallback_description}\n\n"
            "Fogalmazd át tömör, természetes magyar context-szöveggé. A fallback jelentési határán kívül ne adj "
            "hozzá új tényt. Ne adj tanácsot, mechanikai következtetést, jutalmat vagy garantált kimenetelt. "
            "A válaszban ne jelenjen meg belső rendszerzsargon (canonical, authority, mechanikai, validator, fallback, provider, contract). Kerüld az olyan merev formákat is, mint „ügyben áll”, „otthonvárosban helyezkedik el”, az ismétlődő „érkezett … érkezett”, a „Szolgáltatás profilú” és a „szívességet tart nyilván” fordulatokat is."
        )

    def request_body(self, packet: AIDirectorContextPacket) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": self.user_prompt(packet)},
            ],
            "reasoning_effort": self.reasoning_effort,
            "include_reasoning": False,
            "temperature": 0.15,
            "max_completion_tokens": min(self.max_completion_tokens, 260),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "yoru_ai_director_tier2_context_surface",
                    "strict": True,
                    "schema": self.output_schema(),
                },
            },
        }

    async def generate_context(self, packet: AIDirectorContextPacket) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, packet)
