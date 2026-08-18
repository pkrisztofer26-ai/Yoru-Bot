from __future__ import annotations

"""DEV-only Yoru v3.73 AI Scenario Lab.

Narrative/content evaluation only. This file never imports Discord, never opens
Yoru's DB, and never grants AI authority over gameplay state.
"""

from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import argparse
import csv
import json
import os
import re
import time
import urllib.request

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
FORBIDDEN = {
    "amount", "balance", "cooldown", "inventory", "money", "payout",
    "probability", "reward", "rng", "success_chance", "wallet", "xp",
    "police_state", "world_state", "character_state", "permission", "settlement",
}

@dataclass(frozen=True, slots=True)
class Case:
    key: str
    scene_type: str
    family: str
    count: int
    brief: str

CASES = (
    Case("work", "work", "casual_work", 20, "hétköznapi magyar alkalmi munkahelyzetek"),
    Case("career", "career", "generic_career", 20, "természetes karrierhelyzetek több szakmából"),
    Case("crime", "crime", "casual_crime", 20, "fiktív játékos bűnügyi helyzetek, valós útmutató nélkül"),
    Case("store_heist", "heist_store", "heist_store", 10, "fiktív boltrablás döntési pontok absztrakt játékmechanikai szinten"),
    Case("bank_heist", "heist_bank", "heist_bank", 10, "fiktív bankrablás döntési pontok absztrakt játékmechanikai szinten"),
    Case("npc_dialogue", "npc_dialogue", "npc_dialogue", 20, "rövid természetes magyar NPC-dialógushelyzetek"),
    Case("memory_recall", "memory_recall", "consequence_memory", 10, "korábbi döntés természetes visszahívása nyers reputation nélkül"),
    Case("world_context", "world_context", "world_context", 10, "magyar városi hír vagy opportunity in-world hangon"),
)


def schema(case: Case) -> dict[str, Any]:
    choice = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "label": {"type": "string"},
            "consequence_hint": {"type": "string"},
        },
        "required": ["key", "label", "consequence_hint"],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "scene_type": {"type": "string", "enum": [case.scene_type]},
            "family": {"type": "string", "enum": [case.family]},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "choices": {"type": "array", "minItems": 1, "maxItems": 4, "items": choice},
            "tags": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string"}},
            "semantic_key": {"type": "string"},
        },
        "required": ["key", "scene_type", "family", "title", "description", "choices", "tags", "semantic_key"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item}},
        "required": ["items"],
        "additionalProperties": False,
    }


def prompts(case: Case) -> tuple[str, str]:
    system = (
        "Yoru nevű magyar Discord life-RP játék DEV content laborjában dolgozol. "
        "Csak narratív/content javaslatot adhatsz. Nem dönthetsz pénzről, RNG-ről, "
        "success/fail eredményről, rewardról, cooldownról, XP-ről, inventoryról, "
        "rendőrségi/world/character state-ről, permissionről vagy settlementről. "
        "Írj mai, természetes, tömör magyar szöveget, generikus AI-klisék nélkül. "
        "Bűnügyi/heist tartalom csak fiktív játékhelyzet lehet valós operatív útmutató nélkül."
    )
    user = (
        f"Generálj pontosan {case.count} különböző jelenetet. Scene type: {case.scene_type}. "
        f"Family: {case.family}. Irány: {case.brief}. A key és semantic_key ASCII snake_case. "
        "A description 1-3 mondat. Choices valódi döntés legyen mechanikai esély/jutalom nélkül."
    )
    return system, user


def forbidden_paths(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN:
                errors.append(f"forbidden authority field {path}.{key}")
            errors.extend(forbidden_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            errors.extend(forbidden_paths(child, f"{path}[{i}]"))
    return errors


def validate(case: Case, payload: dict[str, Any]) -> list[str]:
    errors = forbidden_paths(payload)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return errors + ["missing items array"]
    if len(items) != case.count:
        errors.append(f"expected {case.count} items, got {len(items)}")
    snake = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    keys: set[str] = set(); semantics: set[str] = set(); descriptions: list[tuple[str, str]] = []
    required = {"key", "scene_type", "family", "title", "description", "choices", "tags", "semantic_key"}
    for i, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != required:
            errors.append(f"items[{i}] invalid fields"); continue
        if item["scene_type"] != case.scene_type or item["family"] != case.family:
            errors.append(f"items[{i}] family/type mismatch")
        key = str(item["key"]); semantic = str(item["semantic_key"])
        if not snake.fullmatch(key): errors.append(f"items[{i}] invalid key")
        if not snake.fullmatch(semantic): errors.append(f"items[{i}] invalid semantic_key")
        if key in keys: errors.append(f"duplicate key {key}")
        if semantic in semantics: errors.append(f"duplicate semantic_key {semantic}")
        keys.add(key); semantics.add(semantic)
        descriptions.append((key, str(item["description"])))
    for i in range(len(descriptions)):
        for j in range(i + 1, len(descriptions)):
            ratio = SequenceMatcher(None, descriptions[i][1].lower(), descriptions[j][1].lower()).ratio()
            if ratio >= 0.88:
                errors.append(f"near duplicate {descriptions[i][0]}/{descriptions[j][0]} ratio={ratio:.3f}")
    return errors


def self_test() -> None:
    assert sum(c.count for c in CASES) == 120
    raw = json.dumps({c.key: schema(c) for c in CASES}, sort_keys=True).lower()
    assert all(f'"{field}"' not in raw for field in FORBIDDEN)
    assert {c.key for c in CASES} == {"work", "career", "crime", "store_heist", "bank_heist", "npc_dialogue", "memory_recall", "world_context"}


def request(case: Case, api_key: str, model: str, effort: str, timeout: float) -> tuple[dict[str, Any], dict[str, Any], float]:
    system, user = prompts(case)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "reasoning_effort": effort,
        "response_format": {"type": "json_schema", "json_schema": {"name": f"yoru_{case.key}", "strict": True, "schema": schema(case)}},
    }
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = json.loads(response.read().decode())
    latency = (time.perf_counter() - started) * 1000
    content = raw["choices"][0]["message"]["content"]
    return json.loads(content), raw.get("usage") or {}, latency


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="low")
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--out-dir", default="artifacts/ai_scenario_lab")
    args = p.parse_args()
    self_test()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        report = {"status": "DRY_RUN_PASS", "model": args.model, "items_requested": 120, "production_ai_authorized": False, "cases": [asdict(c) for c in CASES]}
        (out / "YORU_AI_SCENARIO_LAB_DRY_RUN.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key: raise SystemExit("GROQ_API_KEY is required")
    results: list[dict[str, Any]] = []
    for case in CASES:
        try:
            payload, usage, latency = request(case, api_key, args.model, args.reasoning_effort, args.timeout)
            errors = validate(case, payload)
            results.append({"case": asdict(case), "status": "PASS" if not errors else "FAIL", "latency_ms": round(latency, 3), "usage": usage, "validation_errors": errors, "payload": payload})
        except Exception as exc:
            results.append({"case": asdict(case), "status": "FAIL", "validation_errors": [f"{type(exc).__name__}: {exc}"], "payload": None})
    passed = sum(r["status"] == "PASS" for r in results)
    summary = {"gate": "Yoru v3.73 AI Scenario Lab PoC", "status": "PASS" if passed == len(CASES) else "FAIL", "cases_passed": passed, "cases_total": len(CASES), "items_requested": 120, "items_validated": sum(len((r.get("payload") or {}).get("items", [])) for r in results if r["status"] == "PASS"), "human_review_required": True, "production_ai_authorized": False}
    (out / "YORU_AI_SCENARIO_LAB_RESULT.json").write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "YORU_AI_SCENARIO_LAB_RESULT.txt").write_text("\n".join([summary["gate"], f"STATUS: {summary['status']}", f"cases={passed}/{len(CASES)}", f"items={summary['items_validated']}/120", "human_review_required=true", "production_ai_authorized=false", ""]), encoding="utf-8")
    with (out / "YORU_AI_SCENARIO_LAB_HUMAN_REVIEW.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["case", "key", "title", "natural_hungarian_1_5", "yoru_tone_1_5", "not_ai_smell_1_5", "logic_1_5", "notes"])
        for result in results:
            for item in (result.get("payload") or {}).get("items", []): w.writerow([result["case"]["key"], item.get("key", ""), item.get("title", ""), "", "", "", "", ""])
    print(json.dumps(summary, ensure_ascii=False, indent=2)); return 0 if summary["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
