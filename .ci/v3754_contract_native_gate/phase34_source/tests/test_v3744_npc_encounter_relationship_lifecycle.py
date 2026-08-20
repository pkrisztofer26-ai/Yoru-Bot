from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db_backend as aiosqlite
from app import npc_config
from app.database import Database
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService
from app.services.npc_followups import NPCFollowupService
from app.services.opportunities import OpportunityResolver
from app.services.police import PoliceService


def _iso(hours: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class FakeFollowups:
    def __init__(self) -> None:
        self.first_contacts: list[dict] = []

    async def notify_first_contact(self, guild_id: int, user_id: int, **kwargs) -> None:
        self.first_contacts.append({"guild_id": guild_id, "user_id": user_id, **kwargs})

    async def notify_after_consequence(self, *args, **kwargs) -> None:
        return None


async def _stack(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "w135.db")
    db = Database(path, 1_000_000)
    await db.initialize()
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    return path, db, memory, adapters


def test_first_contact_source_registry_is_explicit_for_all_w134_npcs() -> None:
    expected = {
        "bence_business_contact": {"business_license_purchased"},
        "zoli_black_market_broker": {"black_market_purchase", "crime_success"},
        "dora_legal_contact": {
            "police_crime_incident", "police_street_incident",
            "police_robbery_incident", "police_heist_incident",
        },
        "reka_property_agent": {"housing_purchase"},
        "akos_training_mentor": {"training_enrolled", "training_completed"},
        "eszter_merchant": {"business_property_purchased", "player_market_trade"},
        "marci_city_contact": {"travel_completed"},
        "tamas_organization_contact": {"organization_created", "organization_joined"},
    }
    assert set(npc_config.NPC_FIRST_CONTACT_SOURCES) == set(expected)
    for npc_key, sources in expected.items():
        assert npc_config.first_contact_sources(npc_key) == frozenset(sources)


@pytest.mark.asyncio
async def test_all_eight_encounter_adapters_unlock_canonical_contacts(tmp_path: Path, monkeypatch) -> None:
    _path, _db, memory, adapters = await _stack(tmp_path, monkeypatch)
    now = _iso()

    await adapters.business_license_purchased(
        1, 2, paid=1_000_000, base_price=1_000_000, discount_saved=0,
        favor_effect_key=None, occurred_at=now,
    )
    await adapters.black_market_purchased(1, 2, item_id="lockpick", quantity=1, occurred_at=now)
    await adapters.police_incident(1, 2, source_key="police_street_incident", occurred_at=now)
    await adapters.housing_purchased(
        1, 2, tier_key="rented_flat", city_key="miskolc", property_id=None, occurred_at=now,
    )
    await adapters.training_enrolled(1, 2, course_key="driving_b", occurred_at=now)
    await adapters.business_property_purchased(1, 2, property_id=41, city="miskolc", occurred_at=now)
    await adapters.travel_completed(
        1, 2, from_city_key="miskolc", to_city_key="eger", mode_key="bus", occurred_at=now,
    )
    await adapters.organization_membership(1, 2, crew_id=7, event="joined", occurred_at=now)

    expected = {
        "bence_business_contact", "zoli_black_market_broker", "dora_legal_contact",
        "reka_property_agent", "akos_training_mentor", "eszter_merchant",
        "marci_city_contact", "tamas_organization_contact",
    }
    snapshot = await memory.snapshot(1, 2, fact_limit=100)
    unlocked = {
        rel.subject_key for rel in snapshot.relationships
        if rel.subject_type == "npc" and rel.flags.get("contact_unlocked")
    }
    assert unlocked == expected
    first_contact_facts = [
        fact for fact in snapshot.facts
        if fact.subject_type == "npc" and fact.state_key == "contact_unlocked"
    ]
    assert {fact.subject_key for fact in first_contact_facts} == expected


@pytest.mark.asyncio
async def test_first_contact_is_insert_once_preserves_original_source_and_notifies_once(tmp_path: Path, monkeypatch) -> None:
    _path, _db, memory, adapters = await _stack(tmp_path, monkeypatch)
    fake = FakeFollowups()
    adapters.bind_followups(fake)
    first_at = "2026-08-20T00:01:00+00:00"
    second_at = "2026-08-20T01:01:00+00:00"

    first_fact, first_rel, first_new = await adapters.npc_first_contact(
        1, 2, npc_key="zoli_black_market_broker", source_key="black_market_purchase",
        occurred_at=first_at, value={"item_id": "x"},
    )
    second_fact, second_rel, second_new = await adapters.npc_first_contact(
        1, 2, npc_key="zoli_black_market_broker", source_key="crime_success",
        occurred_at=second_at, value={"scenario": "y"},
    )

    assert first_new is True
    assert second_new is False
    assert second_fact.memory_id == first_fact.memory_id
    assert second_fact.value["source_key"] == "black_market_purchase"
    assert second_fact.occurred_at == first_at
    assert second_rel.flags["contact_source"] == "black_market_purchase"
    assert second_rel.flags["contact_unlocked_at"] == first_at
    assert len(fake.first_contacts) == 1

    facts = await memory.recall(1, 2, category="relationship")
    matching = [fact for fact in facts if fact.memory_key == "npc.zoli_black_market_broker:first_contact"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_first_contact_rejects_unapproved_sources_and_bad_domain_roles(tmp_path: Path, monkeypatch) -> None:
    _path, _db, _memory, adapters = await _stack(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        await adapters.npc_first_contact(
            1, 2, npc_key="reka_property_agent", source_key="crime_success", occurred_at=_iso()
        )
    with pytest.raises(ValueError):
        await adapters.organization_membership(1, 2, crew_id=1, event="invited", occurred_at=_iso())
    with pytest.raises(ValueError):
        await adapters.player_market_trade(1, 2, listing_id=1, role="spectator", occurred_at=_iso())


@pytest.mark.asyncio
async def test_first_contact_creates_phone_candidate_and_lifecycle_history_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _path, db, memory, adapters = await _stack(tmp_path, monkeypatch)
    await adapters.housing_purchased(
        1, 2, tier_key="rented_flat", city_key="miskolc", property_id=None, occurred_at=_iso()
    )
    followups = NPCFollowupService(memory, adapters)
    offers = await followups.candidates(1, 2)
    offer = next(item for item in offers if item.key == "npc_contact_reka_property_agent")
    assert offer.source_family == "relationship"
    assert offer.action_key == "housing"
    assert offer.required_relationship_flags == ("contact_unlocked",)

    resolver = OpportunityResolver(db, memory)
    selected_a = await resolver.record_event(
        1, 2, opportunity_key=offer.key, action_key=offer.action_key,
        cycle_id="cycle-a", source_family=offer.source_family, event_type="selected",
    )
    selected_b = await resolver.record_event(
        1, 2, opportunity_key=offer.key, action_key=offer.action_key,
        cycle_id="cycle-a", source_family=offer.source_family, event_type="selected",
    )
    completed_a = await resolver.record_event(
        1, 2, opportunity_key=offer.key, action_key=offer.action_key,
        cycle_id="cycle-a", source_family=offer.source_family, event_type="completed",
    )
    completed_b = await resolver.record_event(
        1, 2, opportunity_key=offer.key, action_key=offer.action_key,
        cycle_id="cycle-a", source_family=offer.source_family, event_type="completed",
    )
    assert selected_a == selected_b
    assert completed_a == completed_b
    assert selected_a != completed_a

    history = await resolver.recent_history(1, 2, limit=10)
    rows = [item for item in history if item.opportunity_key == offer.key and item.cycle_id == "cycle-a"]
    assert len(rows) == 2
    assert {item.event_type for item in rows} == {"selected", "completed"}


@pytest.mark.asyncio
async def test_resolved_relationship_ages_to_neutral_but_active_tension_does_not(tmp_path: Path, monkeypatch) -> None:
    path, _db, memory, adapters = await _stack(tmp_path, monkeypatch)

    await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="old_rival", preset_key="rival_escalated"
    )
    await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="old_resolved", preset_key="rival_resolved"
    )
    await adapters.npc_consequence(
        1, 2, npc_key="misi_car_dealer", event_key="old_tension", preset_key="betrayal"
    )
    old = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "UPDATE character_relationship_state SET updated_at=? WHERE guild_id=? AND user_id=? AND subject_type='npc'",
            (old, 1, 2),
        )
        await conn.commit()

    changed = await memory.age_resolved_relationships(1, 2, older_than_hours=72)
    assert changed == 1
    jani = await memory.relationship(1, 2, "npc", "jani_mechanic")
    misi = await memory.relationship(1, 2, "npc", "misi_car_dealer")
    assert jani.rival_state == "none"
    assert misi.rival_state == "tension"
    assert jani.flags.get("persistent_rival") is False


@pytest.mark.asyncio
async def test_contact_only_relationship_is_player_facing_as_semantic_ismeros(tmp_path: Path, monkeypatch) -> None:
    _path, _db, memory, adapters = await _stack(tmp_path, monkeypatch)
    await adapters.travel_completed(
        1, 2, from_city_key="miskolc", to_city_key="eger", mode_key="bus", occurred_at=_iso()
    )
    summaries = await NPCFollowupService(memory, adapters).relationship_summaries(1, 2)
    marci = next(item for item in summaries if item.npc_key == "marci_city_contact")
    assert marci.status_label == "Ismerős"
    assert "trust" not in marci.note.casefold()
    assert "favor" not in marci.note.casefold()


class FakeCharacters:
    async def require(self, guild_id: int, user_id: int):
        return object()


class FakePoliceAdapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def police_incident(self, guild_id: int, user_id: int, **kwargs):
        self.calls.append({"guild_id": guild_id, "user_id": user_id, **kwargs})


@pytest.mark.asyncio
async def test_police_contact_only_fires_for_real_authority_incident_after_state_update(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "police-contact.db")
    db = Database(path, 1_000_000)
    await db.initialize()
    fake = FakePoliceAdapter()
    police = PoliceService(db, FakeCharacters(), memory_adapters=fake)

    clean = await police.crime_result(1, 2, success=True, jailed=False)
    assert clean.points > 0
    assert fake.calls == []

    failed = await police.crime_result(1, 2, success=False, jailed=False)
    assert failed.points > clean.points
    assert len(fake.calls) == 1
    assert fake.calls[0]["source_key"] == "police_crime_incident"
    assert fake.calls[0]["occurred_at"] == failed.updated_at
