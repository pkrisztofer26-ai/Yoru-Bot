from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from app.ai_director import AIDirectorPacket


class AIDirectorProviderError(RuntimeError):
    pass


class AIDirectorDailyTokenLimit(AIDirectorProviderError):
    def __init__(self, detail: str, retry_after_seconds: float) -> None:
        super().__init__(detail)
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))


@dataclass(frozen=True, slots=True)
class GroqProviderUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    elapsed_ms: float = 0.0
    attempts: int = 0


def _parse_reset_seconds(value: str | None) -> float:
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


def _daily_limit_retry_seconds(detail: str, headers: Any = None) -> float:
    low = str(detail or "").lower()
    if "tokens per day" not in low and "(tpd)" not in low and " tpd" not in low:
        return 0.0
    waits: list[float] = []
    match = re.search(r"try again in\s+([0-9.]+(?:ms|s|m|h)(?:[0-9.]+(?:ms|s|m|h))*)", low)
    if match:
        waits.append(_parse_reset_seconds(match.group(1)))
    if headers is not None:
        for key in ("Retry-After", "x-ratelimit-reset-tokens"):
            try:
                waits.append(_parse_reset_seconds(headers.get(key)))
            except Exception:
                pass
    return max((value for value in waits if value > 0), default=1.0)


class GroqAIDirectorProvider:
    """Review/batch-only Groq adapter for Phase 12 Tier 1.

    It is intentionally a seed-guided paraphraser. The host supplies facts,
    fallback wording and anchors; the model may return only title/description.
    Runtime wiring remains a separate feature gate.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.groq.com/openai/v1/chat/completions",
        model: str = "openai/gpt-oss-120b",
        reasoning_effort: str = "low",
        timeout: float = 45.0,
        http_retries: int = 1,
        max_completion_tokens: int = 320,
    ) -> None:
        if not str(api_key or "").strip():
            raise ValueError("Hiányzó Groq API key.")
        if not str(endpoint).startswith("https://"):
            raise ValueError("Az AI provider endpointnek HTTPS-nek kell lennie.")
        self.api_key = str(api_key).strip()
        self.endpoint = str(endpoint)
        self.model = str(model)
        self.reasoning_effort = str(reasoning_effort)
        self.timeout = max(5.0, float(timeout))
        self.http_retries = max(0, min(3, int(http_retries)))
        self.max_completion_tokens = max(120, min(700, int(max_completion_tokens)))
        self.last_usage = GroqProviderUsage()

    @staticmethod
    def system_prompt() -> str:
        return (
            "Te a Yoru AI Director szigorúan korlátozott magyar surface-paraphraser rétege vagy. "
            "A host által megadott tényeket nem bővítheted, nem következtethetsz új eseményre, szereplőre, "
            "eredményre vagy mechanikára. Nem dönthetsz pénzről, jutalomról, esélyről, siker/bukásról, "
            "inventoryról, cooldownról, XP-ről, rendőrségi hatásról, settlementről vagy player choice-ról. "
            "Kizárólag természetes, idiomatikus magyar title és egy rövid description mezőt adj vissza. "
            "A GOLDEN SEED természetes magyar esetragjait és helyhatározói alakjait ne rontsd el."
        )

    @staticmethod
    def user_prompt(packet: AIDirectorPacket) -> str:
        facts = "\n".join(f"- {key}: {value}" for key, value in sorted(packet.facts.items())) or "- nincs extra fact"
        anchors = ", ".join(packet.required_terms) or "nincs"
        return (
            f"CONTENT_KEY: {packet.content_key}\n"
            f"FAMILY: {packet.family}\n"
            f"SEMANTIC_SLOT: {packet.semantic_slot}\n"
            f"HOST_FACTS:\n{facts}\n"
            f"KÖTELEZŐ ANCHOROK: {anchors}\n\n"
            "GOLDEN SEED / determinisztikus fallback, amelynek a jelentését meg kell tartani:\n"
            f"TITLE: {packet.fallback_title}\n"
            f"DESCRIPTION: {packet.fallback_description}\n\n"
            "Feladat: fogalmazd át természetes, rövid magyar szövegre. Ne adj hozzá új tényt. "
            "Őrizd meg a GOLDEN SEED természetes magyar esetragjait; a helymegjelölést ne cseréld "
            "nyelvileg idegen alakra (például a közterületi téren alakot ne írd át térben alakra). "
            "Ne írj számot, konkrét jutalmat, esélyt, utasítást vagy új szereplőt, ha nincs a host factekben."
        )

    @staticmethod
    def output_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 120},
                "description": {"type": "string", "minLength": 1, "maxLength": 700},
            },
            "required": ["title", "description"],
        }

    def request_body(self, packet: AIDirectorPacket) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": self.user_prompt(packet)},
            ],
            "reasoning_effort": self.reasoning_effort,
            "include_reasoning": False,
            "temperature": 0.2,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "yoru_ai_director_tier1_surface",
                    "strict": True,
                    "schema": self.output_schema(),
                },
            },
        }

    async def generate_surface(self, packet: AIDirectorPacket) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request, packet)

    def _request(self, packet: AIDirectorPacket) -> Mapping[str, Any]:
        encoded = json.dumps(self.request_body(packet), ensure_ascii=False).encode("utf-8")
        started = time.perf_counter()
        for attempt in range(self.http_retries + 1):
            request = urllib.request.Request(
                self.endpoint,
                data=encoded,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Yoru-AI-Director-W22.2.1/1.0",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                content = raw.get("choices", [{}])[0].get("message", {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise AIDirectorProviderError("A provider üres structured contentet adott.")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise AIDirectorProviderError("A provider structured output gyökere nem objektum.")
                usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
                self.last_usage = GroqProviderUsage(
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or 0),
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    attempts=attempt + 1,
                )
                return parsed
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:4000]
                if exc.code == 429:
                    daily_wait = _daily_limit_retry_seconds(detail, exc.headers)
                    if daily_wait > 0:
                        raise AIDirectorDailyTokenLimit(detail, daily_wait) from exc
                if exc.code == 429 and attempt < self.http_retries:
                    delay = _parse_reset_seconds(exc.headers.get("Retry-After")) or 2.0
                    time.sleep(max(1.0, min(delay + 0.5, 10.0)))
                    continue
                if 500 <= exc.code < 600 and attempt < self.http_retries:
                    time.sleep(min(2.0 * (2 ** attempt), 5.0))
                    continue
                raise AIDirectorProviderError(f"Groq HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.http_retries:
                    time.sleep(min(1.5 * (2 ** attempt), 4.0))
                    continue
                raise AIDirectorProviderError(type(exc).__name__) from exc
        raise AIDirectorProviderError("Provider retry loop exhausted.")
