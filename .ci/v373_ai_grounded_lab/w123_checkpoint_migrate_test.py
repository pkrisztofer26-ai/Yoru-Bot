from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import gzip
import importlib.util
import json
import shutil
import sys

HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


target = load(HERE / "semantic_skeleton_v3.py", "w123_migration_test_target")
lab = target.V2.load_lab()
target.V2.install_provider_hotfix(lab)
target.install_semantic_layer(lab)
migrator = load(HERE / "w123_checkpoint_migrate.py", "w123_checkpoint_migrator")

gold = json.loads(gzip.decompress(base64.b64decode(
    (HERE / "w123_shadow_golden.b64").read_text(encoding="ascii")
)).decode("utf-8"))["items"]
grouped = {}
for row in gold:
    grouped.setdefault(row["packet"], []).append(row)
for rows in grouped.values():
    rows.sort(key=lambda r: r["slot"])


def make_payload(packet_key: str, bad_phrase: str | None = None):
    packet = next(p for p in lab.PACKETS if p.key == packet_key)
    rows = grouped[packet_key]
    surface = {"items": [
        {"slot": r["slot"], "title": r["title"], "description": r["description"]}
        for r in rows
    ]}
    if bad_phrase:
        surface["items"][0]["description"] += " " + bad_phrase
    return packet, target.canonicalize_surface_payload(lab, packet, surface)


with TemporaryDirectory() as td:
    root = Path(td)
    cp = root / "checkpoints"
    out = root / "out"
    cp.mkdir()

    safe_packet, safe_payload = make_payload("npc_misi_car_dealer")
    repair_packet, repair_payload = make_payload("work_miskolc_warehouse", "A raklap heveredik egymásra.")

    for packet, payload in [
        (safe_packet, safe_payload),
        (repair_packet, repair_payload),
    ]:
        result = {
            "packet": lab._packet_meta(packet),
            "status": "PASS",
            "attempts": [],
            "key_normalizations": 0,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "rate_limit": {},
            "estimated_cost_usd": 0.0,
            "payload": payload,
        }
        doc = {
            "contract_version": "w12.3-semantic-skeleton-v2",
            "packet_fingerprint": lab.packet_fingerprint(packet),
            "model": "openai/gpt-oss-120b",
            "reasoning_effort": "low",
            "saved_at_unix": 1.0,
            "result": result,
        }
        (cp / f"{packet.key}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Exact real v4 canary FAIL checkpoint. v5 must salvage it without Groq.
    raw = gzip.decompress(base64.b64decode(
        (HERE / "w123_v4_canteen_fail_checkpoint.b64").read_text(encoding="ascii")
    ))
    (cp / "work_miskolc_canteen.json").write_bytes(raw)

    # A fingerprint mismatch must never be repaired/migrated.
    bad_fp_packet, bad_fp_payload = make_payload("npc_jani_mechanic")
    bad_fp_doc = {
        "contract_version": "w12.3-semantic-skeleton-v4",
        "packet_fingerprint": "wrong",
        "model": "openai/gpt-oss-120b",
        "reasoning_effort": "low",
        "saved_at_unix": 1.0,
        "result": {
            "packet": lab._packet_meta(bad_fp_packet),
            "status": "PASS",
            "payload": bad_fp_payload,
            "attempts": [],
        },
    }
    (cp / "npc_jani_mechanic.json").write_text(
        json.dumps(bad_fp_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = migrator.migrate(
        cp, out,
        model="openai/gpt-oss-120b",
        reasoning_effort="low",
    )

    assert report["migrated_pass"] == 2, report
    assert report["salvaged_failed"] == 1, report
    assert report["rejected"] == 1, report
    assert report["provider_calls"] == 0 and report["groq_tokens_used"] == 0

    safe_doc = json.loads((cp / "npc_misi_car_dealer.json").read_text(encoding="utf-8"))
    assert safe_doc["contract_version"] == target.CONTRACT_VERSION
    assert not lab.validate_payload(safe_packet, safe_doc["result"]["payload"])
    assert "host_surface_repair" not in safe_doc["result"]

    repaired_doc = json.loads((cp / "work_miskolc_warehouse.json").read_text(encoding="utf-8"))
    assert repaired_doc["contract_version"] == target.CONTRACT_VERSION
    assert repaired_doc["result"]["host_surface_repair"]["golden_fallback_count"] == 5
    assert not lab.validate_payload(repair_packet, repaired_doc["result"]["payload"])

    canteen_doc = json.loads((cp / "work_miskolc_canteen.json").read_text(encoding="utf-8"))
    assert canteen_doc["contract_version"] == target.CONTRACT_VERSION
    assert canteen_doc["result"]["status"] == "PASS"
    assert canteen_doc["result"]["salvaged_from_failed_checkpoint"] is True
    assert canteen_doc["result"]["host_surface_repair"]["golden_fallback_count"] == 5
    assert not lab.validate_payload(
        next(p for p in lab.PACKETS if p.key == "work_miskolc_canteen"),
        canteen_doc["result"]["payload"],
    )

    rejected_doc = json.loads((cp / "npc_jani_mechanic.json").read_text(encoding="utf-8"))
    assert rejected_doc["contract_version"] == "w12.3-semantic-skeleton-v4"

print(
    "W12_3_CHECKPOINT_MIGRATION_TEST_PASS "
    "migrated_pass=2 salvaged_failed=1 rejected_fingerprint=1 provider_calls=0"
)
