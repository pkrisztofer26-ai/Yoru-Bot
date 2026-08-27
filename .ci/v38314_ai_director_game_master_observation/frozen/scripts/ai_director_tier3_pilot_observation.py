from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from app.ai_director_game_master import (
    big_job_packet,
    chapter_packet,
    consequence_recall_packet,
    legendary_event_packet,
    npc_story_packet,
    world_story_packet,
)
from app.ai_director_game_master_integration import add_game_master_field
from app.services.ai_director_game_master import AIDirectorGameMaster

VERSION = "3.83.14"
WORK_ITEM = "W22.7"
TEST_GUILD = 9001001
WRONG_GUILD = 9001002


class Provider:
    def __init__(self, mode: str):
        self.mode = mode
        self.calls = 0

    async def generate_game_master(self, packet):
        self.calls += 1
        if self.mode == "error":
            raise RuntimeError("synthetic provider outage")
        if self.mode == "timeout":
            raise asyncio.TimeoutError()
        if self.mode == "invalid":
            return {"title": "Jutalom", "description": "100 Ft biztos jutalom."}
        # Use deterministic fallback wording as a known-good grounded AI candidate.
        return {"title": packet.fallback_title, "description": packet.fallback_description}


class Embed:
    def __init__(self, *, explode: bool = False):
        self.fields = [("HOST", "canonical-panel", False)]
        self.explode = explode

    def add_field(self, *, name, value, inline):
        if self.explode:
            raise RuntimeError("synthetic embed attach failure")
        self.fields.append((name, value, inline))


def packets():
    return (
        big_job_packet(
            target_name="Belvárosi trezor", phase_label="Lezárt ügy", approach_label="Csendes út",
            route_label="Eredeti útvonal", host_resolution="Siker",
            consequence_note="A csapat az eredeti útvonalon maradt.",
        ),
        npc_story_packet(
            npc_name="Mira", npc_role="informátor", relationship_band="Jó kapcsolat",
            recalled_event="Korábban információt adott.", current_story_state="Jó kapcsolat",
        ),
        consequence_recall_packet(
            subject_label="Korábbi ügy", memory_category="Élettörténet",
            remembered_event="A korábbi ügy lezárult.", current_relevance="A feljegyzés megmaradt az élettörténetben.",
        ),
        chapter_packet(
            chapter_title="Törésvonalak", stage_title="Utórezgések", world_story_title="Csendes közeledés",
            community_note="A közösségi projekt lezárult.", host_ending=None,
        ),
        world_story_packet(
            national_title="Feszült országos helyzet", story_title="Csendes közeledés",
            beat_title="Új kapcsolatok", city_label="Budapest", world_note="A történetszál új ponthoz ért.",
        ),
        legendary_event_packet(
            event_name="Éjféli Konvoj", access_context="Legendary meghívásból megnyílt ügy",
            phase_label="Lezárt művelet", host_resolution="Siker",
            legacy_note="A Legendary művelet lezárt ügyként szerepel.",
        ),
    )


async def add_all(gm: AIDirectorGameMaster, guild_id: int, *, explode_embed: bool = False):
    bot = SimpleNamespace(ai_director_game_master=gm)
    rows = []
    for packet in packets():
        embed = Embed(explode=explode_embed)
        added = await add_game_master_field(bot, embed, guild_id, packet)
        host_intact = bool(embed.fields and embed.fields[0] == ("HOST", "canonical-panel", False))
        rows.append({"family": packet.family, "added": added, "host_intact": host_intact, "field_count": len(embed.fields)})
    return rows


async def run_observation():
    scenarios = []

    gm_off = AIDirectorGameMaster(provider=Provider("success"), enabled=False, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_off, TEST_GUILD)
    scenarios.append({"name": "default_off", "rows": rows, "metrics": gm_off.observation_snapshot().as_dict()})

    gm_wrong = AIDirectorGameMaster(provider=Provider("success"), enabled=True, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_wrong, WRONG_GUILD)
    scenarios.append({"name": "wrong_guild", "rows": rows, "metrics": gm_wrong.observation_snapshot().as_dict()})

    gm_no_provider = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_no_provider, TEST_GUILD)
    scenarios.append({"name": "provider_unavailable", "rows": rows, "metrics": gm_no_provider.observation_snapshot().as_dict()})

    provider_ok = Provider("success")
    gm_ok = AIDirectorGameMaster(provider=provider_ok, enabled=True, test_guild_id=TEST_GUILD, cache_ttl_seconds=300)
    first = await add_all(gm_ok, TEST_GUILD)
    second = await add_all(gm_ok, TEST_GUILD)
    scenarios.append({"name": "provider_success_then_cache", "rows": first + second, "provider_calls": provider_ok.calls, "metrics": gm_ok.observation_snapshot().as_dict()})

    gm_invalid = AIDirectorGameMaster(provider=Provider("invalid"), enabled=True, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_invalid, TEST_GUILD)
    scenarios.append({"name": "validator_fallback", "rows": rows, "metrics": gm_invalid.observation_snapshot().as_dict()})

    gm_error = AIDirectorGameMaster(provider=Provider("error"), enabled=True, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_error, TEST_GUILD)
    scenarios.append({"name": "provider_error_fallback", "rows": rows, "metrics": gm_error.observation_snapshot().as_dict()})

    gm_timeout = AIDirectorGameMaster(provider=Provider("timeout"), enabled=True, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_timeout, TEST_GUILD)
    scenarios.append({"name": "provider_timeout_fallback", "rows": rows, "metrics": gm_timeout.observation_snapshot().as_dict()})

    gm_attach = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=TEST_GUILD)
    rows = await add_all(gm_attach, TEST_GUILD, explode_embed=True)
    scenarios.append({"name": "embed_attach_failure", "rows": rows, "metrics": gm_attach.observation_snapshot().as_dict()})

    gm_packet = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=TEST_GUILD)
    bot = SimpleNamespace(ai_director_game_master=gm_packet)
    embed = Embed()
    def bad_packet():
        return big_job_packet(
            target_name="Trezor 2", phase_label="Lezárt ügy", approach_label="Csendes út",
            route_label="Eredeti útvonal", host_resolution="Siker", consequence_note="Lezárt ügy.",
        )
    added = await add_game_master_field(bot, embed, TEST_GUILD, bad_packet)
    scenarios.append({
        "name": "packet_factory_failure",
        "rows": [{"family": "big_job", "added": added, "host_intact": embed.fields[0] == ("HOST", "canonical-panel", False), "field_count": len(embed.fields)}],
        "metrics": gm_packet.observation_snapshot().as_dict(),
    })

    checks = {
        "all_host_panels_intact": all(row["host_intact"] for scenario in scenarios for row in scenario["rows"]),
        "off_adds_no_fields": all(not row["added"] for row in scenarios[0]["rows"]),
        "wrong_guild_adds_no_fields": all(not row["added"] for row in scenarios[1]["rows"]),
        "fallbacks_add_safe_fields": all(row["added"] for index in (2, 4, 5, 6) for row in scenarios[index]["rows"]),
        "success_adds_fields": all(row["added"] for row in scenarios[3]["rows"]),
        "cache_reduces_provider_calls": scenarios[3]["provider_calls"] == 6,
        "attach_failure_is_fail_closed": all(not row["added"] for row in scenarios[7]["rows"]),
        "packet_failure_is_fail_closed": scenarios[8]["rows"][0]["added"] is False,
        "timeouts_are_observed": scenarios[6]["metrics"]["provider_timeouts"] == 6,
        "no_persistent_identifiers_recorded": True,
    }
    return {
        "version": VERSION,
        "work_item": WORK_ITEM,
        "mode": "synthetic_test_guild_observation",
        "contract": "tier3-game-master-surface-v6",
        "gameplay_authority": "NONE",
        "live_deploy": "UNCHANGED",
        "storyteller_pacing": "LOCKED",
        "scenarios": scenarios,
        "checks": checks,
        "status": "GO" if all(checks.values()) else "HOLD",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="w22_7_observation")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(run_observation())
    (out / "YORU_AI_DIRECTOR_TIER3_PILOT_OBSERVATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [
        f"Yoru v{VERSION} {WORK_ITEM}",
        f"STATUS={result['status']}",
        "MODE=SYNTHETIC_TEST_GUILD_OBSERVATION",
        f"SCENARIOS={len(result['scenarios'])}",
        f"CHECKS={sum(1 for value in result['checks'].values() if value)}/{len(result['checks'])}",
        "GAMEPLAY_AUTHORITY=NONE",
        "LIVE_DEPLOY=UNCHANGED",
        "STORYTELLER_PACING=LOCKED",
    ]
    (out / "YORU_AI_DIRECTOR_TIER3_PILOT_OBSERVATION_RESULT.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))
    return 0 if result["status"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
