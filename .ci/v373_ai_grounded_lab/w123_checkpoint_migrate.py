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


def _write_migrated_checkpoint(path: Path, doc: dict[str, Any], lab, mod, packet, result: dict[str, Any]) -> None:
    new_doc = {
        "contract_version": mod.CONTRACT_VERSION,
        "packet_fingerprint": lab.packet_fingerprint(packet),
        "model": doc.get("model"),
        "reasoning_effort": doc.get("reasoning_effort"),
        "saved_at_unix": round(time.time(), 3),
        "result": result,
    }
    tmp = path.with_suffix(".json.migrating")
    tmp.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def migrate(checkpoint_dir: Path, out_dir: Path, *, model: str | None, reasoning_effort: str | None) -> dict[str, Any]:
    mod, lab = _load_target()
    packet_by_key = {p.key: p for p in lab.PACKETS}
    rows = []
    migrated = 0
    salvaged_failed = 0
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
        if not isinstance(result, dict):
            rows.append({"file": path.name, "packet": packet_key, "action": "skip_missing_result"})
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
        source_status = str(result.get("status") or "")

        # v5 can salvage a historical FAIL with zero provider calls when the
        # exact provider surface was preserved. The current contract chooses
        # the minimum golden-slot repair and fully revalidates the final payload.
        if source_status == "FAIL":
            surfaces = result.get("provider_surfaces") or []
            salvage_payload = None
            salvage_meta = None
            for surface in reversed(surfaces):
                try:
                    payload, repair = mod.repair_surface_with_golden(lab, packet, surface)
                    errors = lab.validate_payload(packet, payload) if isinstance(payload, dict) else ["missing repaired payload"]
                except Exception as exc:
                    payload = None
                    repair = {"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}
                    errors = [repair["error"]]
                if payload is not None and not errors:
                    salvage_payload = payload
                    salvage_meta = repair
                    break

            if salvage_payload is None:
                rows.append({
                    "file": path.name,
                    "packet": packet_key,
                    "action": "skip_non_pass_no_safe_surface_salvage",
                    "source_status": source_status,
                    "source_version": source_version,
                })
                skipped += 1
                continue

            migrated_result = dict(result)
            migrated_result["status"] = "PASS"
            migrated_result["payload"] = salvage_payload
            migrated_result["salvaged_from_failed_checkpoint"] = True
            migrated_result["host_surface_repair"] = {
                **(salvage_meta or {}),
                "trigger": "checkpoint_fail_surface_salvage",
            }
            migrated_result["surface_quality"] = {
                "provider_attempt_surfaces": len(surfaces),
                "golden_fallback_slots": list((salvage_meta or {}).get("golden_fallback_slots") or []),
                "golden_fallback_count": int((salvage_meta or {}).get("golden_fallback_count") or 0),
                "native_slot_count": int((salvage_meta or {}).get("native_slot_count") or 0),
                "provider_second_content_request_used": False,
            }
            migrated_result["checkpoint_migration"] = {
                "source_contract_version": source_version,
                "source_status": "FAIL",
                "target_contract_version": mod.CONTRACT_VERSION,
                "provider_reused": False,
                "provider_calls_for_migration": 0,
                "failed_surface_salvaged": True,
                "revalidated_at_unix": round(time.time(), 3),
            }
            _write_migrated_checkpoint(path, doc, lab, mod, packet, migrated_result)
            rows.append({
                "file": path.name,
                "packet": packet_key,
                "action": "salvaged_failed_surface",
                "source_version": source_version,
                "target_version": mod.CONTRACT_VERSION,
                "golden_fallback_count": int((salvage_meta or {}).get("golden_fallback_count") or 0),
                "provider_calls_for_migration": 0,
            })
            salvaged_failed += 1
            continue

        if source_status != "PASS":
            rows.append({"file": path.name, "packet": packet_key, "action": "skip_non_pass", "source_status": source_status})
            skipped += 1
            continue

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
            # A historical PASS may still be safely recoverable under v5's
            # deterministic surface fallback. This prevents a contract bump
            # from forcing a new provider request solely for wording changes.
            try:
                current_payload, repair = mod.repair_surface_with_golden(lab, packet, surface)
                errors = lab.validate_payload(packet, current_payload) if current_payload else ["repair failed"]
            except Exception as exc:
                repair = {"status": "FAIL"}
                current_payload = None
                errors = [f"repair:{type(exc).__name__}:{exc}"]
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
        else:
            repair = None

        migrated_result = dict(result)
        migrated_result["payload"] = current_payload
        if repair and repair.get("golden_fallback_count"):
            migrated_result["host_surface_repair"] = {
                **repair,
                "trigger": "checkpoint_pass_surface_repair",
            }
        migrated_result["checkpoint_migration"] = {
            "source_contract_version": source_version,
            "source_status": "PASS",
            "target_contract_version": mod.CONTRACT_VERSION,
            "provider_reused": False,
            "provider_calls_for_migration": 0,
            "revalidated_at_unix": round(time.time(), 3),
        }
        _write_migrated_checkpoint(path, doc, lab, mod, packet, migrated_result)
        rows.append({
            "file": path.name,
            "packet": packet_key,
            "action": "migrated_pass",
            "source_version": source_version,
            "target_version": mod.CONTRACT_VERSION,
            "golden_fallback_count": int((repair or {}).get("golden_fallback_count") or 0),
            "provider_calls_for_migration": 0,
        })
        migrated += 1

    report = {
        "gate": "Yoru v3.73 W12.3 Checkpoint Revalidation/Migration",
        "contract_version": mod.CONTRACT_VERSION,
        "checkpoint_dir": str(checkpoint_dir),
        "migrated_pass": migrated,
        "salvaged_failed": salvaged_failed,
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
            f"salvaged_failed={salvaged_failed}",
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
