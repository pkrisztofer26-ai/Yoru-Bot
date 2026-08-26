from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Iterable

from app.ai_director_context import (
    AIDirectorContextPacket,
    AIDirectorContextSurface,
    business_context_packet,
    career_context_packet,
    case_context_packet,
    fallback_context_surface,
    housing_context_packet,
    npc_context_packet,
    tips_context_packet,
    travel_context_packet,
    validate_context_surface,
)
from app.providers.ai_director_context_groq import GroqAIDirectorContextProvider


REVIEW_PACKETS: tuple[AIDirectorContextPacket, ...] = (
    career_context_packet(career_name="Raktáros", employer="Modine", city="Miskolc", position="Tapasztalt munkatárs"),
    career_context_packet(career_name="Futár", employer="Yoru Express", city="Budapest", position="Új belépő"),
    business_context_packet(business_name="Duna Logisztika", category="Logisztika", city="Budapest", operating_model="Kiegyensúlyozott működés"),
    business_context_packet(business_name="Borsod Műhely", category="Szolgáltatás", city="Miskolc", operating_model="Stabil működés"),
    travel_context_packet(current_city="Eger", destination_city="Miskolc", travel_mode="Vonat"),
    travel_context_packet(current_city="Budapest"),
    housing_context_packet(home_city="Debrecen", housing_tier="Saját lakás", location_state="otthonvárosban"),
    housing_context_packet(home_city="Szeged", housing_tier="Albérlet", location_state="másik városban tartózkodsz"),
    npc_context_packet(npc_name="Kata", npc_role="Munkaközvetítő", relationship_state="beváltásra váró szívesség"),
    npc_context_packet(npc_name="Réka", npc_role="Ingatlanos", relationship_state="tisztázatlan kapcsolati ügy"),
    tips_context_packet(topic="Alvilági nyom", source_label="korábbi alvilági ügy", certainty="bizonytalan jelzés"),
    tips_context_packet(topic="Eltűnt szállítmány", source_label="üzleti kapcsolat", certainty="ellenőrizetlen jelzés"),
    case_context_packet(case_type="bűnügyi", case_status="nyitott", subject="Alvilági nyom"),
    case_context_packet(case_type="vállalkozási", case_status="lezárt", subject="Eltűnt szállítmány"),
)


def _fixture_raw(packet: AIDirectorContextPacket) -> dict[str, str]:
    fallback = fallback_context_surface(packet)
    return {"title": fallback.title, "description": fallback.description}


async def generate(mode: str, *, model: str, reasoning_effort: str) -> tuple[list[dict], int]:
    provider = None
    if mode == "live":
        provider = GroqAIDirectorContextProvider(
            os.environ.get("GROQ_API_KEY", ""), model=model, reasoning_effort=reasoning_effort,
            timeout=20.0, http_retries=1, max_completion_tokens=220,
        )
    rows: list[dict] = []
    fallbacks = 0
    for packet in REVIEW_PACKETS:
        try:
            raw = _fixture_raw(packet) if provider is None else await provider.generate_context(packet)
            title, description = validate_context_surface(packet, raw)
            surface = AIDirectorContextSurface(
                context_key=packet.context_key, domain=packet.domain, title=title, description=description,
                source="ai_context_review" if provider is not None else "fixture_context_review",
                packet_digest=packet.digest(), contract_version=packet.contract_version,
            )
            status = "PASS"
            error_detail = ""
        except Exception as exc:
            surface = fallback_context_surface(packet)
            fallbacks += 1
            status = f"FALLBACK:{type(exc).__name__}"
            error_detail = str(exc).replace(os.environ.get("GROQ_API_KEY", ""), "[redacted]")[:600]
        rows.append({
            "context_key": packet.context_key,
            "domain": packet.domain,
            "facts": dict(packet.facts),
            "fallback_title": packet.fallback_title,
            "fallback_description": packet.fallback_description,
            "candidate_title": surface.title,
            "candidate_description": surface.description,
            "candidate_source": surface.source,
            "automated_status": status,
            "error_detail": error_detail,
            "packet_digest": packet.digest(),
            "human_groundedness": "",
            "human_hungarian": "",
            "human_new_fact": "",
            "human_decision": "",
            "human_notes": "",
        })
        if provider is not None:
            await asyncio.sleep(2.0)
    return rows, fallbacks


def duplicate_groups(rows: Iterable[dict]) -> int:
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        if not str(row["candidate_source"]).startswith("ai_context_review"):
            continue
        key = (str(row["candidate_title"]).casefold().strip(), str(row["candidate_description"]).casefold().strip())
        seen[key] = seen.get(key, 0) + 1
    return sum(1 for count in seen.values() if count > 1)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows, fallbacks = await generate(args.mode, model=args.model, reasoning_effort=args.reasoning_effort)
    dupes = duplicate_groups(rows)
    validated = len(rows) - fallbacks
    status = "PENDING_HUMAN" if validated == len(rows) and dupes == 0 else "AUTOMATED_HOLD"
    payload = {
        "version": "3.83.6",
        "work_item": "W22.4.2",
        "contract": REVIEW_PACKETS[0].contract_version,
        "mode": args.mode,
        "status": status,
        "total": len(rows),
        "ai_validated": validated,
        "fallbacks": fallbacks,
        "duplicate_groups": dupes,
        "player_facing_scope": "TEST_GUILD_ONLY_DEFAULT_OFF",
        "gameplay_authority": "NONE",
        "human_review_required": True,
        "rows": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = "\n".join((
        "Yoru v3.83.6 W22.4.2 Tier 2 Context Review",
        f"MODE={args.mode}",
        f"STATUS={status}",
        f"TOTAL={len(rows)}",
        f"AI_VALIDATED={validated}",
        f"FALLBACKS={fallbacks}",
        f"DUPLICATE_GROUPS={dupes}",
        "PLAYER_FACING_SCOPE=TEST_GUILD_ONLY_DEFAULT_OFF",
        "GAMEPLAY_AUTHORITY=NONE",
        "HUMAN_REVIEW_REQUIRED=TRUE",
        "",
    ))
    (args.output / "YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt").write_text(result, encoding="utf-8")
    print(result, end="")
    return 0 if status == "PENDING_HUMAN" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
