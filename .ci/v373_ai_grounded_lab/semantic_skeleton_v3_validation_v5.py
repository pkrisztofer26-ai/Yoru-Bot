from __future__ import annotations

from semantic_skeleton_v3_rules import *
import itertools
import json
import os
import re
import sys
import time

def regression_report(lab) -> dict[str, Any]:
    packed = base64.b64decode("".join(p.read_text(encoding="ascii") for p in REGRESSION_CHUNKS))
    corpus = json.loads(gzip.decompress(packed).decode("utf-8"))["items"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in corpus:
        grouped.setdefault(str(row["packet"]), []).append(row)
    packet_by_key = {p.key: p for p in lab.PACKETS}
    rows = []
    legacy_pass = 0
    for key in sorted(grouped):
        packet = packet_by_key[key]
        old = sorted(grouped[key], key=lambda x: int(x["index"]))
        surface = {"items": [
            {"slot": SLOT_IDS[i], "title": r["item"]["title"], "description": r["item"]["description"]}
            for i, r in enumerate(old)
        ]}
        canonical = canonicalize_surface_payload(lab, packet, surface)
        errs = lab.validate_payload(packet, canonical)
        passed = not errs
        if passed:
            legacy_pass += 1
        statuses = [r["human_status"] for r in old]
        if "FAIL" in statuses:
            human_packet_class = "BLOCKER"
        elif "MAJOR" in statuses:
            human_packet_class = "REWRITE"
        elif "MINOR" in statuses:
            human_packet_class = "POLISH"
        else:
            human_packet_class = "PASS"
        rows.append({
            "packet": key,
            "human_packet_class": human_packet_class,
            "old_human_statuses": statuses,
            "w123_accepts_old_packet_after_host_repair": passed,
            "error_count": len(errs),
            "sample_errors": errs[:10],
        })
    blocker_rows = [r for r in rows if r["human_packet_class"] == "BLOCKER"]
    blocker_accepted = sum(bool(r["w123_accepts_old_packet_after_host_repair"]) for r in blocker_rows)
    legacy_rejected = len(grouped) - legacy_pass
    acceptance = "PASS" if blocker_accepted == 0 and legacy_rejected >= 20 else "FAIL"
    return {
        "gate": f"{GATE_NAME} — W12.2 regression corpus",
        "source_items": len(corpus),
        "source_packets": len(grouped),
        "source_blocker_packets": len(blocker_rows),
        "legacy_packets_rejected": legacy_rejected,
        "legacy_packets_accepted_after_host_repair": legacy_pass,
        "blocker_packets_rejected": len(blocker_rows) - blocker_accepted,
        "blocker_packets_accepted": blocker_accepted,
        "acceptance": acceptance,
        "production_ai_authorized": False,
        "rows": rows,
    }


def self_test(lab) -> dict[str, Any]:
    assert CONFIG.get("version") == CONTRACT_VERSION
    assert set(CONFIG["packets"]) == {p.key for p in lab.PACKETS}
    assert len(lab.PACKETS) == 24
    assert sum(p.count for p in lab.PACKETS) == 120

    # Surface schema has no authority/choice fields.
    sample = lab.PACKETS[0]
    props = surface_output_schema(sample)["properties"]["items"]["items"]["properties"]
    assert set(props) == {"slot", "title", "description"}

    # Host owns choices and world contexts own zero choices.
    def probe_surface(packet, title="Rövid próbacím", desc="próba"):
        cfg = packet_cfg(packet)
        anchor_text = " ".join(group[0] for group in cfg["anchors"])
        return {"items": [
            {"slot": slot, "title": f"{title} {chr(65+i)}", "description": f"{anchor_text} {desc} {chr(97+i)}."}
            for i, slot in enumerate(SLOT_IDS)
        ]}

    non_world = next(p for p in lab.PACKETS if p.key == "crime_unknown_envelope")
    can = canonicalize_surface_payload(lab, non_world, probe_surface(non_world))
    assert can["items"][0]["choices"] == choice_rows(non_world, 0)
    assert "slot" not in can["items"][0]

    world = next(p for p in lab.PACKETS if p.key == "world_miskolc_roadworks")
    can_world = canonicalize_surface_payload(lab, world, probe_surface(world))
    assert all(x["choices"] == [] for x in can_world["items"])

    # Known W12.2 factual drift must be blocked.
    canteen = next(p for p in lab.PACKETS if p.key == "work_miskolc_canteen")
    bad = probe_surface(canteen, desc="zöldséget talál ki")
    badc = canonicalize_surface_payload(lab, canteen, bad)
    assert any("ingredient_invention" in e for e in semantic_errors(lab, canteen, badc))

    # Meta/numbered title regression.
    bad_title = probe_surface(non_world)
    bad_title["items"][0]["title"] = "Változat egy"
    bad_title_c = canonicalize_surface_payload(lab, non_world, bad_title)
    assert any("numbered_template_title" in e for e in semantic_errors(lab, non_world, bad_title_c))

    regression = regression_report(lab)
    assert regression["source_items"] == 120
    assert regression["source_packets"] == 24
    assert regression["acceptance"] == "PASS", regression
    assert regression["blocker_packets_accepted"] == 0, regression
    assert regression["legacy_packets_rejected"] >= 20, regression
    print(
        "W12_3_SEMANTIC_SKELETON_SELFTEST_PASS "
        f"surface_only host_choices world_no_choice anchors forbidden_regressions "
        f"legacy_rejected={regression['legacy_packets_rejected']}/24 blocker_rejected={regression['blocker_packets_rejected']}/{regression['source_blocker_packets']}",
        flush=True,
    )
    return regression
