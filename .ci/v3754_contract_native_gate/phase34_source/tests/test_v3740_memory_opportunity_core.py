from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import db_backend as aiosqlite
from app.database import Database
from app.launch_reset_config import RESET_GUILD_TABLES, REQUIRED_TABLES
from app.services.characters import Character
from app.services.memory import ConsequenceMemoryService
from app.services.opportunities import Opportunity, OpportunityResolver


async def _insert_character(path: str, guild_id: int = 1, user_id: int = 2, *, finalized_at: str | None = None) -> Character:
    now = finalized_at or datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """INSERT INTO characters(
                   guild_id,user_id,character_name,age,birthplace,background_key,home_city_key,current_city_key,
                   status,schema_version,created_at,updated_at,finalized_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (guild_id, user_id, "Teszt Elek", 22, "Miskolc", "worker_family", "miskolc", "miskolc", "active", 1, now, now, now),
        )
        await db.commit()
    return Character(
        guild_id, user_id, "Teszt Elek", 22, "Miskolc", "worker_family", "miskolc", "miskolc",
        "active", 1, now, now, now,
    )


@pytest.mark.asyncio
async def test_phase3_schema_is_additive_and_reset_classified(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "phase3.db")
    db = Database(path, 1000)
    await db.initialize()

    expected = {"character_memory_state", "character_relationship_state", "player_opportunity_history"}
    assert expected.issubset(set(RESET_GUILD_TABLES))
    assert expected.issubset(set(REQUIRED_TABLES))

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {str(row[0]) for row in await cur.fetchall()}
    assert expected.issubset(names)


@pytest.mark.asyncio
async def test_record_consequence_is_idempotent_for_relationship_deltas(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "memory.db")
    db = Database(path, 1000)
    await db.initialize()
    await _insert_character(path)
    memory = ConsequenceMemoryService(db)

    kwargs = dict(
        memory_key="npc:jani:tools_helped",
        category="relationship",
        subject_type="npc",
        subject_key="jani",
        state_key="helped_with_tools",
        value={"decision": "helped"},
        trust_delta=25,
        favor_to_player_delta=1,
        relationship_flags={"helped_before": True},
    )
    first, rel1 = await memory.record_consequence(1, 2, **kwargs)
    second, rel2 = await memory.record_consequence(1, 2, **kwargs)

    assert first.memory_key == second.memory_key
    assert rel1 is not None and rel1.trust_score == 25 and rel1.favor_owed_to_player == 1
    assert rel2 is not None and rel2.trust_score == 25 and rel2.favor_owed_to_player == 1
    assert rel2.trust_band == "warm"
    assert rel2.flags["helped_before"] is True

    facts = await memory.recall(1, 2)
    assert [item.memory_key for item in facts] == ["npc:jani:tools_helped"]


@pytest.mark.asyncio
async def test_memory_key_cannot_be_reused_for_different_semantic_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "identity.db")
    db = Database(path, 1000)
    await db.initialize()
    await _insert_character(path)
    memory = ConsequenceMemoryService(db)

    await memory.record_consequence(
        1, 2, memory_key="npc:jani:first", category="relationship", subject_type="npc",
        subject_key="jani", state_key="helped", trust_delta=10,
    )
    with pytest.raises(ValueError):
        await memory.record_consequence(
            1, 2, memory_key="npc:jani:first", category="relationship", subject_type="npc",
            subject_key="jani", state_key="betrayed", trust_delta=-50,
        )

    rel = await memory.relationship(1, 2, "npc", "jani")
    assert rel.trust_score == 10


@pytest.mark.asyncio
async def test_memory_snapshot_and_deactivation_do_not_touch_character_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "snapshot.db")
    db = Database(path, 1000)
    await db.initialize()
    await _insert_character(path)
    memory = ConsequenceMemoryService(db)

    await memory.remember(
        1, 2,
        memory_key="story:first_choice",
        category="decision",
        subject_type="world",
        subject_key="yoru_world",
        state_key="chose_legal_path",
        value={"path": "legal"},
    )
    snap = await memory.snapshot(1, 2)
    assert snap.has("story:first_choice")
    assert await memory.deactivate(1, 2, "story:first_choice") is True
    snap2 = await memory.snapshot(1, 2)
    assert not snap2.has("story:first_choice")

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM character_history WHERE guild_id=? AND user_id=?", (1, 2))
        history_count = int((await cur.fetchone())[0])
    assert history_count == 0


@pytest.mark.asyncio
async def test_resolver_enriches_metadata_and_uses_real_selection_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "resolver.db")
    db = Database(path, 1000)
    await db.initialize()
    character = await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    resolver = OpportunityResolver(db, memory)
    snapshot = SimpleNamespace(cycle_id="cycle-a", expires_at="2026-08-20T00:00:00+00:00")

    candidates = [
        Opportunity("housing_step", "🏠", "Lakhatás", "Lakhatási lépcső.", "housing", 50),
        Opportunity("career_search", "💼", "Állás", "Állást kereshetsz.", "career", 50),
        Opportunity("street_search", "🔎", "Környék", "Nézz körül.", "street:search", 50),
        Opportunity("urgent_training", "🎓", "Aktív képzés", "Folytasd.", "training", 96),
    ]

    first = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=candidates, limit=4)
    assert first[0].key == "urgent_training"
    assert all(item.delivery_channel == "panel" for item in first)
    assert all(item.expires_at == snapshot.expires_at for item in first)
    by_key = {item.key: item for item in first}
    assert by_key["career_search"].source_family == "career"
    assert by_key["housing_step"].requirement_reason == "current_housing_progression"

    await resolver.record_selection(
        1, 2, opportunity_key="housing_step", action_key="housing", cycle_id="cycle-a", source_family="housing"
    )
    second = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=candidates, limit=4)
    positions = {item.key: i for i, item in enumerate(second)}
    assert positions["housing_step"] > positions["career_search"]
    assert second[0].key == "urgent_training"  # critical progression stays stable


@pytest.mark.asyncio
async def test_opportunity_history_records_selection_not_panel_view(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "history.db")
    db = Database(path, 1000)
    await db.initialize()
    character = await _insert_character(path)
    resolver = OpportunityResolver(db, ConsequenceMemoryService(db))
    snapshot = SimpleNamespace(cycle_id="cycle-a", expires_at="2026-08-20T00:00:00+00:00")

    # Resolving/displaying candidates must not itself mutate pacing history.
    await resolver.resolve(
        1, 2, snapshot=snapshot, character=character,
        candidates=[Opportunity("career_search", "💼", "Állás", "Állást kereshetsz.", "career", 52)], limit=5,
    )
    assert await resolver.recent_history(1, 2) == []

    await resolver.record_selection(
        1, 2, opportunity_key="career_search", action_key="career", cycle_id="cycle-a", source_family="career"
    )
    history = await resolver.recent_history(1, 2)
    assert len(history) == 1
    assert history[0].event_type == "selected"
    assert history[0].opportunity_key == "career_search"



@pytest.mark.asyncio
async def test_rp_world_opportunities_delegate_to_resolver_without_bypassing_eligibility(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "world-resolver.db")
    db = Database(path, 1000)
    await db.initialize()
    character = await _insert_character(path)
    await db.ensure_user(1, 2)

    from app.services.world import RPWorldService

    world = RPWorldService(db, ConsequenceMemoryService(db))
    snapshot, offers = await world.opportunities(
        1, 2,
        character=character,
        housing=SimpleNamespace(tier_key="street"),
        qualifications=[],
        vehicles=[],
        police=SimpleNamespace(points=0),
        active_training=None,
        business_count=0,
        has_business_license=False,
        business_license_price=10_000_000,
        street_cooldowns={"search": None, "beg": None, "slut": None},
        employment_key=None,
    )

    assert snapshot.guild_id == 1
    assert 1 <= len(offers) <= 5
    assert any(item.key == "shelter" for item in offers)
    assert all(item.source_family != "general" for item in offers)
    assert all(item.requirement_reason for item in offers)

    keys_before = {item.key for item in offers}

    async def fixed_snapshot(_guild_id: int):
        return snapshot

    monkeypatch.setattr(world, "ensure_current", fixed_snapshot)
    await world.record_opportunity_selection(
        1, 2, opportunity_key="career_search", action_key="career"
    )
    _snapshot2, offers2 = await world.opportunities(
        1, 2,
        character=character,
        housing=SimpleNamespace(tier_key="street"),
        qualifications=[],
        vehicles=[],
        police=SimpleNamespace(points=0),
        active_training=None,
        business_count=0,
        has_business_license=False,
        business_license_price=10_000_000,
        street_cooldowns={"search": None, "beg": None, "slut": None},
        employment_key=None,
    )
    # The resolver may surface a lower-ranked candidate after the selected
    # family is de-prioritized, but every returned row still carries canonical
    # metadata and the recorded selection remains explicit pacing input.
    assert 1 <= len(offers2) <= 5
    assert all(item.source_family != "general" for item in offers2)
    history = await world.opportunity_resolver.recent_history(1, 2)
    assert history and history[0].opportunity_key == "career_search"

def test_phase3_does_not_create_parallel_player_command_or_raw_reputation_ui() -> None:
    root = Path(__file__).resolve().parents[1]
    memory_text = (root / "app/services/memory.py").read_text(encoding="utf-8")
    resolver_text = (root / "app/services/opportunities.py").read_text(encoding="utf-8")
    world_text = (root / "app/services/world.py").read_text(encoding="utf-8")
    view_text = (root / "app/cogs/character_views/world.py").read_text(encoding="utf-8")

    assert "@app_commands" not in memory_text
    assert "@commands.command" not in memory_text
    assert "@app_commands" not in resolver_text
    assert "@commands.command" not in resolver_text
    assert "self.opportunity_resolver.resolve" in world_text
    assert "record_opportunity_selection" in world_text
    assert "record_opportunity_selection" in view_text
    assert "trust_score" not in view_text
    assert "favor_owed_to_player" not in view_text
