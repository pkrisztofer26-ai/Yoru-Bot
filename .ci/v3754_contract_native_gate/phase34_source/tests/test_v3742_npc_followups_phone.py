from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import db_backend as aiosqlite
from app.database import Database
from app.services.characters import CharacterService
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService
from app.services.notification_contracts import GameplayNotificationContract
from app.services.npc_followups import NPCFollowupService
from app.services.opportunities import OpportunityResolver
from app.services.world import RPWorldService


async def _insert_character(path: str, guild_id: int = 1, user_id: int = 2):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """INSERT INTO characters(
                   guild_id,user_id,character_name,age,birthplace,background_key,home_city_key,current_city_key,
                   status,schema_version,created_at,updated_at,finalized_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (guild_id, user_id, "Teszt Elek", 22, "Miskolc", "worker_family", "miskolc", "miskolc", "active", 1, now, now, now),
        )
        await db.commit()
    return await CharacterService(Database(path, 1000)).require(guild_id, user_id)


class FakeNotifications:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.by_event: dict[str, dict] = {}

    async def notify(self, **kwargs):
        key = str(kwargs["event_key"])
        if key in self.by_event:
            return self.by_event[key]
        row = {"notification_id": len(self.calls) + 1, **kwargs}
        self.calls.append(row)
        self.by_event[key] = row
        return row


@pytest.mark.asyncio
async def test_favor_redemption_is_atomic_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "favor.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)

    await adapters.npc_consequence(1, 2, npc_key="jani_mechanic", event_key="help_one", preset_key="player_helped")
    await adapters.npc_consequence(1, 2, npc_key="jani_mechanic", event_key="help_two", preset_key="player_helped")
    rel0 = await memory.relationship(1, 2, "npc", "jani_mechanic")
    assert rel0.favor_owed_to_player == 2

    first = await followups.redeem_favor(1, 2, npc_key="jani_mechanic", cycle_id="cycle-a")
    assert first.newly_consumed is True and first.remaining_favors == 1

    replay = await followups.redeem_favor(1, 2, npc_key="jani_mechanic", cycle_id="cycle-a")
    assert replay.memory_key == first.memory_key
    assert replay.newly_consumed is False
    assert replay.remaining_favors == 1

    second = await followups.redeem_favor(1, 2, npc_key="jani_mechanic", cycle_id="cycle-b")
    assert second.newly_consumed is True and second.remaining_favors == 0
    with pytest.raises(ValueError):
        await followups.redeem_favor(1, 2, npc_key="jani_mechanic", cycle_id="cycle-c")

    facts = await memory.recall(1, 2, category="favor")
    redeemed = [fact for fact in facts if fact.subject_key == "jani_mechanic"]
    assert len(redeemed) == 2
    assert all(fact.state_key in {"favor_redeemed", "favor_effect.jani_repair_discount"} for fact in redeemed)


@pytest.mark.asyncio
async def test_tension_blocks_favor_until_explicit_resolution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "tension.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)

    await adapters.npc_consequence(1, 2, npc_key="misi_car_dealer", event_key="help", preset_key="player_helped")
    await adapters.npc_consequence(1, 2, npc_key="misi_car_dealer", event_key="broken", preset_key="betrayal")
    offers = await followups.candidates(1, 2)
    keys = {item.key for item in offers}
    assert "npc_tension_misi_car_dealer" in keys
    assert "npc_favor_misi_car_dealer" not in keys
    with pytest.raises(ValueError):
        await followups.redeem_favor(1, 2, npc_key="misi_car_dealer", cycle_id="cycle-a")

    resolved = await followups.resolve_tension(1, 2, npc_key="misi_car_dealer", cycle_id="cycle-a")
    assert resolved.rival_state == "resolved"
    offers2 = await followups.candidates(1, 2)
    assert "npc_favor_misi_car_dealer" in {item.key for item in offers2}


@pytest.mark.asyncio
async def test_persistent_rival_cannot_be_cleared_by_quick_tension_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "rival.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)

    await adapters.npc_consequence(1, 2, npc_key="lilla_dispatcher", event_key="escalated", preset_key="rival_escalated")
    offers = await followups.candidates(1, 2)
    rival = next(item for item in offers if item.key == "npc_rival_lilla_dispatcher")
    assert rival.action_key == "relationship:rival:lilla_dispatcher"
    assert rival.repeat_cooldown_hours == 24
    with pytest.raises(ValueError):
        await followups.resolve_tension(1, 2, npc_key="lilla_dispatcher", cycle_id="cycle-a")
    rel = await memory.relationship(1, 2, "npc", "lilla_dispatcher")
    assert rel.rival_state == "rival"


@pytest.mark.asyncio
async def test_relationship_followup_uses_selection_history_for_anti_repeat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "cooldown.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); character = await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)
    resolver = OpportunityResolver(db, memory)

    # Four kept agreements reach warm without creating favors.
    for idx in range(4):
        await adapters.npc_consequence(1, 2, npc_key="kata_job_agent", event_key=f"kept_{idx}", preset_key="agreement_kept")
    candidates = await followups.candidates(1, 2)
    item = next(row for row in candidates if row.key == "npc_followup_kata_job_agent")
    snapshot = SimpleNamespace(cycle_id="cycle-a", expires_at="2026-08-20T00:00:00+00:00")
    first = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[item], limit=5)
    assert [row.key for row in first] == ["npc_followup_kata_job_agent"]

    await resolver.record_selection(
        1, 2, opportunity_key=item.key, action_key=item.action_key, cycle_id="cycle-a", source_family="relationship"
    )
    second = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[item], limit=5)
    assert second == []


@pytest.mark.asyncio
async def test_world_adds_relationship_candidate_without_bypassing_resolver(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "world-followup.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); character = await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)
    world = RPWorldService(db, memory)
    world.bind_npc_followups(followups)
    await adapters.npc_consequence(1, 2, npc_key="jani_mechanic", event_key="help", preset_key="player_helped")

    _snapshot, offers = await world.opportunities(
        1, 2, character=character, housing=SimpleNamespace(tier_key="street"), qualifications=[], vehicles=[],
        police=SimpleNamespace(points=0), active_training=None, business_count=0, has_business_license=False,
        business_license_price=10_000_000, street_cooldowns={"search": None, "beg": None, "slut": None}, employment_key=None,
    )
    favor = next(item for item in offers if item.key == "npc_favor_jani_mechanic")
    assert favor.source_family == "relationship"
    assert favor.required_favor_to_player == 1
    assert favor.subject_type == "npc" and favor.subject_key == "jani_mechanic"


@pytest.mark.asyncio
async def test_npc_consequence_can_emit_deduped_phone_followup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "phone.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    backend = FakeNotifications()
    contract = GameplayNotificationContract(backend)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters, contract)
    adapters.bind_followups(followups)

    await adapters.npc_consequence(1, 2, npc_key="jani_mechanic", event_key="help", preset_key="player_helped")
    await adapters.npc_consequence(1, 2, npc_key="jani_mechanic", event_key="help", preset_key="player_helped")
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["category"] == "opportunity"
    assert call["action_type"] == "opportunity"
    assert call["action_ref"] == "npc_favor_jani_mechanic"
    assert "trust_score" not in (call["title"] + call["body"])


@pytest.mark.asyncio
async def test_opportunity_outcome_history_supports_completed_and_resolved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "outcomes.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    world = RPWorldService(db, ConsequenceMemoryService(db))
    snapshot = await world.ensure_current(1)
    async def fixed(_guild_id: int): return snapshot
    monkeypatch.setattr(world, "ensure_current", fixed)

    await world.record_opportunity_outcome(
        1, 2, opportunity_key="npc_favor_jani_mechanic", action_key="favor:jani_mechanic",
        event_type="completed", source_family="relationship",
    )
    await world.record_opportunity_outcome(
        1, 2, opportunity_key="npc_tension_jani_mechanic", action_key="relationship:tension:jani_mechanic",
        event_type="resolved", source_family="relationship",
    )
    history = await world.opportunity_resolver.recent_history(1, 2)
    assert {row.event_type for row in history[:2]} == {"completed", "resolved"}


def test_canonical_npc_registry_owns_hungarian_with_name_forms() -> None:
    from app import npc_config
    assert npc_config.npc("kata_job_agent").with_name == "Katával"
    assert npc_config.npc("misi_car_dealer").with_name == "Misivel"
    assert npc_config.npc("jani_mechanic").with_name == "Janival"
    assert npc_config.npc("lilla_dispatcher").with_name == "Lillával"


def test_phone_ui_and_followup_layer_do_not_expose_raw_relationship_state_or_add_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    followups = (root / "app/services/npc_followups.py").read_text(encoding="utf-8")
    world_view = (root / "app/cogs/character_views/world.py").read_text(encoding="utf-8")
    profile = (root / "app/cogs/character_views/profile.py").read_text(encoding="utf-8")
    notifications = (root / "app/cogs/notifications.py").read_text(encoding="utf-8")

    assert "@app_commands" not in followups and "@commands.command" not in followups
    for forbidden_call in ("add_wallet(", "remove_wallet(", "add_item(", "remove_item(", "award_xp("):
        assert forbidden_call not in followups
    assert "trust_score" not in world_view
    assert "favor_owed_to_player" not in world_view
    assert 'label="Telefon"' in profile
    assert '📱 Telefon' in notifications
    assert 'action_type in {"relationship", "opportunity"}' in notifications
