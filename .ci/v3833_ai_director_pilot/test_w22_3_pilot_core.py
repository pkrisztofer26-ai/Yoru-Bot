from __future__ import annotations

import inspect

from app.ai_director_pilot import (
    AIDirectorPilot,
    AIDirectorPilotPolicy,
    PILOT_FIELD_NAME,
    REVIEWED_TIER1_SURFACES,
    W22_2_1_HUMAN_QA,
    W22_2_1_REVIEW_ARTIFACT_ID,
    W22_2_1_REVIEW_ARTIFACT_SHA256,
    W22_2_1_REVIEW_RUN_ID,
)
from app.ai_director_review import review_surface_quality_errors
from app.ai_director_tier1 import TIER1_REVIEW_PACKETS

TEST_GUILD = 123456789012345678
OTHER_GUILD = 223456789012345678
USER = 323456789012345678


def test_bundle_is_exact_closed_catalog():
    assert len(REVIEWED_TIER1_SURFACES) == 15
    assert set(REVIEWED_TIER1_SURFACES) == {p.content_key for p in TIER1_REVIEW_PACKETS}


def test_bundle_has_three_per_family():
    counts = {}
    for surface in REVIEWED_TIER1_SURFACES.values():
        counts[surface.family] = counts.get(surface.family, 0) + 1
    assert counts == {"work": 3, "crime": 3, "search": 3, "beg": 3, "career": 3}


def test_bundle_source_is_reviewed_not_generated():
    assert {s.source for s in REVIEWED_TIER1_SURFACES.values()} == {"human_reviewed_cache"}
    assert not any(s.ai_generated for s in REVIEWED_TIER1_SURFACES.values())


def test_bundle_digest_matches_host_packets():
    packets = {p.content_key: p for p in TIER1_REVIEW_PACKETS}
    for key, surface in REVIEWED_TIER1_SURFACES.items():
        assert surface.packet_digest == packets[key].digest()
        assert surface.contract_version == packets[key].contract_version


def test_bundle_passes_surface_guards():
    packets = {p.content_key: p for p in TIER1_REVIEW_PACKETS}
    for key, surface in REVIEWED_TIER1_SURFACES.items():
        assert review_surface_quality_errors(packets[key], surface.title, surface.description) == ()


def test_square_regression_is_closed():
    square = REVIEWED_TIER1_SURFACES["beg_square_crowd"]
    assert "A téren" in square.description
    assert "A térben" not in square.description


def test_review_provenance_is_pinned():
    assert W22_2_1_REVIEW_RUN_ID == 32969015798
    assert W22_2_1_REVIEW_ARTIFACT_ID == 9606860343
    assert W22_2_1_REVIEW_ARTIFACT_SHA256 == "fe40bcb859652367dd4d8f8468fbbda0320f8eed12ec78a4b6e0e1b2b3b3fc37"
    assert W22_2_1_HUMAN_QA == "15/15 GO"


def test_policy_default_is_off():
    policy = AIDirectorPilotPolicy()
    assert policy.enabled is False
    assert policy.active_for_guild(TEST_GUILD) is False


def test_enabled_without_test_guild_is_inactive():
    assert AIDirectorPilotPolicy(enabled=True, test_guild_id=None).active_for_guild(TEST_GUILD) is False


def test_policy_never_leaks_to_other_guild():
    policy = AIDirectorPilotPolicy(enabled=True, test_guild_id=TEST_GUILD)
    assert policy.active_for_guild(TEST_GUILD) is True
    assert policy.active_for_guild(OTHER_GUILD) is False


def test_enabled_test_guild_returns_reviewed_surface_only():
    pilot = AIDirectorPilot(enabled=True, test_guild_id=TEST_GUILD)
    surface = pilot.surface(TEST_GUILD, USER, "work")
    assert surface is not None
    assert surface.family == "work"
    assert surface.source == "human_reviewed_cache"
    assert pilot.surface(OTHER_GUILD, USER, "work") is None


def test_selector_is_deterministic():
    pilot = AIDirectorPilot(enabled=True, test_guild_id=TEST_GUILD)
    assert pilot.surface(TEST_GUILD, USER, "crime") == pilot.surface(TEST_GUILD, USER, "crime")


def test_non_tier1_families_are_not_addressable():
    pilot = AIDirectorPilot(enabled=True, test_guild_id=TEST_GUILD)
    for family in ("heist", "asset", "chapter", "world"):
        assert pilot.surface(TEST_GUILD, USER, family) is None


def test_field_is_explicitly_test_marked_and_bounded():
    pilot = AIDirectorPilot(enabled=True, test_guild_id=TEST_GUILD)
    value = pilot.field_value(TEST_GUILD, USER, "search")
    assert PILOT_FIELD_NAME == "🌙 Yoru Director • teszt"
    assert value and "\n" in value and len(value) <= 1024


def test_core_module_has_no_runtime_provider_or_authority_import():
    import app.ai_director_pilot as module
    source = inspect.getsource(module)
    assert "urllib" not in source
    assert "repositories.ai_director" not in source
    assert "services.economy" not in source
    assert "services.assets" not in source
    assert "services.contracts" not in source
    assert "services.heist" not in source
