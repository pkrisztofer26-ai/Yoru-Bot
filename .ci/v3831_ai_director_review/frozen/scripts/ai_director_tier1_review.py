from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.ai_director import (
    AIDirectorSurface,
    AIDirectorValidationError,
    fallback_surface,
    validate_provider_surface,
)
from app.ai_director_review import build_review_artifact, review_surface_quality_errors
from app.ai_director_tier1 import TIER1_REVIEW_PACKETS
from app.providers.ai_director_groq import (
    AIDirectorDailyTokenLimit,
    AIDirectorProviderError,
    GroqAIDirectorProvider,
)


class _FixtureProvider:
    """Offline contract probe; not production content."""
    async def generate_surface(self, packet):
        return {"title": packet.fallback_title, "description": packet.fallback_description}


async def generate(provider) -> tuple[AIDirectorSurface, ...]:
    surfaces: list[AIDirectorSurface] = []
    for packet in TIER1_REVIEW_PACKETS:
        try:
            raw = await provider.generate_surface(packet)
            title, description = validate_provider_surface(packet, raw)
            quality_errors = review_surface_quality_errors(packet, title, description)
            if quality_errors:
                raise AIDirectorValidationError("Human-derived surface guard: " + ",".join(quality_errors))
        except AIDirectorDailyTokenLimit:
            raise
        except (AIDirectorProviderError, AIDirectorValidationError) as exc:
            # Review batches fail closed per packet: never guess or accept a
            # malformed provider surface.  Preserve the deterministic seed,
            # mark the batch AUTOMATED_HOLD through the fallback source and
            # keep player-facing AI disabled.
            print(f"AI_DIRECTOR_REVIEW_FALLBACK content_key={packet.content_key} reason={type(exc).__name__}")
            surfaces.append(fallback_surface(packet))
            continue
        surfaces.append(AIDirectorSurface(
            content_key=packet.content_key,
            family=packet.family,
            title=title,
            description=description,
            source="ai_cached",
            packet_digest=packet.digest(),
            contract_version=packet.contract_version,
        ))
    return tuple(surfaces)


async def main_async(args) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.mode == "live":
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise SystemExit("GROQ_API_KEY hiányzik a live review módhoz.")
        provider = GroqAIDirectorProvider(
            key,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            timeout=args.timeout,
        )
    else:
        provider = _FixtureProvider()

    try:
        surfaces = await generate(provider)
    except AIDirectorDailyTokenLimit as exc:
        result = {
            "status": "INCOMPLETE_PROVIDER_TPD",
            "retry_after_seconds": round(exc.retry_after_seconds, 3),
            "player_facing_ai": False,
            "production_runtime_enabled": False,
            "human_review_required": True,
        }
        (output / "YORU_AI_DIRECTOR_TIER1_REVIEW_RESULT.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 2

    artifact = build_review_artifact(TIER1_REVIEW_PACKETS, surfaces)
    (output / "YORU_AI_DIRECTOR_TIER1_REVIEW_RESULT.json").write_text(artifact.to_json(), encoding="utf-8")
    (output / "YORU_AI_DIRECTOR_TIER1_HUMAN_REVIEW.csv").write_text(artifact.to_csv(), encoding="utf-8-sig")
    summary = [
        "Yoru v3.83.2 W22.2.1 Tier 1 Hungarian Surface Hardening Review",
        f"MODE={args.mode}",
        f"STATUS={artifact.status}",
        f"TOTAL={artifact.total}",
        f"AI_VALIDATED={artifact.ai_validated}",
        f"FALLBACKS={artifact.deterministic_fallbacks}",
        f"DUPLICATE_GROUPS={artifact.exact_duplicate_groups}",
        "PLAYER_FACING_AI=OFF",
        "PRODUCTION_RUNTIME_ENABLED=FALSE",
        "HUMAN_REVIEW_REQUIRED=TRUE",
    ]
    (output / "YORU_AI_DIRECTOR_TIER1_REVIEW_RESULT.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return 0 if artifact.status == "PENDING_HUMAN" else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--output", default="artifacts/ai_director_tier1_review")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
