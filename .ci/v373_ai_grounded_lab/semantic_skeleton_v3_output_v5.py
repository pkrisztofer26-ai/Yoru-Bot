from __future__ import annotations

from semantic_skeleton_v3_rules import *
import json
import os
import sys

def out_dir_from_argv() -> Path:
    args = sys.argv[1:]
    if "--out-dir" in args:
        i = args.index("--out-dir")
        if i + 1 < len(args):
            return Path(args[i + 1])
    return Path("artifacts/ai_semantic_skeleton_lab")


def rewrite_gate_files(out: Path, regression: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "W12_3_REGRESSION_RESULT.json").write_text(json.dumps(regression, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "W12_3_REGRESSION_RESULT.txt").write_text(
        "\n".join([
            regression["gate"],
            f"STATUS: {regression['acceptance']}",
            f"legacy_packets_rejected={regression['legacy_packets_rejected']}/24",
            f"blocker_packets_rejected={regression['blocker_packets_rejected']}/{regression['source_blocker_packets']}",
            f"source_items={regression['source_items']}/120",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )

    dry = out / "YORU_AI_GROUNDED_LAB_DRY_RUN.json"
    if dry.is_file():
        try:
            data = json.loads(dry.read_text(encoding="utf-8"))
            data["gate"] = GATE_NAME
            data["contract_version"] = CONTRACT_VERSION
            data["run_scope"] = os.environ.get("W123_RUN_SCOPE", "full")
            data["semantic_skeleton"] = {
                "provider_fields": ["slot", "title", "description"],
                "provider_role": "seed_guided_surface_paraphraser",
                "host_owned": ["key", "semantic_key", "choices", "tags", "grounding_ids", "entities_mentioned", "new_fact_claims"],
                "world_player_choices": False,
                "packet_fallback_policy": "atomic_golden_packet",
                "provider_content_retries": 0,
                "w122_regression_packets_rejected": regression["legacy_packets_rejected"],
                "w122_blocker_packets_rejected": regression["blocker_packets_rejected"],
            }
            dry.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    result = out / "YORU_AI_GROUNDED_LAB_RESULT.json"
    if result.is_file():
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
            summary = data.get("summary", {})
            if isinstance(summary, dict):
                summary["gate"] = GATE_NAME
                summary["contract_version"] = CONTRACT_VERSION
                summary["semantic_skeleton_enabled"] = True
                summary["run_scope"] = os.environ.get("W123_RUN_SCOPE", "full")
                summary["w122_regression_packets_rejected"] = regression["legacy_packets_rejected"]
                summary["w122_blocker_packets_rejected"] = regression["blocker_packets_rejected"]
                results = data.get("results") if isinstance(data.get("results"), list) else []
                fallback_slots = sum(
                    int((r.get("surface_quality") or {}).get("golden_fallback_count", 0) or 0)
                    for r in results if isinstance(r, dict)
                )
                repaired_packets = sum(
                    1 for r in results
                    if isinstance(r, dict)
                    and int((r.get("surface_quality") or {}).get("golden_fallback_count", 0) or 0) > 0
                )
                schema_recovered = sum(
                    1 for r in results if isinstance(r, dict)
                    and any(
                        isinstance(ev, dict) and ev.get("trigger") == "provider_json_schema_failed_generation"
                        for ev in (r.get("provider_surface_events") or [])
                    )
                )
                validated_slots = sum(
                    len((r.get("payload") or {}).get("items", []))
                    for r in results if isinstance(r, dict) and r.get("status") == "PASS"
                )
                summary["golden_fallback_slots"] = fallback_slots
                summary["native_slots"] = max(0, validated_slots - fallback_slots)
                summary["repaired_packets"] = repaired_packets
                summary["schema_recovered_packets"] = schema_recovered
                summary["provider_content_retries"] = 0
            result.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    result_txt = out / "YORU_AI_GROUNDED_LAB_RESULT.txt"
    if result_txt.is_file():
        text = result_txt.read_text(encoding="utf-8")
        lines = text.splitlines()
        if lines:
            lines[0] = GATE_NAME
        result_txt.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    old_progress = out / "W12_2_PROGRESS.txt"
    if old_progress.is_file():
        (out / "W12_3_PROGRESS.txt").write_text(old_progress.read_text(encoding="utf-8"), encoding="utf-8")


def write_tpd_stop(out: Path, exc) -> None:
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "gate": GATE_NAME,
        "contract_version": CONTRACT_VERSION,
        "status": "INCOMPLETE",
        "run_scope": os.environ.get("W123_RUN_SCOPE", "full"),
        "provider_blocked_reason": "daily_token_limit",
        "provider_retry_after_seconds": round(float(exc.retry_after_seconds), 3),
        "checkpoint_progress_preserved": True,
        "semantic_skeleton_enabled": True,
        "human_review_required": True,
        "production_ai_authorized": False,
    }
    (out / "YORU_AI_GROUNDED_LAB_RESULT.json").write_text(json.dumps({"summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "YORU_AI_GROUNDED_LAB_RESULT.txt").write_text(
        "\n".join([
            GATE_NAME,
            "STATUS: INCOMPLETE",
            "provider_blocked_reason=daily_token_limit",
            f"provider_retry_after_seconds={summary['provider_retry_after_seconds']}",
            "checkpoint_progress_preserved=true",
            "semantic_skeleton_enabled=true",
            "human_review_required=true",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )
    print(
        f"TPD_BUDGET_STOP retry_after={float(exc.retry_after_seconds):.1f}s "
        "checkpoint_progress_preserved=true; W12.3 auto-resume eligible",
        flush=True,
    )
