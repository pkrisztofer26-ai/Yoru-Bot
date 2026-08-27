from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.ai_director_game_master import AIDirectorGameMasterPacket, big_job_packet
from app.ai_director_game_master_integration import add_game_master_field
from app.services.ai_director_game_master import AIDirectorGameMaster


def run(coro):
    return asyncio.run(coro)


class Provider:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {"title": "A Belvárosi trezor", "description": "A Belvárosi trezor ügy lezárása: Siker."}
        self.error = error
        self.calls = 0

    async def generate_game_master(self, packet):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.payload)


class Embed:
    def __init__(self, explode=False):
        self.fields = [("HOST", "canonical", False)]
        self.explode = explode

    def add_field(self, *, name, value, inline):
        if self.explode:
            raise RuntimeError("attach failed")
        self.fields.append((name, value, inline))


def packet():
    return big_job_packet(
        target_name="Belvárosi trezor", phase_label="Lezárt ügy", approach_label="Csendes út",
        route_label="Eredeti útvonal", host_resolution="Siker",
        consequence_note="A csapat az eredeti útvonalon maradt.",
    )


def test_version_is_v38314():
    assert Path("VERSION").read_text(encoding="utf-8").strip() == "3.83.14"


def test_observation_snapshot_starts_zero_and_contains_no_ids():
    gm = AIDirectorGameMaster(enabled=False, test_guild_id=10)
    data = gm.observation_snapshot().as_dict()
    assert all(value == 0 for key, value in data.items() if key != "family_requests")
    assert data["family_requests"] == {}
    assert not any("guild" in key or "user" in key or "digest" in key for key in data)


def test_disabled_request_is_observed_without_provider_call():
    p = Provider(); gm = AIDirectorGameMaster(provider=p, enabled=False, test_guild_id=10)
    assert run(gm.surface(10, packet())) is None
    snap = gm.observation_snapshot()
    assert snap.requests_total == 1 and snap.inactive_skips == 1 and snap.provider_attempts == 0 and p.calls == 0


def test_wrong_guild_is_observed_without_provider_call():
    p = Provider(); gm = AIDirectorGameMaster(provider=p, enabled=True, test_guild_id=10)
    assert run(gm.surface(11, packet())) is None
    snap = gm.observation_snapshot()
    assert snap.inactive_skips == 1 and snap.provider_attempts == 0 and p.calls == 0


def test_missing_provider_counts_safe_fallback():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    result = run(gm.surface(10, packet()))
    snap = gm.observation_snapshot()
    assert result.source == "deterministic_scenario_v2_fallback"
    assert snap.provider_unavailable == 1 and snap.deterministic_fallbacks == 1


def test_valid_provider_counts_ai_surface():
    p = Provider(); gm = AIDirectorGameMaster(provider=p, enabled=True, test_guild_id=10)
    result = run(gm.surface(10, packet()))
    snap = gm.observation_snapshot()
    assert result.source == "ai_game_master"
    assert snap.provider_attempts == 1 and snap.ai_surfaces == 1 and snap.deterministic_fallbacks == 0


def test_cache_hit_is_observed_and_skips_second_provider_call():
    p = Provider(); gm = AIDirectorGameMaster(provider=p, enabled=True, test_guild_id=10, cache_ttl_seconds=300)
    run(gm.surface(10, packet())); second = run(gm.surface(10, packet()))
    snap = gm.observation_snapshot()
    assert second.source == "ai_game_master_cache"
    assert p.calls == 1 and snap.cache_hits == 1 and snap.requests_total == 2


def test_invalid_provider_surface_counts_validation_fallback():
    p = Provider(payload={"title": "Jutalom", "description": "100 Ft biztos jutalom."})
    gm = AIDirectorGameMaster(provider=p, enabled=True, test_guild_id=10)
    result = run(gm.surface(10, packet()))
    snap = gm.observation_snapshot()
    assert result.source == "deterministic_scenario_v2_fallback"
    assert snap.output_validation_failures == 1 and snap.deterministic_fallbacks == 1


def test_provider_exception_counts_provider_failure_fallback():
    gm = AIDirectorGameMaster(provider=Provider(error=RuntimeError("offline")), enabled=True, test_guild_id=10)
    result = run(gm.surface(10, packet()))
    snap = gm.observation_snapshot()
    assert result.source == "deterministic_scenario_v2_fallback"
    assert snap.provider_failures == 1 and snap.deterministic_fallbacks == 1


def test_timeout_counts_timeout_fallback_separately():
    gm = AIDirectorGameMaster(provider=Provider(error=asyncio.TimeoutError()), enabled=True, test_guild_id=10)
    result = run(gm.surface(10, packet()))
    snap = gm.observation_snapshot()
    assert result.source == "deterministic_scenario_v2_fallback"
    assert snap.provider_timeouts == 1 and snap.provider_failures == 0 and snap.deterministic_fallbacks == 1


def test_packet_rejection_is_observed_and_still_raises_to_integration_boundary():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    invalid = AIDirectorGameMasterPacket(
        story_key="big_job.invalid", family="big_job", semantic_slot="invalid",
        fallback_title="Hibás", fallback_description="Hibás packet.",
        facts={"target_name": "Trezor 2"}, required_terms=(), tags=(),
    )
    try:
        run(gm.surface(10, invalid))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid packet must be rejected")
    assert gm.observation_snapshot().packet_rejections == 1


def test_integration_records_added_field():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    embed = Embed(); bot = SimpleNamespace(ai_director_game_master=gm)
    assert run(add_game_master_field(bot, embed, 10, packet)) is True
    snap = gm.observation_snapshot()
    assert snap.fields_added == 1 and snap.presentation_skips == 0 and embed.fields[0][0] == "HOST"


def test_integration_records_wrong_guild_skip():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    embed = Embed(); bot = SimpleNamespace(ai_director_game_master=gm)
    assert run(add_game_master_field(bot, embed, 11, packet)) is False
    snap = gm.observation_snapshot()
    assert snap.presentation_skips == 1 and snap.fields_added == 0 and embed.fields == [("HOST", "canonical", False)]


def test_packet_factory_failure_cannot_break_host_panel():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    embed = Embed(); bot = SimpleNamespace(ai_director_game_master=gm)
    def bad():
        return big_job_packet(target_name="Trezor 2", phase_label="Lezárt ügy", approach_label="Csendes út", route_label="Eredeti útvonal", host_resolution="Siker", consequence_note="Lezárt ügy.")
    assert run(add_game_master_field(bot, embed, 10, bad)) is False
    snap = gm.observation_snapshot()
    assert snap.integration_failures == 1 and snap.presentation_skips == 1
    assert embed.fields == [("HOST", "canonical", False)]


def test_embed_attach_failure_is_now_fail_closed():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    embed = Embed(explode=True); bot = SimpleNamespace(ai_director_game_master=gm)
    assert run(add_game_master_field(bot, embed, 10, packet)) is False
    snap = gm.observation_snapshot()
    assert snap.integration_failures == 1 and snap.presentation_skips == 1 and snap.fields_added == 0
    assert embed.fields == [("HOST", "canonical", False)]


def test_observation_reset_clears_counters_only():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    run(gm.surface(10, packet()))
    gm.reset_observation()
    snap = gm.observation_snapshot()
    assert snap.requests_total == 0 and snap.deterministic_fallbacks == 0 and snap.family_requests == ()


def test_family_request_counter_is_semantic_only():
    gm = AIDirectorGameMaster(provider=None, enabled=True, test_guild_id=10)
    run(gm.surface(10, packet()))
    assert gm.observation_snapshot().family_requests == (("big_job", 1),)


def test_observation_service_has_no_persistence_dependency():
    text = Path("app/services/ai_director_game_master.py").read_text(encoding="utf-8")
    for forbidden in ("sqlite3", "mariadb", "app.repositories", "INSERT INTO", "UPDATE ai_", "DELETE FROM"):
        assert forbidden not in text


def test_observation_integration_keeps_attach_inside_try_boundary():
    text = Path("app/ai_director_game_master_integration.py").read_text(encoding="utf-8")
    try_pos = text.index("try:")
    add_pos = text.index("embed.add_field")
    except_pos = text.index("except Exception", try_pos)
    assert try_pos < add_pos < except_pos


def test_storyteller_pacing_stays_locked():
    combined = (Path("app/services/ai_director_game_master.py").read_text(encoding="utf-8") + Path("app/ai_director_game_master_integration.py").read_text(encoding="utf-8")).casefold()
    assert "storyteller_pacing" not in combined and "storyteller pacing" not in combined


def test_provider_contract_is_unchanged_in_w227():
    text = Path("app/ai_director_game_master.py").read_text(encoding="utf-8")
    assert 'GAME_MASTER_CONTRACT_VERSION = "tier3-game-master-surface-v6"' in text


def test_no_new_player_facing_callsite_is_added_by_observation_module():
    text = Path("scripts/ai_director_tier3_pilot_observation.py").read_text(encoding="utf-8")
    assert "discord" not in text.casefold()
    assert "bot.run" not in text


def test_observation_script_is_synthetic_and_marks_live_unchanged():
    text = Path("scripts/ai_director_tier3_pilot_observation.py").read_text(encoding="utf-8")
    assert '"synthetic_test_guild_observation"' in text
    assert '"UNCHANGED"' in text


def test_observation_does_not_add_native_db_requirement():
    text = Path("scripts/ai_director_tier3_pilot_observation.py").read_text(encoding="utf-8")
    assert "mariadb" not in text.casefold() and "sqlite" not in text.casefold()
