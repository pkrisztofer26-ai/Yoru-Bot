from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import importlib.util
import json
import sys
import time

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"


def _load_target():
    spec = importlib.util.spec_from_file_location("w123_checkpoint_migrate_target", TARGET)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {TARGET}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    lab = mod.V2.load_lab()
    mod.V2.install_provider_hotfix(lab)
    mod.install_semantic_layer(lab)
    return mod, lab


def _surface_from_result(mod, result: dict[str, Any]) -> dict[str, Any] | None:
    payload = result.get("payload") if isinstance(result, dict) else None
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) != len(mod.SLOT_IDS):
        return None
    rows = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return None
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title or not description:
            return None
        rows.append({"slot": mod.SLOT_IDS[i], "title": title, "description": description})
    return {"items": rows}


def migrate(checkpoint_dir: Path, out_dir: Path, *, model: str | None, reasoning_effort: str | None) -> dict[str, Any]:
    mod, lab = _load_target()
    packet_by_key = {p.key: p for p in lab.PACKETS}
    rows = []
    migrated = 0
    already_current = 0
    rejected = 0
    skipped = 0

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(checkpoint_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append({"file": path.name, "action": "skip_invalid_json", "error": f"{type(exc).__name__}:{exc}"})
            skipped += 1
            continue

        result = doc.get("result") if isinstance(doc, dict) else None
        packet_key = str(((result or {}).get("packet") or {}).get("key") or path.stem)
        packet = packet_by_key.get(packet_key)
        if packet is None:
            rows.append({"file": path.name, "packet": packet_key, "action": "skip_unknown_packet"})
            skipped += 1
            continue
        if not isinstance(result, dict) or result.get("status") != "PASS":
            rows.append({"file": path.name, "packet": packet_key, "action": "skip_non_pass", "source_status": (result or {}).get("status") if isinstance(result, dict) else None})
            skipped += 1
            continue
        if model and doc.get("model") != model:
            rows.append({"file": path.name, "packet": packet_key, "action": "skip_model_mismatch", "source_model": doc.get("model")})
            skipped += 1
            continue
        if reasoning_effort and doc.get("reasoning_effort") != reasoning_effort:
            rows.append({"file": path.name, "packet": packet_key, "action": "skip_reasoning_mismatch", "source_reasoning": doc.get("reasoning_effort")})
            skipped += 1
            continue
        if doc.get("packet_fingerprint") != lab.packet_fingerprint(packet):
            rows.append({"file": path.name, "packet": packet_key, "action": "reject_packet_fingerprint_mismatch"})
            rejected += 1
            continue

        source_version = str(doc.get("contract_version") or "")
        if source_version == mod.CONTRACT_VERSION:
            payload = result.get("payload")
            errs = lab.validate_payload(packet, payload) if isinstance(payload, dict) else ["missing payload"]
            if errs:
                rows.append({"file": path.name, "packet": packet_key, "action": "reject_current_invalid", "errors": errs[:12]})
                rejected += 1
            else:
                rows.append({"file": path.name, "packet": packet_key, "action": "already_current_pass"})
                already_current += 1
            continue

        surface = _surface_from_result(mod, result)
        if surface is None:
            rows.append({"file": path.name, "packet": packet_key, "action": "reject_no_reconstructable_surface", "source_version": source_version})
            rejected += 1
            continue

        try:
            current_payload = mod.canonicalize_surface_payload(lab, packet, surface)
            errors = lab.validate_payload(packet, current_payload)
        except Exception as exc:
            errors = [f"canonicalization:{type(exc).__name__}:{exc}"]
            current_payload = None

        if errors:
            rows.append({
                "file": path.name,
                "packet": packet_key,
                "action": "reject_old_checkpoint_under_current_contract",
                "source_version": source_version,
                "target_version": mod.CONTRACT_VERSION,
                "errors": errors[:12],
            })
            rejected += 1
            continue

        migrated_result = dict(result)
        migrated_result["payload"] = current_payload
        migrated_result["checkpoint_migration"] = {
            "source_contract_version": source_version,
            "target_contract_version": mod.CONTRACT_VERSION,
            "provider_reused": False,
            "provider_calls_for_migration": 0,
            "revalidated_at_unix": round(time.time(), 3),
        }
        new_doc = {
            "contract_version": mod.CONTRACT_VERSION,
            "packet_fingerprint": lab.packet_fingerprint(packet),
            "model": doc.get("model"),
            "reasoning_effort": doc.get("reasoning_effort"),
            "saved_at_unix": round(time.time(), 3),
            "result": migrated_result,
        }
        tmp = path.with_suffix(".json.migrating")
        tmp.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        rows.append({
            "file": path.name,
            "packet": packet_key,
            "action": "migrated_pass",
            "source_version": source_version,
            "target_version": mod.CONTRACT_VERSION,
            "provider_calls_for_migration": 0,
        })
        migrated += 1

    report = {
        "gate": "Yoru v3.73 W12.3 Checkpoint Revalidation/Migration",
        "contract_version": mod.CONTRACT_VERSION,
        "checkpoint_dir": str(checkpoint_dir),
        "migrated_pass": migrated,
        "already_current_pass": already_current,
        "rejected": rejected,
        "skipped": skipped,
        "provider_calls": 0,
        "groq_tokens_used": 0,
        "production_ai_authorized": False,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "W12_3_CHECKPOINT_MIGRATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "W12_3_CHECKPOINT_MIGRATION.txt").write_text(
        "\n".join([
            report["gate"],
            f"contract_version={mod.CONTRACT_VERSION}",
            f"migrated_pass={migrated}",
            f"already_current_pass={already_current}",
            f"rejected={rejected}",
            f"skipped={skipped}",
            "provider_calls=0",
            "groq_tokens_used=0",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default=None)
    args = parser.parse_args()
    report = migrate(Path(args.checkpoint_dir), Path(args.out_dir), model=args.model, reasoning_effort=args.reasoning_effort)
    print((Path(args.out_dir) / "W12_3_CHECKPOINT_MIGRATION.txt").read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
