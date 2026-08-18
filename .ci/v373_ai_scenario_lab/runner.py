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
import unicodedata
import urllib.error
import urllib.request

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
DEFAULT_BATCH_SIZE = 5
MAX_COMPLETION_TOKENS = 2800
FORBIDDEN = {
    "amount", "balance", "cooldown", "inventory", "money", "payout",
    "probability", "reward", "rng", "success_chance", "wallet", "xp",
    "police_state", "world_state", "character_state", "permission", "settlement",
}
FANTASY_MARKERS = {
    "varázsló", "varázslat", "varázstárgy", "mágia", "kard", "városkapu",
    "fogadóban", "kovácsműhely", "gyógyital", "sárkány",
}
OPERATIONAL_HEIST_MARKERS = {
    "zárnyitó", "lockpick", "jammer", "robbanóanyag", "fúró használata",
    "kábelek átvágása", "kamera lekapcsol", "terminál hack", "ujjlenyomat",
    "biometrikus hamisítás", "riasztás elhallgat", "főáramot",
}


@dataclass(frozen=True, slots=True)
class Case:
    key: str
    scene_type: str
    family: str
    count: int
    brief: str


CASES = (
    Case("work", "work", "casual_work", 20, "hétköznapi magyar alkalmi munkahelyzetek: bolt, raktár, gyár, futár, vendéglátás, iroda, szerviz"),
    Case("career", "career", "generic_career", 20, "mai magyar karrierhelyzetek több szakmából, természetes munkahelyi döntésekkel"),
    Case("crime", "crime", "casual_crime", 20, "fiktív játékos bűnügyi helyzetek kizárólag absztrakt döntési szinten, valós módszer vagy útmutató nélkül"),
    Case("store_heist", "heist_store", "heist_store", 10, "fiktív boltrablás-jelenetek magas szintű csapatdöntésekkel; semmilyen technikai vagy operatív betörési módszer"),
    Case("bank_heist", "heist_bank", "heist_bank", 10, "fiktív bankrablás-jelenetek magas szintű csapatdöntésekkel; semmilyen technikai vagy operatív betörési módszer"),
    Case("npc_dialogue", "npc_dialogue", "npc_dialogue", 20, "jelenkori magyar life-RP NPC-helyzetek: boltos, szerelő, főnök, szomszéd, pultos, ügyintéző, sofőr, bérbeadó; fantasy nélkül"),
    Case("memory_recall", "memory_recall", "consequence_memory", 10, "korábbi játékosdöntés természetes felidézése úgy, hogy ne találjon ki nyers statot vagy mechanikai eredményt"),
    Case("world_context", "world_context", "world_context", 10, "Yoru világán belüli, magyar városok hangulatát idéző fiktív helyi hírek és lehetőségek; ne állíts valós hírt valódi intézményről"),
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


def prompts(case: Case, batch_index: int, prior_keys: list[str]) -> tuple[str, str]:
    system = (
        "A Yoru egy jelenkori magyar Discord life-RP játék. A DEV content labor számára írsz. "
        "Csak narratív/content javaslatot adhatsz; a Rule Engine az egyetlen mechanikai authority. "
        "Nem dönthetsz pénzről, RNG-ről, siker/kudarc esélyről, jutalomról, cooldownról, XP-ről, "
        "inventoryról, rendőrségi/world/character state-ről, permissionről vagy settlementről. "
        "A szöveg legyen mai, rövid, természetes magyar; ne legyen tankönyvszagú, fantasy, középkori, "
        "amerikai sablon vagy generikus AI-klisé. Ne használj indokolatlan angol szavakat. "
        "A döntések különböző játékosi hozzáállásokat adjanak, ne csak ugyanazt fogalmazzák át. "
        "Bűnügyi/heist jelenetben kizárólag magas szintű fiktív döntést adj: ne írj konkrét feltörési, "
        "riasztó-kikerülési, fegyveres, robbanóanyagos, hackelési, zárnyitási vagy nyomeltüntetési módszert."
    )
    previous = ", ".join(prior_keys[-20:]) if prior_keys else "nincs"
    user = (
        f"Generálj pontosan {case.count} különböző jelenetet ehhez a batchhez (batch #{batch_index}). "
        f"Scene type: {case.scene_type}. Family: {case.family}. Irány: {case.brief}. "
        "A key és semantic_key kizárólag ASCII snake_case legyen, ékezet nélkül, például: miskolci_muszakcsere. "
        "A title természetes magyar cím, a description 1-2 rövid mondat. 2-4 tömör choice legyen jelenetenként. "
        "A consequence_hint csak narratív irányt jelezhet, számszerű/mechanikai következményt nem. "
        f"Korábbi kulcsok, amelyeket tilos újra használni: {previous}."
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


def ascii_snake(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def normalize_keys(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for i, item in enumerate(payload.get("items") or []):
        if not isinstance(item, dict):
            continue
        for field in ("key", "semantic_key"):
            before = str(item.get(field, ""))
            after = ascii_snake(before)
            if after and after != before:
                item[field] = after
                warnings.append(f"items[{i}].{field}: {before!r} -> {after!r}")
        for j, choice in enumerate(item.get("choices") or []):
            if not isinstance(choice, dict):
                continue
            before = str(choice.get("key", ""))
            after = ascii_snake(before)
            if after and after != before:
                choice["key"] = after
                warnings.append(f"items[{i}].choices[{j}].key: {before!r} -> {after!r}")
    return warnings


def validate(case: Case, payload: dict[str, Any]) -> list[str]:
    errors = forbidden_paths(payload)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return errors + ["missing items array"]
    if len(items) != case.count:
        errors.append(f"expected {case.count} items, got {len(items)}")
    snake = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    keys: set[str] = set()
    semantics: set[str] = set()
    descriptions: list[tuple[str, str]] = []
    required = {"key", "scene_type", "family", "title", "description", "choices", "tags", "semantic_key"}
    for i, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != required:
            errors.append(f"items[{i}] invalid fields")
            continue
        if item["scene_type"] != case.scene_type or item["family"] != case.family:
            errors.append(f"items[{i}] family/type mismatch")
        key = str(item["key"])
        semantic = str(item["semantic_key"])
        if not snake.fullmatch(key):
            errors.append(f"items[{i}] invalid key")
        if not snake.fullmatch(semantic):
            errors.append(f"items[{i}] invalid semantic_key")
        if key in keys:
            errors.append(f"duplicate key {key}")
        if semantic in semantics:
            errors.append(f"duplicate semantic_key {semantic}")
        keys.add(key)
        semantics.add(semantic)
        text = " ".join([
            str(item.get("title", "")),
            str(item.get("description", "")),
            " ".join(str(c.get("label", "")) for c in item.get("choices", []) if isinstance(c, dict)),
        ]).lower()
        if case.key == "npc_dialogue":
            for marker in FANTASY_MARKERS:
                if marker in text:
                    errors.append(f"items[{i}] fantasy marker: {marker}")
        if case.key in {"store_heist", "bank_heist"}:
            for marker in OPERATIONAL_HEIST_MARKERS:
                if marker in text:
                    errors.append(f"items[{i}] operational heist marker: {marker}")
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
    assert {c.key for c in CASES} == {
        "work", "career", "crime", "store_heist", "bank_heist",
        "npc_dialogue", "memory_recall", "world_context",
    }
    assert ascii_snake("miskolci_női_vállalkozók") == "miskolci_noi_vallalkozok"


def _delay_from_429(exc: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After", "")
    try:
        return max(1.0, min(float(retry_after), 90.0))
    except (TypeError, ValueError):
        return min(15.0 * (2 ** attempt), 90.0)


def request(
    case: Case,
    api_key: str,
    model: str,
    effort: str,
    timeout: float,
    batch_index: int,
    prior_keys: list[str],
) -> tuple[dict[str, Any], dict[str, Any], float]:
    system, user = prompts(case, batch_index, prior_keys)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "reasoning_effort": effort,
        "temperature": 0.8,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": f"yoru_{case.key}_{batch_index}", "strict": True, "schema": schema(case)},
        },
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    started = time.perf_counter()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = json.loads(response.read().decode())
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", "replace")
            if exc.code == 429 and attempt < 3:
                delay = _delay_from_429(exc, attempt)
                print(f"Groq rate limit for {case.key} batch {batch_index}; retrying in {delay:.1f}s (attempt {attempt + 2}/4)")
                time.sleep(delay)
                continue
            raise RuntimeError(f"Groq HTTP {exc.code} {exc.reason}: {error_body[:4000]}") from exc
    else:
        raise RuntimeError("Groq request retry loop exhausted")
    latency = (time.perf_counter() - started) * 1000
    content = raw["choices"][0]["message"]["content"]
    return json.loads(content), raw.get("usage") or {}, latency


def generate_case(
    case: Case,
    api_key: str,
    model: str,
    effort: str,
    timeout: float,
    batch_size: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    batch_reports: list[dict[str, Any]] = []
    normalization_warnings: list[str] = []
    batch_index = 1
    while len(items) < case.count:
        want = min(batch_size, case.count - len(items))
        batch_case = Case(case.key, case.scene_type, case.family, want, case.brief)
        last_error = ""
        for batch_attempt in range(3):
            payload, usage, latency = request(
                batch_case, api_key, model, effort, timeout, batch_index,
                [str(item.get("key", "")) for item in items],
            )
            warnings = normalize_keys(payload)
            normalization_warnings.extend(f"batch {batch_index}: {w}" for w in warnings)
            batch_items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(batch_items, list):
                last_error = "missing items array"
                continue
            if len(batch_items) != want:
                last_error = f"expected batch size {want}, got {len(batch_items)}"
                continue
            combined = {"items": items + batch_items}
            provisional = Case(case.key, case.scene_type, case.family, len(combined["items"]), case.brief)
            errors = validate(provisional, combined)
            if errors:
                last_error = "; ".join(errors[:8])
                continue
            items.extend(batch_items)
            batch_reports.append({
                "batch": batch_index,
                "requested": want,
                "received": len(batch_items),
                "latency_ms": round(latency, 3),
                "usage": usage,
                "normalizations": len(warnings),
            })
            break
        else:
            raise RuntimeError(f"{case.key} batch {batch_index} failed after 3 content attempts: {last_error}")
        batch_index += 1
    return {"items": items}, batch_reports, normalization_warnings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="low")
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--out-dir", default="artifacts/ai_scenario_lab")
    args = p.parse_args()
    if args.batch_size < 1 or args.batch_size > 5:
        raise SystemExit("--batch-size must be between 1 and 5")
    self_test()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        report = {
            "status": "DRY_RUN_PASS",
            "model": args.model,
            "items_requested": 120,
            "batch_size": args.batch_size,
            "max_completion_tokens_per_request": MAX_COMPLETION_TOKENS,
            "production_ai_authorized": False,
            "cases": [asdict(c) for c in CASES],
        }
        (out / "YORU_AI_SCENARIO_LAB_DRY_RUN.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("GROQ_API_KEY is required")

    results: list[dict[str, Any]] = []
    for case in CASES:
        try:
            payload, batches, normalizations = generate_case(
                case, api_key, args.model, args.reasoning_effort, args.timeout, args.batch_size,
            )
            errors = validate(case, payload)
            results.append({
                "case": asdict(case),
                "status": "PASS" if not errors else "FAIL",
                "validation_errors": errors,
                "batch_reports": batches,
                "normalization_warnings": normalizations,
                "payload": payload,
            })
        except Exception as exc:
            results.append({
                "case": asdict(case),
                "status": "FAIL",
                "validation_errors": [f"{type(exc).__name__}: {exc}"],
                "batch_reports": [],
                "normalization_warnings": [],
                "payload": None,
            })

    passed = sum(r["status"] == "PASS" for r in results)
    all_items = sum(len((r.get("payload") or {}).get("items", [])) for r in results)
    normalized = sum(len(r.get("normalization_warnings") or []) for r in results)
    summary = {
        "gate": "Yoru v3.73 AI Scenario Lab PoC",
        "status": "PASS" if passed == len(CASES) else "FAIL",
        "cases_passed": passed,
        "cases_total": len(CASES),
        "items_requested": 120,
        "items_generated": all_items,
        "items_validated": sum(len((r.get("payload") or {}).get("items", [])) for r in results if r["status"] == "PASS"),
        "key_normalizations": normalized,
        "human_review_required": True,
        "production_ai_authorized": False,
    }
    (out / "YORU_AI_SCENARIO_LAB_RESULT.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "YORU_AI_SCENARIO_LAB_RESULT.txt").write_text(
        "\n".join([
            summary["gate"],
            f"STATUS: {summary['status']}",
            f"cases={passed}/{len(CASES)}",
            f"items={summary['items_validated']}/120",
            f"key_normalizations={normalized}",
            "human_review_required=true",
            "production_ai_authorized=false",
            "",
        ]),
        encoding="utf-8",
    )
    with (out / "YORU_AI_SCENARIO_LAB_HUMAN_REVIEW.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "case", "key", "title", "description", "choices",
            "natural_hungarian_1_5", "yoru_tone_1_5", "not_ai_smell_1_5", "logic_1_5", "notes",
        ])
        for result in results:
            for item in (result.get("payload") or {}).get("items", []):
                choices = " | ".join(str(c.get("label", "")) for c in item.get("choices", []) if isinstance(c, dict))
                w.writerow([
                    result["case"]["key"], item.get("key", ""), item.get("title", ""),
                    item.get("description", ""), choices, "", "", "", "", "",
                ])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
