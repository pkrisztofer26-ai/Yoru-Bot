from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import importlib.util
import json
import os
import sys
import time

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"
CANARY_PACKETS = (
    "work_miskolc_canteen",
    "career_cnc_quality",
    "crime_unknown_envelope",
    "store_heist_teammate_panic",
    "npc_lilla_dispatcher",
    "memory_nora_wallet",
    "world_eger_heat",
)


def _load_target():
    spec = importlib.util.spec_from_file_location("w123_canary_target", TARGET)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {TARGET}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    lab = mod.V2.load_lab()
    mod.V2.install_provider_hotfix(lab)
    mod.install_semantic_layer(lab)
    return mod, lab


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", default="https://api.groq.com/openai/v1/chat/completions")
    p.add_argument("--model", default="openai/gpt-oss-120b")
    p.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="low")
    p.add_argument("--timeout", type=float, default=40.0)
    p.add_argument("--max-completion-tokens", type=int, default=900)
    p.add_argument("--http-retries", type=int, default=1)
    p.add_argument("--content-retries", type=int, default=0)
    p.add_argument("--rate-floor-tokens", type=int, default=1800)
    p.add_argument("--input-usd-per-million", type=float, default=0.15)
    p.add_argument("--output-usd-per-million", type=float, default=0.60)
    p.add_argument("--out-dir", default="artifacts/ai_semantic_skeleton_lab")
    return p.parse_args()


def _write(out: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    doc = {"summary": summary, "results": results}
    (out / "YORU_AI_GROUNDED_LAB_RESULT.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "YORU_AI_GROUNDED_LAB_RESULT.txt").write_text(
        "\n".join([
            "Yoru v3.73 W12.3 High-Risk Canary",
            f"STATUS: {summary['status']}",
            f"contract_version={summary['contract_version']}",
            "run_scope=canary",
            f"packets={summary.get('packets_passed', 0)}/{summary.get('packets_total', len(CANARY_PACKETS))}",
            f"items={summary.get('items_validated', 0)}/{len(CANARY_PACKETS) * 5}",
            f"resumed_pass_packets={summary.get('resumed_pass_packets', 0)}",
            f"provider_requests_this_run={summary.get('provider_requests_this_run', 0)}",
            f"provider_blocked_reason={summary.get('provider_blocked_reason', '')}",
            f"provider_retry_after_seconds={summary.get('provider_retry_after_seconds', 0)}",
            "human_review_required=true",
            "production_ai_authorized=false",
            "",
        ]), encoding="utf-8"
    )
    # Human-review CSV format is already implemented by the frozen lab.


def main() -> int:
    args = _args()
    mod, lab = _load_target()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key_map = {p.key: p for p in lab.PACKETS}
    packets = [key_map[k] for k in CANARY_PACKETS]
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GROQ_API_KEY")

    started = time.perf_counter()
    results_by_key: dict[str, dict[str, Any]] = {}
    prior_keys: list[str] = []
    resumed = 0
    requests = 0

    # Reuse only checkpoints that satisfy the current contract. Migration is
    # performed by the workflow before this script runs.
    for packet in packets:
        result = lab.load_pass_checkpoint(out, packet, args)
        if result is not None:
            results_by_key[packet.key] = result
            prior_keys.extend(lab._prior_keys_from_result(result))
            resumed += 1
            print(f"CANARY RESUME_PASS {packet.key}", flush=True)

    try:
        for index, packet in enumerate(packets, 1):
            if packet.key in results_by_key:
                continue
            print(f"CANARY {index}/{len(packets)} START {packet.key}", flush=True)
            result = lab.run_packet(args, packet, api_key, prior_keys)
            requests += 1
            lab.save_checkpoint(out, packet, args, result)
            if result.get("status") != "PASS":
                results_by_key[packet.key] = result
                ordered = [results_by_key[k] for k in CANARY_PACKETS if k in results_by_key]
                summary = {
                    "gate": "Yoru v3.73 W12.3 High-Risk Canary",
                    "contract_version": mod.CONTRACT_VERSION,
                    "run_scope": "canary",
                    "status": "FAIL",
                    "packets_passed": sum(r.get("status") == "PASS" for r in ordered),
                    "packets_failed": sum(r.get("status") == "FAIL" for r in ordered),
                    "packets_total": len(packets),
                    "items_validated": sum(len((r.get("payload") or {}).get("items", [])) for r in ordered if r.get("status") == "PASS"),
                    "resumed_pass_packets": resumed,
                    "provider_requests_this_run": requests,
                    "fail_fast": True,
                    "checkpoint_progress_preserved": True,
                    "human_review_required": True,
                    "production_ai_authorized": False,
                }
                _write(out, summary, ordered)
                lab.write_human_review(out / "YORU_AI_GROUNDED_LAB_HUMAN_REVIEW.csv", ordered)
                print(f"CANARY FAIL_FAST packet={packet.key}", flush=True)
                return 1
            results_by_key[packet.key] = result
            prior_keys.extend(lab._prior_keys_from_result(result))
            lab.maybe_rate_pause(result, args.rate_floor_tokens)
            print(f"CANARY PASS {packet.key}", flush=True)

    except mod.V2.DailyTokenLimitStop as exc:
        ordered = [results_by_key[k] for k in CANARY_PACKETS if k in results_by_key]
        summary = {
            "gate": "Yoru v3.73 W12.3 High-Risk Canary",
            "contract_version": mod.CONTRACT_VERSION,
            "run_scope": "canary",
            "status": "INCOMPLETE",
            "provider_blocked_reason": "daily_token_limit",
            "provider_retry_after_seconds": round(float(exc.retry_after_seconds), 3),
            "checkpoint_progress_preserved": True,
            "packets_passed": sum(r.get("status") == "PASS" for r in ordered),
            "packets_failed": 0,
            "packets_total": len(packets),
            "items_validated": sum(len((r.get("payload") or {}).get("items", [])) for r in ordered),
            "resumed_pass_packets": resumed,
            "provider_requests_this_run": requests,
            "human_review_required": True,
            "production_ai_authorized": False,
        }
        _write(out, summary, ordered)
        lab.write_human_review(out / "YORU_AI_GROUNDED_LAB_HUMAN_REVIEW.csv", ordered)
        print(f"CANARY_TPD_STOP retry_after={exc.retry_after_seconds:.1f}s", flush=True)
        return 2

    ordered = [results_by_key[k] for k in CANARY_PACKETS]
    global_errors = lab.global_validation(ordered)
    status = "PASS" if not global_errors else "FAIL"
    summary = {
        "gate": "Yoru v3.73 W12.3 High-Risk Canary",
        "contract_version": mod.CONTRACT_VERSION,
        "run_scope": "canary",
        "status": status,
        "packets_passed": len(ordered) if not global_errors else 0,
        "packets_failed": 0 if not global_errors else len(ordered),
        "packets_total": len(packets),
        "items_validated": sum(len((r.get("payload") or {}).get("items", [])) for r in ordered),
        "global_validation_errors": global_errors,
        "resumed_pass_packets": resumed,
        "provider_requests_this_run": requests,
        "elapsed_seconds_this_run": round(time.perf_counter() - started, 3),
        "checkpoint_progress_preserved": True,
        "human_review_required": True,
        "production_ai_authorized": False,
    }
    _write(out, summary, ordered)
    lab.write_human_review(out / "YORU_AI_GROUNDED_LAB_HUMAN_REVIEW.csv", ordered)
    print(f"CANARY {status} packets={len(ordered)}/{len(packets)} items={summary['items_validated']}/{len(packets)*5}", flush=True)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
