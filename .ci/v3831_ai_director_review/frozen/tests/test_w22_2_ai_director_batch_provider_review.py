from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.ai_director import AIDirectorPacket, AIDirectorSurface
from app.ai_director_review import build_review_artifact, review_surface_quality_errors
from app.ai_director_tier1 import TIER1_REVIEW_PACKETS
from app.providers.ai_director_groq import (
    AIDirectorDailyTokenLimit,
    GroqAIDirectorProvider,
    _daily_limit_retry_seconds,
    _parse_reset_seconds,
)


def provider() -> GroqAIDirectorProvider:
    return GroqAIDirectorProvider("test-key")


def first_packet() -> AIDirectorPacket:
    return TIER1_REVIEW_PACKETS[0]


def ai_surface(packet: AIDirectorPacket, *, title: str | None = None, description: str | None = None) -> AIDirectorSurface:
    return AIDirectorSurface(
        content_key=packet.content_key,
        family=packet.family,
        title=title or packet.fallback_title,
        description=description or packet.fallback_description,
        source="ai_cached",
        packet_digest=packet.digest(),
        contract_version=packet.contract_version,
    )


def test_provider_uses_https_and_go_model_default():
    item = provider()
    assert item.endpoint.startswith("https://")
    assert item.model == "openai/gpt-oss-120b"
    assert item.reasoning_effort == "low"


def test_provider_rejects_missing_key_and_plain_http():
    with pytest.raises(ValueError):
        GroqAIDirectorProvider("")
    with pytest.raises(ValueError):
        GroqAIDirectorProvider("x", endpoint="http://example.test")


def test_provider_schema_is_strict_title_description_only():
    schema = provider().output_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"title", "description"}
    assert set(schema["required"]) == {"title", "description"}


def test_provider_request_is_seed_guided_and_host_grounded():
    item = provider()
    packet = first_packet()
    body = item.request_body(packet)
    assert body["response_format"]["type"] == "json_schema"
    prompt = body["messages"][1]["content"]
    assert packet.fallback_title in prompt
    assert packet.fallback_description in prompt
    assert "HOST_FACTS" in prompt
    for value in packet.facts.values():
        assert str(value) in prompt


def test_system_prompt_explicitly_denies_mechanical_authority():
    text = provider().system_prompt().casefold()
    for marker in ("pénzről", "jutalomról", "esélyről", "inventoryról", "settlementről", "player choice"):
        assert marker in text


def test_api_key_is_not_written_into_request_body():
    item = GroqAIDirectorProvider("secret-test-value")
    serialized = json.dumps(item.request_body(first_packet()), ensure_ascii=False)
    assert "secret-test-value" not in serialized


def test_rate_limit_parser_keeps_old_w12_3_tpd_behavior():
    assert 372.7 < _parse_reset_seconds("6m12.816s") < 373.0
    wait = _daily_limit_retry_seconds(
        '{"error":{"message":"Rate limit reached on tokens per day (TPD). Please try again in 6m12.816s."}}'
    )
    assert 372.7 < wait < 373.0
    assert _daily_limit_retry_seconds("tokens per minute exceeded") == 0.0


def test_review_artifact_all_validated_is_pending_human_not_go():
    packets = TIER1_REVIEW_PACKETS
    artifact = build_review_artifact(packets, tuple(ai_surface(packet) for packet in packets))
    assert artifact.total == 15
    assert artifact.ai_validated == 15
    assert artifact.deterministic_fallbacks == 0
    assert artifact.status == "PENDING_HUMAN"
    assert artifact.human_review_required is True
    assert artifact.player_facing_ai is False
    assert artifact.production_runtime_enabled is False


def test_review_artifact_has_all_roadmap_families():
    artifact = build_review_artifact(
        TIER1_REVIEW_PACKETS,
        tuple(ai_surface(packet) for packet in TIER1_REVIEW_PACKETS),
    )
    assert {row.family for row in artifact.rows} == {"work", "crime", "search", "beg", "career"}


def test_review_artifact_fallback_forces_automated_hold():
    packets = TIER1_REVIEW_PACKETS[:2]
    good = ai_surface(packets[0])
    fallback = AIDirectorSurface(
        content_key=packets[1].content_key,
        family=packets[1].family,
        title=packets[1].fallback_title,
        description=packets[1].fallback_description,
        source="deterministic_fallback",
        packet_digest=packets[1].digest(),
        contract_version=packets[1].contract_version,
    )
    artifact = build_review_artifact(packets, (good, fallback))
    assert artifact.status == "AUTOMATED_HOLD"
    assert artifact.ai_validated == 1
    assert artifact.deterministic_fallbacks == 1
    assert artifact.rows[1].cache_seed_eligible is False


def test_review_artifact_duplicate_ai_surface_is_held_and_not_seed_eligible():
    one, two = TIER1_REVIEW_PACKETS[:2]
    title = "Azonos cím"
    description = "A raktár azonos review szöveget kap."
    artifact = build_review_artifact(
        (one, two),
        (ai_surface(one, title=title, description=description), ai_surface(two, title=title, description=description)),
    )
    assert artifact.status == "AUTOMATED_HOLD"
    assert artifact.exact_duplicate_groups == 1
    assert all(row.automated_status == "DUPLICATE_HOLD" for row in artifact.rows)
    assert not any(row.cache_seed_eligible for row in artifact.rows)


def test_review_identity_mismatch_is_rejected():
    packet = first_packet()
    surface = ai_surface(packet)
    broken = AIDirectorSurface(
        content_key="work_other",
        family=surface.family,
        title=surface.title,
        description=surface.description,
        source=surface.source,
        packet_digest=surface.packet_digest,
        contract_version=surface.contract_version,
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        build_review_artifact((packet,), (broken,))


def test_review_json_and_csv_are_human_review_ready():
    packet = first_packet()
    artifact = build_review_artifact((packet,), (ai_surface(packet),))
    payload = json.loads(artifact.to_json())
    assert payload["status"] == "PENDING_HUMAN"
    csv_text = artifact.to_csv()
    for column in ("human_groundedness", "human_hungarian", "human_yoru_tone", "human_new_fact", "human_decision", "human_notes"):
        assert column in csv_text


def test_fixture_review_script_generates_non_player_artifact(tmp_path):
    from scripts.ai_director_tier1_review import main_async

    class Args:
        mode = "fixture"
        output = str(tmp_path)
        model = "openai/gpt-oss-120b"
        reasoning_effort = "low"
        timeout = 5.0

    assert asyncio.run(main_async(Args())) == 0
    result = json.loads((tmp_path / "YORU_AI_DIRECTOR_TIER1_REVIEW_RESULT.json").read_text(encoding="utf-8"))
    assert result["total"] == 15
    assert result["status"] == "PENDING_HUMAN"
    assert result["player_facing_ai"] is False
    assert (tmp_path / "YORU_AI_DIRECTOR_TIER1_HUMAN_REVIEW.csv").is_file()


def test_live_review_script_requires_secret_without_leaking(tmp_path, monkeypatch):
    from scripts.ai_director_tier1_review import main_async

    class Args:
        mode = "live"
        output = str(tmp_path)
        model = "openai/gpt-oss-120b"
        reasoning_effort = "low"
        timeout = 5.0

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GROQ_API_KEY"):
        asyncio.run(main_async(Args()))


def test_production_runtime_still_has_no_provider_and_is_disabled():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "provider=None, runtime_enabled=False" in source
    assert "GroqAIDirectorProvider" not in source
    assert "GROQ_API_KEY" not in source


def test_review_pipeline_has_no_wallet_inventory_or_settlement_dependency():
    source = (
        Path("app/providers/ai_director_groq.py").read_text(encoding="utf-8")
        + Path("app/ai_director_review.py").read_text(encoding="utf-8")
        + Path("scripts/ai_director_tier1_review.py").read_text(encoding="utf-8")
    )
    forbidden_imports = ("services.economy", "services.assets", "services.contracts", "services.heist", "repositories.wallet")
    assert not any(item in source for item in forbidden_imports)


def test_contract_version_bumped_for_review_pipeline():
    assert first_packet().contract_version == "tier1-cached-surface-v3"


def test_review_generate_fails_closed_to_fallback_on_provider_error():
    from scripts import ai_director_tier1_review as review_script
    from app.providers.ai_director_groq import AIDirectorProviderError

    class BrokenProvider:
        async def generate_surface(self, packet):
            raise AIDirectorProviderError("boom")

    surfaces = asyncio.run(review_script.generate(BrokenProvider()))
    assert len(surfaces) == 15
    assert all(surface.source == "deterministic_fallback" for surface in surfaces)
    artifact = build_review_artifact(TIER1_REVIEW_PACKETS, surfaces)
    assert artifact.status == "AUTOMATED_HOLD"
    assert artifact.deterministic_fallbacks == 15


def test_review_generate_fails_closed_to_fallback_on_validation_error():
    from scripts import ai_director_tier1_review as review_script

    class InvalidProvider:
        async def generate_surface(self, packet):
            return {"title": "Hiányos", "description": "Nincs benne a kötelező host anchor."}

    surfaces = asyncio.run(review_script.generate(InvalidProvider()))
    assert len(surfaces) == 15
    assert all(surface.source == "deterministic_fallback" for surface in surfaces)


def test_provider_prompt_preserves_natural_hungarian_case_forms():
    prompt = provider().user_prompt(next(p for p in TIER1_REVIEW_PACKETS if p.content_key == "beg_square_crowd"))
    assert "esetragjait" in prompt
    assert "téren" in prompt
    assert "térben" in prompt


def test_human_qa_guard_rejects_reviewed_square_locative_regression():
    packet = next(p for p in TIER1_REVIEW_PACKETS if p.content_key == "beg_square_crowd")
    assert review_surface_quality_errors(
        packet,
        "Mozgalmasabb lett a tér",
        "A térben a járókelők mozgása változik.",
    ) == ("unnatural_square_locative",)
    assert review_surface_quality_errors(
        packet,
        packet.fallback_title,
        packet.fallback_description,
    ) == ()


def test_review_generate_fails_closed_on_human_qa_surface_regression():
    from scripts import ai_director_tier1_review as review_script

    class RegressionProvider:
        async def generate_surface(self, packet):
            if packet.content_key == "beg_square_crowd":
                return {
                    "title": "Mozgalmasabb lett a tér",
                    "description": "A térben a járókelők mozgása változik, de a reakcióik előre nem láthatóak.",
                }
            return {"title": packet.fallback_title, "description": packet.fallback_description}

    surfaces = asyncio.run(review_script.generate(RegressionProvider()))
    square = next(surface for surface in surfaces if surface.content_key == "beg_square_crowd")
    assert square.source == "deterministic_fallback"
    artifact = build_review_artifact(TIER1_REVIEW_PACKETS, surfaces)
    assert artifact.status == "AUTOMATED_HOLD"
