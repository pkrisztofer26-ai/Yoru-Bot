from __future__ import annotations

from pathlib import Path
import argparse
import importlib.util
import sys

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"
spec = importlib.util.spec_from_file_location("w123_v4_extra_target", TARGET)
if not spec or not spec.loader:
    raise SystemExit("cannot import semantic_skeleton_v3.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
lab = mod.V2.load_lab()
mod.V2.install_provider_hotfix(lab)
mod.install_semantic_layer(lab)

checks = []
def ok(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    checks.append(name)
    print(f"PASS {name}")

# v4: a 4-anchor packet may contain a focused 2-anchor item when packet-level
# 3/5 coverage preserves every canonical anchor.
canteen = next(p for p in lab.PACKETS if p.key == "work_miskolc_canteen")
all4 = "alapanyag késik sor előkészítés"
surface = {"items": [
    {"slot": mod.SLOT_IDS[0], "title": "Menza fókusz A", "description": f"{all4} marad a rövid jelenet fókusza."},
    {"slot": mod.SLOT_IDS[1], "title": "Menza fókusz B", "description": "A növekvő sor mellett a kiszolgálás szervezése kerül előtérbe."},
    {"slot": mod.SLOT_IDS[2], "title": "Menza fókusz C", "description": f"{all4} mellett a kisegítő a saját feladatánál marad."},
    {"slot": mod.SLOT_IDS[3], "title": "Menza fókusz D", "description": f"{all4} együtt adja a jelenet keretét."},
    {"slot": mod.SLOT_IDS[4], "title": "Menza fókusz E", "description": f"{all4} marad a helyzet teljes kerete."},
]}
errs = lab.validate_payload(canteen, mod.canonicalize_surface_payload(lab, canteen, surface))
ok("allow_four_anchor_two_focus_when_packet_covered", not errs)

# v4: 5-anchor world packets remain stricter: 2/5 is still rejected.
world = next(p for p in lab.PACKETS if p.key == "world_eger_heat")
anchors = mod.packet_cfg(world)["anchors"]
full = " ".join(g[0] for g in anchors)
surface = {"items": [
    {"slot": mod.SLOT_IDS[0], "title": "Egri fókusz A", "description": "Eger és a hőség röviden jelenik meg a leírásban."},
    {"slot": mod.SLOT_IDS[1], "title": "Egri fókusz B", "description": f"{full} marad a világállapot leírása."},
    {"slot": mod.SLOT_IDS[2], "title": "Egri fókusz C", "description": f"{full} marad a világállapot kerete."},
    {"slot": mod.SLOT_IDS[3], "title": "Egri fókusz D", "description": f"{full} együtt jelenik meg."},
    {"slot": mod.SLOT_IDS[4], "title": "Egri fókusz E", "description": f"{full} adja a rövid hírszerű leírást."},
]}
errs = lab.validate_payload(world, mod.canonicalize_surface_payload(lab, world, surface))
ok("world_five_anchor_minimum_three", any("minimum=3" in e for e in errs))

# v4: failed provider surfaces survive as diagnostic evidence without becoming
# authoritative scenario payload.
lab2 = mod.V2.load_lab(); mod.V2.install_provider_hotfix(lab2)
bad_packet = next(p for p in lab2.PACKETS if p.key == "work_miskolc_canteen")
def fake_request(**kwargs):
    return (
        {"items": [
            {"slot": slot, "title": f"Nyers próba {chr(65+i)}", "description": f"alapanyag késik sor előkészítés zöldséget talál ki {chr(97+i)}."}
            for i, slot in enumerate(mod.SLOT_IDS)
        ]},
        {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        1.0, 1, {"remaining_tokens": 7000, "limit_tokens": 8000, "reset_tokens_seconds": 1.0},
    )
lab2.request_groq = fake_request
mod.install_semantic_layer(lab2)
args = argparse.Namespace(endpoint="fake", model="openai/gpt-oss-120b", reasoning_effort="low", timeout=1.0,
    max_completion_tokens=100, http_retries=0, content_retries=0,
    input_usd_per_million=0.15, output_usd_per_million=0.60)
failed = lab2.run_packet(args, bad_packet, "fake-key", [])
ok("failed_surface_evidence_preserved", failed.get("status") == "FAIL" and len(failed.get("provider_surfaces") or []) == 1)

# v4 canary gets one content retry before fail-fast.
canary_source = (HERE / "w123_canary.py").read_text(encoding="utf-8")
ok("canary_one_content_retry", 'p.add_argument("--content-retries", type=int, default=1)' in canary_source)

print(f"W12_3_V4_EXTRA_CONTRACT_TESTS_PASS {len(checks)}/{len(checks)}")
