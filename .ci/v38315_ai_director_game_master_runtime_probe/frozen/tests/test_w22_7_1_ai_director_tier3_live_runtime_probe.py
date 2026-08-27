from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.ai_director_game_master_runtime_probe import (
    EXPECTED_FAMILIES,
    evaluate_runtime_probe,
    run_live_runtime_probe,
)
from app.services.ai_director_game_master import AIDirectorGameMaster

TEST_GUILD = 9001001
WRONG_GUILD = 9001002


class Provider:
    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = 0

    async def generate_game_master(self, packet):
        self.calls += 1
        if self.mode == "error":
            raise RuntimeError("offline")
        if self.mode == "invalid":
            return {"title": "Jutalom", "description": "100 Ft biztos jutalom."}
        return {"title": packet.fallback_title, "description": packet.fallback_description}


class Embed:
    def __init__(self):
        self.fields = [("HOST", "canonical", False)]

    def add_field(self, *, name, value, inline):
        self.fields.append((name, value, inline))


def factory(_family: str, _pass_index: int):
    return Embed()


def test_live_probe_go_has_exact_provider_and_cache_shape():
    provider = Provider()
    gm = AIDirectorGameMaster(provider=provider, enabled=True, test_guild_id=TEST_GUILD, cache_ttl_seconds=300)
    report, previews = asyncio.run(run_live_runtime_probe(SimpleNamespace(ai_director_game_master=gm), TEST_GUILD, embed_factory=factory))
    assert report.status == "GO"
    assert provider.calls == 6
    assert len(previews) == 6
    assert report.metrics["requests_total"] == 12
    assert report.metrics["provider_attempts"] == 6
    assert report.metrics["ai_surfaces"] == 6
    assert report.metrics["cache_hits"] == 6
    assert report.metrics["fields_added"] == 12
    assert set(report.metrics["family_requests"]) == EXPECTED_FAMILIES


def test_live_probe_wrong_guild_holds_and_never_calls_provider():
    provider = Provider()
    gm = AIDirectorGameMaster(provider=provider, enabled=True, test_guild_id=TEST_GUILD)
    report, previews = asyncio.run(run_live_runtime_probe(SimpleNamespace(ai_director_game_master=gm), WRONG_GUILD, embed_factory=factory))
    assert report.status == "HOLD"
    assert provider.calls == 0
    assert previews == []


def test_live_probe_provider_error_holds_but_falls_back_safely():
    gm = AIDirectorGameMaster(provider=Provider("error"), enabled=True, test_guild_id=TEST_GUILD)
    report, previews = asyncio.run(run_live_runtime_probe(SimpleNamespace(ai_director_game_master=gm), TEST_GUILD, embed_factory=factory))
    assert report.status == "HOLD"
    assert len(previews) == 6
    assert report.metrics["provider_failures"] == 12
    assert report.metrics["deterministic_fallbacks"] == 12
    assert report.metrics["fields_added"] == 12
    assert report.metrics["integration_failures"] == 0


def test_live_probe_invalid_output_holds_and_records_validation():
    gm = AIDirectorGameMaster(provider=Provider("invalid"), enabled=True, test_guild_id=TEST_GUILD)
    report, _ = asyncio.run(run_live_runtime_probe(SimpleNamespace(ai_director_game_master=gm), TEST_GUILD, embed_factory=factory))
    assert report.status == "HOLD"
    assert report.metrics["output_validation_failures"] == 12
    assert report.metrics["deterministic_fallbacks"] == 12


def test_probe_evidence_contains_no_identifiers_or_provider_text():
    metrics = {
        "requests_total": 12, "inactive_skips": 0, "packet_rejections": 0,
        "provider_unavailable": 0, "provider_attempts": 6, "provider_failures": 0,
        "provider_timeouts": 0, "output_validation_failures": 0, "ai_surfaces": 6,
        "cache_hits": 6, "deterministic_fallbacks": 0, "fields_added": 12,
        "presentation_skips": 0, "integration_failures": 0,
        "family_requests": {family: 2 for family in EXPECTED_FAMILIES},
    }
    payload = evaluate_runtime_probe(metrics, policy_active=True, host_panels_intact=True).as_dict()
    text = str(payload).casefold()
    for forbidden in ("guild_id", "user_id", "packet_digest", "provider_text", "prompt"):
        assert forbidden not in text


def test_reset_observation_can_clear_cache_for_deterministic_probe():
    provider = Provider()
    gm = AIDirectorGameMaster(provider=provider, enabled=True, test_guild_id=TEST_GUILD)
    asyncio.run(run_live_runtime_probe(SimpleNamespace(ai_director_game_master=gm), TEST_GUILD, embed_factory=factory))
    assert gm._cache
    gm.reset_observation(clear_cache=True)
    assert gm._cache == {}
    assert gm.observation_snapshot().requests_total == 0


def test_admin_command_is_owner_only_and_ephemeral_by_contract():
    source = open("app/cogs/admin.py", encoding="utf-8").read()
    assert 'name="gmpilotprobe"' in source
    assert "await self.bot.is_owner(interaction.user)" in source
    assert "pilot.active_for_guild(interaction.guild.id)" in source
    assert "ephemeral=True" in source


def test_probe_does_not_reference_database_or_gameplay_mutation():
    source = open("app/ai_director_game_master_runtime_probe.py", encoding="utf-8").read().casefold()
    for forbidden in ("database", "repository", "wallet", "bank", "settlement", "update ", "insert ", "delete "):
        assert forbidden not in source
