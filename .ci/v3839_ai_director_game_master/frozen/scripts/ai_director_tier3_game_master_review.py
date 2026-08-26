from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path

from app.ai_director_game_master import (
    big_job_packet, chapter_packet, consequence_recall_packet, fallback_game_master_surface,
    legendary_event_packet, npc_story_packet, validate_game_master_surface, world_story_packet,
)
from app.providers.ai_director_game_master_groq import GroqAIDirectorGameMasterProvider


def review_packets():
    return [
        big_job_packet(target_name="Belvárosi trezor", phase_label="menekülés", approach_label="csendes", route_label="hátsó útvonal", host_resolution="részsiker", consequence_note="a csapat szétszóródva jutott ki"),
        big_job_packet(target_name="Kikötői raktár", phase_label="lezárás", approach_label="gyors", route_label="ipari útvonal", host_resolution="siker", consequence_note="az akció híre gyorsan terjedt"),
        npc_story_packet(npc_name="Zoli", npc_role="kapcsolattartó", relationship_band="óvatos", recalled_event="korábban betartottad a megállapodást", current_story_state="újra szóba áll veled"),
        npc_story_packet(npc_name="Mira", npc_role="informátor", relationship_band="bizalmatlan", recalled_event="egy régi ügyben cserben hagytad", current_story_state="távolságot tart"),
        consequence_recall_packet(subject_label="a régi üzlettárs", memory_category="agreement", remembered_event="a megállapodást végül teljesítetted", current_relevance="ismét felmerült a közös múlt"),
        consequence_recall_packet(subject_label="a riválisod", memory_category="rival", remembered_event="a konfliktus lezáratlan maradt", current_relevance="ugyanabban a körben mozogtok"),
        chapter_packet(chapter_title="Repedések a városban", stage_title="Utórezgések", world_story_title="Feszült egyensúly", community_note="a közösségi válasz vegyes maradt"),
        chapter_packet(chapter_title="Repedések a városban", stage_title="Lezárás", world_story_title="Feszült egyensúly", community_note="a közösségi döntések nyomot hagytak", host_ending="Törékeny egyensúly"),
        world_story_packet(national_title="Országos bizonytalanság", story_title="Feszült egyensúly", beat_title="Új törésvonal", city_label="Budapest", world_note="a helyi szereplők kivárnak"),
        world_story_packet(national_title="Lassú rendeződés", story_title="Új kapcsolatok", beat_title="Csendes közeledés", city_label="Szeged", world_note="a helyi hangulat óvatosan enyhül"),
        legendary_event_packet(event_name="Fekete Korona", access_context="ritka meghívás után indult", phase_label="végjáték", host_resolution="részsiker", legacy_note="az ügy neve megmaradt a városi történetekben"),
        legendary_event_packet(event_name="Éjféli Konvoj", access_context="különleges opportunity nyitotta meg", phase_label="lezárás", host_resolution="siker", legacy_note="a résztvevők története később is előkerül"),
    ]


async def run(args) -> int:
    packets = review_packets()
    provider = None
    if args.mode == "live":
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GROQ_API_KEY szükséges live reviewhoz.")
        provider = GroqAIDirectorGameMasterProvider(key, model=args.model, reasoning_effort=args.reasoning_effort, timeout=45.0, http_retries=1, max_completion_tokens=280)
    rows = []
    for packet in packets:
        fallback = fallback_game_master_surface(packet)
        source = "fixture"
        raw = {"title": fallback.title, "description": fallback.description}
        raw_title = raw["title"]
        raw_description = raw["description"]
        error = ""
        error_detail = ""
        if provider is not None:
            try:
                raw = dict(await provider.generate_game_master(packet))
                raw_title = str(raw.get("title") or "")
                raw_description = str(raw.get("description") or "")
                source = "ai"
            except Exception as exc:
                raw = {"title": fallback.title, "description": fallback.description}
                raw_title = ""
                raw_description = ""
                source = "fallback"
                error = type(exc).__name__
                error_detail = str(exc)[:240]
        try:
            title, description = validate_game_master_surface(packet, raw)
            validated = True
        except Exception as exc:
            title, description = fallback.title, fallback.description
            source = "fallback"
            validated = False
            error = error or type(exc).__name__
            error_detail = error_detail or str(exc)[:240]
        # The player-facing candidate is the effective surface after fail-closed fallback,
        # so validate that final surface independently from provider acceptance.
        validate_game_master_surface(packet, {"title": title, "description": description})
        effective_validated = True
        rows.append({
            "story_key": packet.story_key, "family": packet.family, "source": source,
            "validated": validated, "effective_validated": effective_validated, "title": title, "description": description, "error": error,
            "raw_title": raw_title, "raw_description": raw_description, "error_detail": error_detail,
            "groundedness": "", "hungarian": "", "yoru_tone": "", "new_fact": "", "decision": "", "notes": "",
        })
        if provider is not None:
            await asyncio.sleep(2.0)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    ai_validated = sum(1 for row in rows if row["source"] == "ai" and row["validated"])
    fallbacks = sum(1 for row in rows if row["source"] == "fallback")
    effective_validated = sum(1 for row in rows if row["effective_validated"])
    status = "PENDING_HUMAN" if effective_validated == len(rows) else "AUTOMATED_HOLD"
    result = {
        "version": "3.83.9", "work_item": "W22.5.1.1", "contract": "tier3-game-master-surface-v3",
        "total": len(rows), "ai_validated": ai_validated, "fallbacks": fallbacks, "effective_validated": effective_validated,
        "status": status, "player_facing_ai": False, "gameplay_authority": "NONE", "live_deploy": False,
        "rows": rows,
    }
    (output / "YORU_AI_DIRECTOR_TIER3_GAME_MASTER_REVIEW_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "YORU_AI_DIRECTOR_TIER3_GAME_MASTER_REVIEW_RESULT.txt").write_text(
        "\n".join([
            "Yoru v3.83.9 W22.5.1.1 Tier 3 Game Master Provider Review",
            f"STATUS={status}", f"TOTAL={len(rows)}", f"AI_VALIDATED={ai_validated}", f"FALLBACKS={fallbacks}",
            f"EFFECTIVE_VALIDATED={effective_validated}",
            "PLAYER_FACING_AI=OFF", "GAMEPLAY_AUTHORITY=NONE", "LIVE_DEPLOY=UNCHANGED",
        ]) + "\n", encoding="utf-8")
    with (output / "YORU_AI_DIRECTOR_TIER3_GAME_MASTER_HUMAN_REVIEW.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print((output / "YORU_AI_DIRECTOR_TIER3_GAME_MASTER_REVIEW_RESULT.txt").read_text(encoding="utf-8"), end="")
    return 0 if effective_validated == len(rows) else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--output", default="tier3_game_master_review")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
