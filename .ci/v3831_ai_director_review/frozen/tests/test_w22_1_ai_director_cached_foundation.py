from __future__ import annotations

import asyncio
from dataclasses import fields
from pathlib import Path

import pytest

from app.ai_director import (
    AIDirectorPacket,
    AIDirectorSurface,
    AIDirectorValidationError,
    validate_provider_surface,
)
from app.services.ai_director import AIDirectorService


class FakeProvider:
    def __init__(self, response=None, *, error: Exception | None = None) -> None:
        self.response = response or {"title": "Műszakkezdés", "description": "A raktárban indul a műszak."}
        self.error = error
        self.calls = 0

    async def generate_surface(self, packet):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.response)


class FakeRepo:
    def __init__(self) -> None:
        self.items = {}
        self.initialized = False
        self.purged = False

    async def initialize(self):
        self.initialized = True

    async def purge_expired(self):
        self.purged = True
        return 0

    async def get(self, *, content_key, packet_digest, contract_version):
        return self.items.get((content_key, packet_digest, contract_version))

    async def put(self, surface, *, expires_at):
        self.items[(surface.content_key, surface.packet_digest, surface.contract_version)] = surface


def packet(**changes) -> AIDirectorPacket:
    data = dict(
        content_key="work_warehouse_start",
        family="work",
        semantic_slot="shift_opening",
        fallback_title="Indul a műszak",
        fallback_description="A raktárban elkezdődik a műszak.",
        facts={"location": "raktár", "activity": "műszak"},
        required_terms=("raktár",),
        tags=("tier1", "work"),
    )
    data.update(changes)
    return AIDirectorPacket(**data)


def run(coro):
    return asyncio.run(coro)


def test_packet_digest_is_stable_and_fact_sensitive():
    first = packet()
    second = packet(facts={"activity": "műszak", "location": "raktár"})
    changed = packet(facts={"activity": "műszak", "location": "műhely"})
    assert first.digest() == second.digest()
    assert first.digest() != changed.digest()


def test_provider_contract_accepts_only_title_and_description():
    title, description = validate_provider_surface(
        packet(), {"title": "Raktári kezdés", "description": "A raktár új feladattal ébred."}
    )
    assert title == "Raktári kezdés"
    assert "raktár" in description


@pytest.mark.parametrize("field", ["reward", "chance", "choices", "outcome", "settlement", "inventory"])
def test_provider_contract_rejects_authority_fields(field):
    with pytest.raises(AIDirectorValidationError):
        validate_provider_surface(
            packet(), {"title": "Raktári kezdés", "description": "A raktár új feladattal ébred.", field: 1}
        )


def test_provider_contract_rejects_missing_grounding_anchor():
    with pytest.raises(AIDirectorValidationError, match="grounding anchor"):
        validate_provider_surface(packet(), {"title": "Műszakkezdés", "description": "Új feladat érkezik."})


def test_initialize_delegates_only_cache_housekeeping():
    repo = FakeRepo()
    service = AIDirectorService(repo)
    run(service.initialize())
    assert repo.initialized and repo.purged


def test_non_tier1_family_is_rejected_before_provider_call():
    provider = FakeProvider()
    service = AIDirectorService(FakeRepo(), provider=provider, runtime_enabled=True)
    with pytest.raises(AIDirectorValidationError):
        run(service.surface(packet(family="chapter"), allow_generation=True))
    assert provider.calls == 0


def test_runtime_disabled_always_returns_deterministic_fallback():
    provider = FakeProvider()
    service = AIDirectorService(FakeRepo(), provider=provider, runtime_enabled=False)
    surface = run(service.surface(packet(), allow_generation=True))
    assert surface.source == "deterministic_fallback"
    assert surface.title == "Indul a műszak"
    assert provider.calls == 0


def test_generation_requires_explicit_allow_generation():
    provider = FakeProvider()
    service = AIDirectorService(FakeRepo(), provider=provider, runtime_enabled=True)
    surface = run(service.surface(packet(), allow_generation=False))
    assert surface.source == "deterministic_fallback"
    assert provider.calls == 0


def test_valid_generation_is_cached_and_second_call_uses_cache():
    provider = FakeProvider({"title": "Raktári fordulat", "description": "A raktár ma szokatlanul mozgalmas."})
    service = AIDirectorService(FakeRepo(), provider=provider, runtime_enabled=True)
    first = run(service.surface(packet(), allow_generation=True))
    second = run(service.surface(packet(), allow_generation=False))
    assert first.source == second.source == "ai_cached"
    assert first.title == second.title
    assert provider.calls == 1


def test_provider_error_fails_closed_without_cache():
    provider = FakeProvider(error=RuntimeError("provider down"))
    repo = FakeRepo()
    service = AIDirectorService(repo, provider=provider, runtime_enabled=True)
    result = run(service.surface(packet(), allow_generation=True))
    assert result.source == "deterministic_fallback"
    assert repo.items == {}


def test_invalid_provider_output_fails_closed_without_cache():
    provider = FakeProvider({"title": "Gyors pénz", "description": "Új helyzet.", "reward": 500000})
    repo = FakeRepo()
    service = AIDirectorService(repo, provider=provider, runtime_enabled=True)
    result = run(service.surface(packet(), allow_generation=True))
    assert result.source == "deterministic_fallback"
    assert provider.calls == 1
    assert repo.items == {}


def test_batch_tracks_generated_cache_hits_and_fallbacks():
    provider = FakeProvider({"title": "Raktári hír", "description": "A raktár új feladatra készül."})
    service = AIDirectorService(FakeRepo(), provider=provider, runtime_enabled=True)
    one = packet(content_key="work_a")
    two = packet(content_key="work_b")
    generated = run(service.review_batch((one, two), allow_generation=True))
    cached = run(service.review_batch((one, two), allow_generation=False))
    assert (generated.generated, generated.cache_hits, generated.fallbacks) == (2, 0, 0)
    assert (cached.generated, cached.cache_hits, cached.fallbacks) == (0, 2, 0)
    assert provider.calls == 2


def test_batch_rejects_duplicate_packet_identity():
    service = AIDirectorService(FakeRepo())
    item = packet()
    with pytest.raises(ValueError, match="Duplikált"):
        run(service.review_batch((item, item)))


def test_surface_has_no_authoritative_gameplay_fields():
    names = {field.name for field in fields(AIDirectorSurface)}
    forbidden = {"reward", "payout", "chance", "success", "wallet", "inventory", "cooldown", "settlement", "choices"}
    assert not names.intersection(forbidden)


def test_mysql_cache_schema_is_innodb_and_has_no_player_state_columns():
    source = Path("app/repositories/ai_director.py").read_text(encoding="utf-8")
    mysql = source.split('mysql_sql="""', 1)[1].split('"""', 1)[0]
    assert "ENGINE=InnoDB" in mysql
    assert "PRIMARY KEY(content_key,packet_digest,contract_version)" in mysql
    for forbidden in ("user_id", "wallet", "reward", "inventory", "success", "settlement"):
        assert forbidden not in mysql


def test_production_composition_is_providerless_and_disabled():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "AIDirectorCacheRepository(self.database.path)" in source
    assert "provider=None, runtime_enabled=False" in source
    assert "await self.ai_director.initialize()" in source


def test_tier1_review_catalog_covers_exact_roadmap_families():
    from app.ai_director_tier1 import TIER1_REVIEW_PACKETS
    from app.ai_director import validate_packet

    families = {item.family for item in TIER1_REVIEW_PACKETS}
    assert families == {"work", "crime", "search", "beg", "career"}
    assert len(TIER1_REVIEW_PACKETS) == 15
    assert len({item.content_key for item in TIER1_REVIEW_PACKETS}) == len(TIER1_REVIEW_PACKETS)
    for item in TIER1_REVIEW_PACKETS:
        assert validate_packet(item) is item
        assert "cached_review" in item.tags


def test_tier1_review_catalog_contains_no_authority_fact_keys():
    from app.ai_director_tier1 import TIER1_REVIEW_PACKETS
    forbidden = {"reward", "payout", "chance", "success", "wallet", "inventory", "cooldown", "settlement"}
    for item in TIER1_REVIEW_PACKETS:
        assert not forbidden.intersection(item.facts)
