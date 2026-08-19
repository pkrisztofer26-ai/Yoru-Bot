from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from typing import Any
import argparse
import base64
import gzip
import importlib.util
import json
import sys

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"
GOLDEN_PATH = HERE / "w123_shadow_golden.json"
GOLDEN_PACKED_PATH = HERE / "w123_shadow_golden.b64"


def _load_target():
    spec = importlib.util.spec_from_file_location("w123_shadow_target", TARGET)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {TARGET}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    lab = mod.V2.load_lab()
    mod.V2.install_provider_hotfix(lab)
    mod.install_semantic_layer(lab)
    return mod, lab


def _golden_payload() -> dict[str, Any]:
    if GOLDEN_PACKED_PATH.is_file():
        packed = base64.b64decode(GOLDEN_PACKED_PATH.read_text(encoding="ascii"))
        return json.loads(gzip.decompress(packed).decode("utf-8"))
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _group_goldens() -> dict[str, list[dict[str, Any]]]:
    payload = _golden_payload()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in payload["items"]:
        grouped.setdefault(str(row["packet"]), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: str(r["slot"]))
    return grouped


def _golden_surface(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": [
        {"slot": r["slot"], "title": r["title"], "description": r["description"]}
        for r in rows
    ]}


def _canonical(mod, lab, packet, rows):
    return mod.canonicalize_surface_payload(lab, packet, _golden_surface(rows))


def _cross_entity(lab, packet) -> str:
    for candidate in ("Nóra", "Jani", "Lilla", "Kata", "Misi", "Réka", "Bálint", "Miskolc", "Eger"):
        if candidate not in packet.entities and candidate in lab.GLOBAL_KNOWN_ENTITIES:
            return candidate
    # Should never happen for the current matrix.
    return "Nóra"


PACKET_BAD_PHRASES = {
    "work_miskolc_warehouse": "A raklap visszakerül a megfelelő helyére.",
    "work_eger_event_cleanup": "A játékos irányítja a csapatot.",
    "work_mezokovesd_archive": "A mappákat a hibás címke alapján találgatva rendezi.",
    "work_miskolc_canteen": "A késő alapanyag helyett zöldséget választanak.",
    "career_cnc_quality": "A CNC eltérés után a játékos módosítja a szerszámbeállítást.",
    "career_dispatch_road_closure": "Az útlezárás miatt alternatív útvonalat talál ki.",
    "career_retail_training": "Az új kolléga csúcsidőben fegyelmi ügyet kap.",
    "career_mechanic_part_delay": "Réka számára pontos érkezési időt kér a szállítótól.",
    "crime_unknown_envelope": "Az ismerős azt kéri, hogy vedd át helyette a borítékot.",
    "crime_stolen_phone_offer": "A telefon szinte ingyen van, ezért jó üzletnek tűnik.",
    "crime_hold_unknown_bag": "A barátod csalódott lesz, ha nemet mondasz a táskára.",
    "crime_illegal_race_invite": "A titkos verseny útvonaláról is beszélnek.",
    "store_heist_alarm_change": "A csapat a kamera megkerülését tervezi.",
    "store_heist_teammate_panic": "A pánikoló csapattárs légzőgyakorlatot kezd.",
    "bank_heist_plan_mismatch": "A bevetés középső szakaszában a terep megváltozik.",
    "bank_heist_unexpected_crowd": "A bank belső tere zsúfolt a tömegtől.",
    "npc_lilla_dispatcher": "Lilla konkrét fuvart ajánl pontos időponttal.",
    "npc_jani_mechanic": "Jani megmondja, melyik alkatrész hibás és mennyibe kerül.",
    "npc_kata_job_agent": "Kata konkrét állást és fizetést ajánl.",
    "npc_misi_car_dealer": "Misi konkrét autót és árat ajánl a játékosnak.",
    "memory_nora_wallet": "Nóra egy ajándékkal köszöni meg a régi segítséget.",
    "memory_jani_tools": "Jani megemlíti a közös autójavítást és a tartozását.",
    "world_miskolc_roadworks": "A baleset miatt új útvonalat kell választani Miskolcon.",
    "world_eger_heat": "Egerben a tömegközlekedés is ritkábban jár a hőség miatt.",
}


def _surface_mutation(rows, kind: str, packet, lab):
    surf = _golden_surface(rows)
    if kind == "meta_title":
        surf["items"][0]["title"] = "Változat egy"
    elif kind == "duplicate_title":
        surf["items"][1]["title"] = surf["items"][0]["title"]
    elif kind == "near_duplicate_description":
        surf["items"][1]["description"] = surf["items"][0]["description"]
    elif kind == "weak_anchor":
        surf["items"][0]["description"] = "A jelenet rövid marad, és nem tesz hozzá semmilyen új konkrét részletet."
    elif kind == "cross_entity":
        surf["items"][0]["description"] += f" {_cross_entity(lab, packet)} is ott van."
    elif kind == "packet_semantic_drift":
        surf["items"][0]["description"] += " " + PACKET_BAD_PHRASES[packet.key]
    else:
        raise KeyError(kind)
    return surf


def _payload_mutation(payload: dict[str, Any], kind: str, packet):
    out = deepcopy(payload)
    if kind == "choice_agency_tamper":
        if packet.profile == "world":
            out["items"][0]["choices"] = [{"key": "choice_01", "label": "Kerülőt választasz", "consequence_hint": "Új útvonalat keresel."}]
        else:
            out["items"][0]["choices"] = []
    elif kind == "key_tamper":
        out["items"][0]["key"] = "provider_owned_bad_key"
    elif kind == "semantic_key_tamper":
        out["items"][0]["semantic_key"] = "provider_owned_semantics"
    elif kind == "tags_tamper":
        out["items"][0]["tags"] = ["ai_generated"]
    else:
        raise KeyError(kind)
    return out


def run_shadow(out: Path) -> dict[str, Any]:
    mod, lab = _load_target()
    packet_by_key = {p.key: p for p in lab.PACKETS}
    # Validate the CURRENT curated source-of-truth. Newer contract overlays may
    # patch a small number of golden rows without rewriting the historical
    # packed corpus; the Shadow Lab must see the same surface as runtime.
    grouped = {p.key: list(mod.golden_surface(p)["items"]) for p in lab.PACKETS}

    golden_rows = []
    adversarial_rows = []
    golden_pass_items = 0
    golden_pass_packets = 0

    surface_kinds = (
        "meta_title",
        "duplicate_title",
        "near_duplicate_description",
        "weak_anchor",
        "cross_entity",
        "packet_semantic_drift",
    )
    payload_kinds = (
        "choice_agency_tamper",
        "key_tamper",
        "semantic_key_tamper",
        "tags_tamper",
    )

    for packet in lab.PACKETS:
        rows = grouped[packet.key]
        canonical = _canonical(mod, lab, packet, rows)
        errs = lab.validate_payload(packet, canonical)
        packet_pass = not errs
        if packet_pass:
            golden_pass_packets += 1
            golden_pass_items += len(canonical.get("items", []))
        golden_rows.append({
            "packet": packet.key,
            "status": "PASS" if packet_pass else "FAIL",
            "error_count": len(errs),
            "errors": errs,
        })

        for kind in surface_kinds:
            mutated_surface = _surface_mutation(rows, kind, packet, lab)
            try:
                mutated = mod.canonicalize_surface_payload(lab, packet, mutated_surface)
                a_errs = lab.validate_payload(packet, mutated)
            except Exception as exc:
                a_errs = [f"canonicalization:{type(exc).__name__}:{exc}"]
            adversarial_rows.append({
                "packet": packet.key,
                "case": kind,
                "rejected": bool(a_errs),
                "error_count": len(a_errs),
                "sample_errors": a_errs[:8],
            })

        for kind in payload_kinds:
            mutated = _payload_mutation(canonical, kind, packet)
            a_errs = lab.validate_payload(packet, mutated)
            adversarial_rows.append({
                "packet": packet.key,
                "case": kind,
                "rejected": bool(a_errs),
                "error_count": len(a_errs),
                "sample_errors": a_errs[:8],
            })

    historical = mod.regression_report(lab)
    rejected = sum(1 for row in adversarial_rows if row["rejected"])
    total_adv = len(adversarial_rows)
    failed_adv = [row for row in adversarial_rows if not row["rejected"]]

    acceptance = (
        golden_pass_packets == 24
        and golden_pass_items == 120
        and rejected == total_adv
        and historical["blocker_packets_accepted"] == 0
        and historical["legacy_packets_rejected"] >= 20
    )

    report = {
        "gate": "Yoru v3.73 W12.3 Shadow Lab",
        "contract_version": mod.CONTRACT_VERSION,
        "status": "PASS" if acceptance else "FAIL",
        "provider_calls": 0,
        "groq_tokens_used": 0,
        "production_ai_authorized": False,
        "golden": {
            "scenarios": 120,
            "packets": 24,
            "passed_scenarios": golden_pass_items,
            "passed_packets": golden_pass_packets,
            "rows": golden_rows,
        },
        "adversarial": {
            "cases": total_adv,
            "rejected": rejected,
            "accepted_unexpectedly": len(failed_adv),
            "failed_rows": failed_adv,
            "rows": adversarial_rows,
        },
        "historical_w122": historical,
        "evidence_units": 120 + total_adv + int(historical["source_items"]),
    }

    out.mkdir(parents=True, exist_ok=True)
    (out / "W12_3_SHADOW_LAB_RESULT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "W12_3_SHADOW_LAB_RESULT.txt").write_text(
        "\n".join([
            report["gate"],
            f"STATUS: {report['status']}",
            f"contract_version={report['contract_version']}",
            f"golden={golden_pass_items}/120 scenarios; packets={golden_pass_packets}/24",
            f"adversarial_rejected={rejected}/{total_adv}",
            f"historical_legacy_rejected={historical['legacy_packets_rejected']}/24",
            f"historical_blockers_rejected={historical['blocker_packets_rejected']}/{historical['source_blocker_packets']}",
            f"evidence_units={report['evidence_units']}",
            "provider_calls=0",
            "groq_tokens_used=0",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="artifacts/w123_shadow_lab")
    args = parser.parse_args()
    report = run_shadow(Path(args.out_dir))
    print((Path(args.out_dir) / "W12_3_SHADOW_LAB_RESULT.txt").read_text(encoding="utf-8"), end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
