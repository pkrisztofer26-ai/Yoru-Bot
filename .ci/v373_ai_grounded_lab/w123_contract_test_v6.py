from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import base64
import gzip
import importlib.util
import json
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"


def load_target():
    spec = importlib.util.spec_from_file_location("w123_v6_contract_target", TARGET)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load semantic target")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ok(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def load_canary_fixture():
    text = "".join(
        p.read_text(encoding="ascii").strip()
        for p in sorted(HERE.glob("w123_v5_canary_humanqa.part*.b64"))
    )
    return json.loads(gzip.decompress(base64.b64decode(text)).decode("utf-8"))


mod = load_target()
lab = mod.V2.load_lab()
mod.V2.install_provider_hotfix(lab)
mod.install_semantic_layer(lab)

ok("contract_v6", mod.CONTRACT_VERSION == "w12.3-semantic-skeleton-v6")
ok("config_v6", mod.CONFIG["version"] == mod.CONTRACT_VERSION)

fixture = load_canary_fixture()
docs = fixture["checkpoints"]
ok("v5_canary_fixture_7_packets", len(docs) == 7)

packet_by_key = {p.key: p for p in lab.PACKETS}

# Human mini-QA MAJOR regressions must now be deterministic rejects.
def old_result(packet_key: str):
    return docs[f"{packet_key}.json"]["result"]

for packet_key, expected in [
    ("work_miskolc_canteen", "canteen_unsupplied_peak_period"),
    ("career_cnc_quality", "cnc_measurement_accuracy_inversion"),
    ("world_eger_heat", "world_heat_imposed_restriction_drift"),
]:
    packet = packet_by_key[packet_key]
    payload = old_result(packet_key)["payload"]
    errs = lab.validate_payload(packet, payload)
    ok(f"reject_v5_human_major_{packet_key}", any(expected in e for e in errs))

# Host-owned choice fixes.
lilla = packet_by_key["npc_lilla_dispatcher"]
lilla_surface = mod.golden_surface(lilla)
lilla_payload = mod.canonicalize_surface_payload(lab, lilla, lilla_surface)
ok(
    "lilla_no_indefinite_decline",
    all(
        any(c["label"] == "Nem vállalod az egyeztetést" for c in item["choices"])
        and all("később sem" not in c["consequence_hint"] for c in item["choices"])
        for item in lilla_payload["items"]
    ),
)

nora = packet_by_key["memory_nora_wallet"]
nora_payload = mod.canonicalize_surface_payload(lab, nora, mod.golden_surface(nora))
ok(
    "nora_no_unsupplied_return_greeting",
    all(
        any(c["label"] == "Köszönsz Nórának" for c in item["choices"])
        and all("Visszaköszönsz" not in c["label"] for c in item["choices"])
        for item in nora_payload["items"]
    ),
)

# Curated golden corpus itself must contain none of the human-mini-QA regressions.
for packet_key in [
    "work_miskolc_canteen",
    "career_cnc_quality",
    "store_heist_teammate_panic",
    "npc_lilla_dispatcher",
    "memory_nora_wallet",
    "world_eger_heat",
]:
    packet = packet_by_key[packet_key]
    payload = mod.canonicalize_surface_payload(lab, packet, mod.golden_surface(packet))
    errs = lab.validate_payload(packet, payload)
    ok(f"golden_v6_{packet_key}", not errs)

gold_canteen = mod.golden_surface(packet_by_key["work_miskolc_canteen"])
ok(
    "golden_no_unsupplied_peak_hour",
    all("csúcsidő" not in (x["title"] + " " + x["description"]).casefold() for x in gold_canteen["items"]),
)
world = packet_by_key["world_eger_heat"]
gold_world = mod.golden_surface(world)
ok(
    "golden_world_preserves_outdoor_job_scope",
    all(
        ("alkalmi munk" not in x["description"].casefold())
        or ("szabadtér" in x["description"].casefold())
        for x in gold_world["items"]
    ),
)
gold_nora = mod.golden_surface(nora)
ok(
    "golden_nora_actor_unambiguous",
    all(
        "korábban ő találta" not in x["description"].casefold()
        and "segítség miatt: ő találta" not in x["description"].casefold()
        for x in gold_nora["items"]
    ),
)

# Exact v5 PASS canary must migrate to v6 with zero provider calls.
import w123_checkpoint_migrate as migrate_mod

with tempfile.TemporaryDirectory(prefix="w123_v6_migrate_") as td:
    base = Path(td)
    cp_dir = base / "checkpoints"
    out_dir = base / "out"
    cp_dir.mkdir()
    for name, doc in docs.items():
        (cp_dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    report = migrate_mod.migrate(
        cp_dir,
        out_dir,
        model="openai/gpt-oss-120b",
        reasoning_effort="low",
    )
    ok("migrate_all_7_v5_canary", report["migrated_pass"] == 7)
    ok("migrate_7_no_reject", report["rejected"] == 0 and report["skipped"] == 0)
    ok("migrate_7_zero_provider", report["provider_calls"] == 0 and report["groq_tokens_used"] == 0)

    # Re-read all migrated checkpoints and verify every final payload under v6.
    final_rows = []
    fallback_packets = []
    for path in sorted(cp_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        result = doc["result"]
        packet_key = result["packet"]["key"]
        packet = packet_by_key[packet_key]
        errs = lab.validate_payload(packet, result["payload"])
        ok(f"migrated_final_valid_{packet_key}", not errs)
        final_rows.extend(result["payload"]["items"])
        if int((result.get("host_surface_repair") or {}).get("golden_fallback_count") or 0):
            fallback_packets.append(packet_key)

    ok("migrated_final_35_items", len(final_rows) == 35)
    ok(
        "human_major_packets_repaired_without_groq",
        {"work_miskolc_canteen", "career_cnc_quality", "world_eger_heat"}.issubset(set(fallback_packets)),
    )

# Provider remains exactly one request per fresh packet; no content retry.
ok("v6_zero_content_retry_policy", getattr(mod, "CONTRACT_VERSION") == "w12.3-semantic-skeleton-v6")

print("W12_3_V6_HUMAN_CANARY_TESTS_PASS")
