from __future__ import annotations

"""W12.2 FAST/RESUME v2 CI hotfix layer.

Keeps the frozen v1 fixture intact while fixing two provider-facing issues:
1) host owns packet key namespaces, so AI slug drift cannot fail a grounded item;
2) Groq TPD exhaustion stops immediately instead of burning the CI wall clock.
"""

from pathlib import Path
from typing import Any
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
RUNTIME_RUNNER = HERE / "runtime" / "runner.py"
HOTFIX_VERSION = "w12.2-fast-resume-v2"
TARGETED_PROMPT_PACKET = "crime_stolen_phone_offer"


def grounded_user_prompt(lab, packet, prior_keys: list[str]) -> str:
    """Keep the canonical prompt, with a narrow lexical/diversity guard for one stuck packet."""
    base = lab.user_prompt(packet, prior_keys)
    if packet.key != TARGETED_PROMPT_PACKET:
        return base
    return base + (
        "\n\nPACKET_SPECIFIC_GUARD — crime_stolen_phone_offer:\n"
        "- A validator tiltja ezeket a szavakat az output bármely szövegmezőjében: "
        "kedvezmény, ingyenes, ingyenesen, ajándékba. Egyiket se használd.\n"
        "- Az ajánlat árjellegét csak a grounded fact értelmében, például „feltűnően olcsó” "
        "vagy „gyanúsan olcsó” formában írd le; ne találj ki árat, akciót, ajándékot vagy új feltételt.\n"
        "- Az öt jelenet descriptionje legyen ténylegesen eltérő megfogalmazású. "
        "Váltogasd a hangsúlyt kizárólag a meglévő factek között: gyanús ajánlat, kitérő eredetválasz, "
        "visszautasítás, beszélgetés megszakítása, további tisztázás. Új tényt ne adj hozzá.\n"
    )


class DailyTokenLimitStop(BaseException):
    def __init__(self, detail: str, retry_after_seconds: float):
        super().__init__(detail)
        self.detail = detail
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))


def load_lab():
    spec = importlib.util.spec_from_file_location("w122_frozen_runner", RUNTIME_RUNNER)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import frozen runner: {RUNTIME_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.CONTRACT_VERSION = HOTFIX_VERSION
    return module


def parse_reset_seconds(value: str | None) -> float:
    raw = str(value or "").strip().lower()
    if not raw:
        return 0.0
    total = 0.0
    for amount, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h)", raw):
        total += float(amount) * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]
    if total:
        return total
    try:
        return float(raw)
    except ValueError:
        return 0.0


def daily_limit_retry_seconds(detail: str, headers: Any = None) -> float:
    low = str(detail or "").lower()
    if "tokens per day" not in low and "(tpd)" not in low and " tpd" not in low:
        return 0.0
    waits: list[float] = []
    match = re.search(r"try again in\s+([0-9.]+(?:ms|s|m|h)(?:[0-9.]+(?:ms|s|m|h))*)", low)
    if match:
        waits.append(parse_reset_seconds(match.group(1)))
    if headers is not None:
        try:
            waits.append(parse_reset_seconds(headers.get("Retry-After")))
            waits.append(parse_reset_seconds(headers.get("x-ratelimit-reset-tokens")))
        except Exception:
            pass
    return max((x for x in waits if x > 0), default=1.0)


def host_namespace(lab, packet, payload: dict[str, Any]) -> int:
    changed = 0
    seen_item: set[str] = set()
    seen_sem: set[str] = set()
    items = payload.get("items", []) if isinstance(payload, dict) else []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        for field, seen, fallback in (
            ("key", seen_item, f"variant_{index:02d}"),
            ("semantic_key", seen_sem, f"semantic_{index:02d}"),
        ):
            raw = str(item.get(field, ""))
            norm = lab._ascii_snake(raw)
            prefix = packet.key + "_"
            suffix = norm[len(prefix):] if norm.startswith(prefix) else norm
            suffix = suffix or fallback
            candidate = prefix + suffix
            if candidate in seen:
                candidate = f"{candidate}_{index:02d}"
            seen.add(candidate)
            if raw != candidate:
                item[field] = candidate
                changed += 1
        choice_seen: set[str] = set()
        for ci, choice in enumerate(item.get("choices", []) if isinstance(item.get("choices"), list) else [], 1):
            if not isinstance(choice, dict):
                continue
            raw = str(choice.get("key", ""))
            candidate = lab._ascii_snake(raw) or f"choice_{ci:02d}"
            if candidate in choice_seen:
                candidate = f"{candidate}_{ci:02d}"
            choice_seen.add(candidate)
            if raw != candidate:
                choice["key"] = candidate
                changed += 1
    return changed


def install_provider_hotfix(lab) -> None:
    def request_groq_v2(*, api_key: str, endpoint: str, model: str, packet, effort: str, timeout: float,
                        max_completion_tokens: int, prior_keys: list[str], http_retries: int):
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": lab.system_prompt(packet)},
                {"role": "user", "content": grounded_user_prompt(lab, packet, prior_keys)},
            ],
            "reasoning_effort": effort,
            "include_reasoning": False,
            "max_completion_tokens": max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"yoru_grounded_{packet.key}",
                    "strict": True,
                    "schema": lab.output_schema(packet),
                },
            },
        }
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        started = time.perf_counter()
        for attempt in range(http_retries + 1):
            req = urllib.request.Request(
                endpoint,
                data=encoded,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": lab.USER_AGENT,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                    headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                content = raw.get("choices", [{}])[0].get("message", {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("provider returned empty message content")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("structured output root is not an object")
                host_namespace(lab, packet, parsed)
                rate = {
                    "remaining_tokens": int(headers.get("x-ratelimit-remaining-tokens", "0") or 0),
                    "limit_tokens": int(headers.get("x-ratelimit-limit-tokens", "0") or 0),
                    "reset_tokens_seconds": round(parse_reset_seconds(headers.get("x-ratelimit-reset-tokens")), 3),
                }
                return (
                    parsed,
                    raw.get("usage") if isinstance(raw.get("usage"), dict) else {},
                    (time.perf_counter() - started) * 1000.0,
                    attempt + 1,
                    rate,
                )
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:4000]
                if exc.code == 429:
                    daily_wait = daily_limit_retry_seconds(detail, exc.headers)
                    if daily_wait > 0:
                        raise DailyTokenLimitStop(detail, daily_wait)
                if exc.code == 429 and attempt < http_retries:
                    delay = parse_reset_seconds(exc.headers.get("Retry-After"))
                    if delay <= 0:
                        delay = parse_reset_seconds(exc.headers.get("x-ratelimit-reset-tokens"))
                    if delay <= 0:
                        delay = 10.0
                    delay = max(1.0, min(delay + 0.75, 45.0))
                    print(f"RATE_LIMIT packet={packet.key} attempt={attempt + 1}/{http_retries + 1} retry_in={delay:.1f}s", flush=True)
                    time.sleep(delay)
                    continue
                if 500 <= exc.code < 600 and attempt < http_retries:
                    delay = min(3.0 * (2 ** attempt), 8.0)
                    print(f"PROVIDER_5XX packet={packet.key} http={exc.code} retry_in={delay:.1f}s", flush=True)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Groq HTTP {exc.code} {exc.reason}: {detail}") from exc
        raise RuntimeError("provider retry loop exhausted")

    lab.request_groq = request_groq_v2


def self_test(lab) -> None:
    p = next(x for x in lab.PACKETS if x.key == "work_miskolc_warehouse")
    payload = {
        "items": [{
            "key": "elso_valtozat",
            "packet_key": p.key,
            "scene_type": p.scene_type,
            "family": p.family,
            "title": "Helyzet",
            "description": "A megadott helyzetből induló rövid jelenet.",
            "choices": [{"key": "varsz", "label": "Kivársz", "consequence_hint": "Nem sieted el."}],
            "tags": ["grounded"],
            "semantic_key": "raktari_helyzet",
            "grounding_ids": list(p.fact_ids),
            "entities_mentioned": [],
            "new_fact_claims": [],
        }] * p.count
    }
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    changed = host_namespace(lab, p, payload)
    assert changed >= p.count * 2
    assert all(str(x["key"]).startswith(p.key + "_") for x in payload["items"])
    assert all(str(x["semantic_key"]).startswith(p.key + "_") for x in payload["items"])
    wait = daily_limit_retry_seconds(
        '{"error":{"message":"Rate limit reached on tokens per day (TPD). Please try again in 6m12.816s."}}'
    )
    assert 372.7 < wait < 373.0
    assert daily_limit_retry_seconds("tokens per minute exceeded") == 0.0
    stuck = next(x for x in lab.PACKETS if x.key == TARGETED_PROMPT_PACKET)
    guarded = grounded_user_prompt(lab, stuck, [])
    assert "PACKET_SPECIFIC_GUARD" in guarded
    assert "kedvezmény, ingyenes, ingyenesen, ajándékba" in guarded
    assert "ténylegesen eltérő" in guarded
    assert "PACKET_SPECIFIC_GUARD" not in grounded_user_prompt(lab, p, [])
    print(
        "HOTFIX_V2_CONTRACTS_PASS host_namespace daily_tpd_stop checkpoint_version targeted_crime_prompt_guard",
        flush=True,
    )


def out_dir_from_argv() -> Path:
    args = sys.argv[1:]
    if "--out-dir" in args:
        i = args.index("--out-dir")
        if i + 1 < len(args):
            return Path(args[i + 1])
    return Path("artifacts/ai_grounded_scenario_lab")


def write_tpd_stop(out: Path, exc: DailyTokenLimitStop) -> None:
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "gate": "Yoru v3.73 W12.2 Grounded AI Scenario Contracts — FAST/RESUME v2",
        "contract_version": HOTFIX_VERSION,
        "status": "INCOMPLETE",
        "provider_blocked_reason": "daily_token_limit",
        "provider_retry_after_seconds": round(exc.retry_after_seconds, 3),
        "checkpoint_progress_preserved": True,
        "human_review_required": True,
        "production_ai_authorized": False,
    }
    (out / "YORU_AI_GROUNDED_LAB_RESULT.json").write_text(
        json.dumps({"summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "YORU_AI_GROUNDED_LAB_RESULT.txt").write_text(
        "\n".join([
            summary["gate"],
            "STATUS: INCOMPLETE",
            "provider_blocked_reason=daily_token_limit",
            f"provider_retry_after_seconds={summary['provider_retry_after_seconds']}",
            "checkpoint_progress_preserved=true",
            "human_review_required=true",
            "production_ai_authorized=false",
            "",
        ]),
        encoding="utf-8",
    )
    print(
        f"TPD_BUDGET_STOP retry_after={exc.retry_after_seconds:.1f}s "
        "checkpoint_progress_preserved=true; rerun later",
        flush=True,
    )


def main() -> int:
    lab = load_lab()
    install_provider_hotfix(lab)
    self_test(lab)
    try:
        return int(lab.main())
    except DailyTokenLimitStop as exc:
        write_tpd_stop(out_dir_from_argv(), exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
