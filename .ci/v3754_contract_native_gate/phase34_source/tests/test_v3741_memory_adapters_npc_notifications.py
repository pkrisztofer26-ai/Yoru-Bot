from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import db_backend as aiosqlite
from app import notification_config, npc_config
from app.database import Database
from app.services.characters import CharacterService
from app.services.jobs import JobsService
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService
from app.services.notification_contracts import GameplayNotificationContract, GameplayNotificationIntent
from app.services.opportunities import Opportunity, OpportunityResolver
from app.services.statistics import StatisticsService
from app.services.training import TrainingService


async def _insert_character(path: str, guild_id: int = 1, user_id: int = 2) -> None:
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


class FakeNotifications:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def notify(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {"notification_id": len(self.calls), **kwargs}


@pytest.mark.asyncio
async def test_canonical_npc_registry_preserves_reviewed_baseline_identities() -> None:
    baseline_roles = {
        "job_agent", "car_dealer", "mechanic", "dispatcher",
        "business_contact", "black_market_broker", "legal_contact",
    }
    baseline_npcs = {
        "kata_job_agent", "misi_car_dealer", "jani_mechanic", "lilla_dispatcher",
    }
    assert baseline_roles.issubset(set(npc_config.ROLE_BY_KEY))
    assert baseline_npcs.issubset(set(npc_config.NPC_BY_KEY))
    assert npc_config.npc("jani_mechanic").role_key == "mechanic"
    assert len(npc_config.NPC_BY_KEY) == len(npc_config.NPCS)
    # Reserved roles may be deliberately promoted to named canonical NPCs by
    # later content packs; they must never overlap an unknown role.
    assert npc_config.RESERVED_ROLE_SLOTS.issubset(set(npc_config.ROLE_BY_KEY))


@pytest.mark.asyncio
async def test_npc_consequence_presets_are_idempotent_and_persist_favor_rival_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "npc-memory.db")
    db = Database(path, 1000)
    await db.initialize()
    await _insert_character(path)
    adapters = MemoryAdapterService(ConsequenceMemoryService(db))

    first_fact, first_rel = await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="tools_help", preset_key="player_helped"
    )
    retry_fact, retry_rel = await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="tools_help", preset_key="player_helped"
    )
    assert first_fact.memory_key == retry_fact.memory_key
    assert first_rel is not None and retry_rel is not None
    assert first_rel.favor_owed_to_player == 1
    assert retry_rel.favor_owed_to_player == 1  # replay cannot double-count
    assert retry_rel.flags["player_helped"] is True

    _betrayal, rel2 = await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="deal_betrayal", preset_key="betrayal"
    )
    assert rel2 is not None and rel2.rival_state == "tension"
    _escalation, rel3 = await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="rival_escalation", preset_key="rival_escalated"
    )
    assert rel3 is not None and rel3.rival_state == "rival"
    assert rel3.flags["persistent_rival"] is True


@pytest.mark.asyncio
async def test_relationship_gated_opportunity_requires_explicit_subject_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "relationship-opportunity.db")
    db = Database(path, 1000)
    await db.initialize()
    await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    resolver = OpportunityResolver(db, memory)
    character = await CharacterService(db).require(1, 2)
    snapshot = SimpleNamespace(cycle_id="phase3", expires_at="2026-08-20T00:00:00+00:00")

    private = Opportunity(
        "jani_private_followup", "🔧", "Jani visszajelzett", "Van egy személyes folytatás.",
        "relationship", 60, source_family="relationship", rarity="uncommon",
        subject_type="npc", subject_key="jani_mechanic",
        required_trust_bands=("warm", "trusted"), required_relationship_flags=("player_helped",),
    )
    public = Opportunity("career_search", "💼", "Állás", "Állást kereshetsz.", "career", 50)

    before = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[private, public], limit=5)
    assert [item.key for item in before] == ["career_search"]

    await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="help_a", preset_key="player_helped"
    )
    # One help is positive but still below the warm band; access remains closed.
    middle = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[private, public], limit=5)
    assert [item.key for item in middle] == ["career_search"]

    await adapters.npc_consequence(
        1, 2, npc_key="jani_mechanic", event_key="help_b", preset_key="player_helped"
    )
    after = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[private, public], limit=5)
    assert {item.key for item in after} == {"jani_private_followup", "career_search"}
    gated = next(item for item in after if item.key == "jani_private_followup")
    assert gated.subject_key == "jani_mechanic"


@pytest.mark.asyncio
async def test_memory_key_gated_opportunity_only_uses_explicit_memory_requirement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "memory-opportunity.db")
    db = Database(path, 1000)
    await db.initialize()
    await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    resolver = OpportunityResolver(db, memory)
    character = await CharacterService(db).require(1, 2)
    snapshot = SimpleNamespace(cycle_id="phase3", expires_at="2026-08-20T00:00:00+00:00")
    candidate = Opportunity(
        "forklift_followup", "🏗️", "Új raktári út", "A képesítésedhez kapcsolódó lehetőség.",
        "career", 50, required_memory_keys=("training.completed:forklift",),
    )
    assert await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[candidate]) == []
    await MemoryAdapterService(memory).training_completed(
        1, 2, course_key="forklift", completed_at=datetime.now(timezone.utc).isoformat()
    )
    result = await resolver.resolve(1, 2, snapshot=snapshot, character=character, candidates=[candidate])
    assert [item.key for item in result] == ["forklift_followup"]


@pytest.mark.asyncio
async def test_career_hire_and_quit_write_memory_only_after_domain_settlement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "career-memory.db")
    db = Database(path, 1000)
    await db.initialize()
    await db.ensure_user(1, 2)
    await _insert_character(path)
    characters = CharacterService(db)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    jobs = JobsService(
        db, SimpleNamespace(), StatisticsService(db), characters=characters,
        training=None, world=None, vehicles=None, housing=None, scenarios=None,
        memory_adapters=adapters,
    )

    hired = await jobs.hire(1, 2, "shelf_stocker")
    assert hired["career_key"] == "shelf_stocker"
    snapshot = await memory.snapshot(1, 2)
    hired_facts = [fact for fact in snapshot.facts if fact.state_key == "career_hired"]
    assert len(hired_facts) == 1
    assert hired_facts[0].source_history_event_id is not None

    ended = await jobs.quit_employment(1, 2)
    assert ended["career_key"] == "shelf_stocker"
    snapshot2 = await memory.snapshot(1, 2)
    assert sum(1 for fact in snapshot2.facts if fact.state_key == "career_hired") == 1
    assert sum(1 for fact in snapshot2.facts if fact.state_key == "career_quit") == 1


@pytest.mark.asyncio
async def test_training_completion_hook_records_semantic_memory_after_qualification(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "training-memory.db")
    db = Database(path, 1000)
    await db.initialize()
    await db.ensure_user(1, 2)
    await _insert_character(path)
    characters = CharacterService(db)
    memory = ConsequenceMemoryService(db)
    training = TrainingService(db, characters, MemoryAdapterService(memory))
    now = datetime.now(timezone.utc).isoformat()

    # Put the deterministic test character at the final B-license stage with a
    # score that passes after the strongest canonical final choice.
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "INSERT INTO training_sessions(guild_id,user_id,course_key,status,stage_index,started_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (1, 2, "driving_b", "active", 3, now, now),
        )
        await conn.execute(
            "INSERT INTO user_statistics(guild_id,user_id,stat_name,value,updated_at) VALUES(?,?,?,?,?)",
            (1, 2, "training.score.driving_b", 6, now),
        )
        await conn.commit()

    result = await training.choose(1, 2, course_key="driving_b", expected_stage=3, choice_key="reroute")
    assert result.completed is True
    snapshot = await memory.snapshot(1, 2)
    facts = [fact for fact in snapshot.facts if fact.memory_key == "training.completed:driving_b"]
    assert len(facts) == 1
    assert facts[0].state_key == "qualification_driving_b"


@pytest.mark.asyncio
async def test_notification_contract_reuses_existing_backend_and_canonical_npc_identity() -> None:
    fake = FakeNotifications()
    contract = GameplayNotificationContract(fake)  # type: ignore[arg-type]

    row = await contract.relationship_followup(
        1, 2, npc_key="lilla_dispatcher", event_key="callback_01",
        title="Lilla keresett", body="Lilla később szeretne egyeztetni veled.", important=True,
    )
    assert row["category"] == "relationship"
    assert row["action_type"] == "relationship"
    assert fake.calls[0]["event_key"] == "gameplay:relationship.lilla_dispatcher.callback_01:npc:lilla_dispatcher"

    await contract.private_opportunity(
        1, 2, opportunity_key="lilla_private_job", event_key="cycle_44",
        title="Privát lehetőség", body="Egy korábbi kapcsolatod miatt új lehetőség nyílt meg.",
        expires_at="2026-08-20T00:00:00+00:00", npc_key="lilla_dispatcher",
    )
    assert fake.calls[1]["category"] == "opportunity"
    assert fake.calls[1]["action_type"] == "opportunity"

    with pytest.raises(KeyError):
        await contract.relationship_followup(
            1, 2, npc_key="invented_person", event_key="x", title="X", body="Y"
        )

    with pytest.raises(ValueError):
        await contract.deliver(
            1, 2, GameplayNotificationIntent(
                intent_key="leak.test", category="relationship", severity="info",
                title="Kapcsolat", body="trust_score=85", subject_type="npc", subject_key="jani_mechanic",
            )
        )


def test_notification_categories_and_action_urls_extend_existing_system_without_second_backend() -> None:
    assert notification_config.CATEGORY_LABELS["relationship"][1] == "Kapcsolatok"
    assert notification_config.CATEGORY_LABELS["opportunity"][1] == "Lehetőségek"
    assert notification_config.OPTIONAL_DM_DEFAULTS["relationship"] is True
    assert notification_config.OPTIONAL_DM_DEFAULTS["opportunity"] is True

    root = Path(__file__).resolve().parents[1]
    contracts = (root / "app/services/notification_contracts.py").read_text(encoding="utf-8")
    notifications = (root / "app/services/notifications.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    assert "NotificationRepository" not in contracts
    assert "self.notifications.notify(" in contracts
    assert '"relationship": "life_panel"' in notifications
    assert '"opportunity": "life_panel"' in notifications
    assert "GameplayNotificationContract(self.notifications)" in main


def test_w132_adds_no_parallel_player_command_and_no_raw_relationship_ui() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "app/npc_config.py",
        root / "app/services/memory_adapters.py",
        root / "app/services/notification_contracts.py",
        root / "app/services/opportunities.py",
    ]
    joined = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert "@app_commands" not in joined
    assert "@commands.command" not in joined
    world_view = (root / "app/cogs/character_views/world.py").read_text(encoding="utf-8")
    assert "trust_score" not in world_view
    assert "favor_owed_to_player" not in world_view
    assert "required_trust_bands" not in world_view
