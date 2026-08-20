from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import db_backend as aiosqlite
from app import npc_config, npc_favor_config, vehicle_config
from app.database import Database
from app.services.business import BusinessService
from app.services.characters import CharacterService
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService
from app.services.npc_followups import FOLLOWUPS, NPCFollowupService
from app.services.vehicles import VehicleService


class FakeStats:
    async def add(self, *args, **kwargs):
        return None

    async def increment(self, *args, **kwargs):
        return None

    async def set_max(self, *args, **kwargs):
        return None


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
    return await CharacterService(Database(path, 100_000_000)).require(guild_id, user_id)


async def _grant_and_redeem(
    adapters: MemoryAdapterService,
    followups: NPCFollowupService,
    *,
    npc_key: str,
    cycle: str = "cycle-a",
):
    await adapters.npc_consequence(
        1, 2, npc_key=npc_key, event_key=f"help_{cycle}", preset_key="player_helped"
    )
    return await followups.redeem_favor(1, 2, npc_key=npc_key, cycle_id=cycle)


def test_w134_npc_content_pack_is_unique_and_deliberate() -> None:
    assert len(npc_config.NPCS) == 12
    assert len({item.key for item in npc_config.NPCS}) == 12
    assert len({item.display_name for item in npc_config.NPCS}) == 12
    assert len(FOLLOWUPS) == 12
    assert set(FOLLOWUPS) == {item.key for item in npc_config.NPCS}
    for item in npc_config.NPCS:
        assert item.role_key in npc_config.ROLE_BY_KEY
        assert item.with_name
        assert item.tags
    for key in (
        "bence_business_contact", "zoli_black_market_broker", "dora_legal_contact",
        "reka_property_agent", "akos_training_mentor", "eszter_merchant",
        "marci_city_contact", "tamas_organization_contact",
    ):
        assert npc_config.npc(key).key == key


def test_domain_favor_effect_config_has_no_settlement_authority() -> None:
    effects = {item.key: item for item in npc_favor_config.FAVOR_EFFECTS}
    assert set(effects) == {
        "jani_repair_discount",
        "misi_dealership_discount",
        "bence_business_license_discount",
    }
    assert effects["jani_repair_discount"].domain == "vehicle"
    assert effects["misi_dealership_discount"].domain == "vehicle"
    assert effects["bence_business_license_discount"].domain == "business"
    assert effects["jani_repair_discount"].savings(1_000_000) == 250_000
    assert effects["misi_dealership_discount"].savings(20_000_000) == 500_000
    assert effects["bence_business_license_discount"].savings(5_000_000) == 500_000


@pytest.mark.asyncio
async def test_redeemed_jani_favor_becomes_active_domain_voucher(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "jani-voucher.db")
    db = Database(path, 100_000_000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)

    result = await _grant_and_redeem(adapters, followups, npc_key="jani_mechanic")
    assert result.effect_key == "jani_repair_discount"
    assert result.effect_label
    voucher = await memory.active_favor_effect(
        1, 2, effect_key="jani_repair_discount", subject_key="jani_mechanic"
    )
    assert voucher is not None and voucher.active
    assert voucher.state_key == "favor_effect.jani_repair_discount"


@pytest.mark.asyncio
async def test_jani_discount_is_consumed_in_same_repair_transaction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "jani-repair.db")
    db = Database(path, 100_000_000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)
    vehicles = VehicleService(db, CharacterService(db), memory, adapters)

    await _grant_and_redeem(adapters, followups, npc_key="jani_mechanic")
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO character_vehicles(
                   guild_id,user_id,model_key,condition_key,city_key,purchase_price,estimated_value,
                   status,acquired_at,updated_at,sold_at
               ) VALUES(?,?,?,?,?,?,?,'owned',?,?,NULL)""",
            (1, 2, "suzuki_swift_2005", "poor", "miskolc", 3_000_000, 2_730_000, now, now),
        )
        vehicle_id = int(cur.lastrowid or 0)
        await conn.execute(
            """INSERT INTO vehicle_state(vehicle_id,guild_id,user_id,is_primary,issue_key,issue_revealed,last_service_at,updated_at)
               VALUES(?,?,?,1,NULL,0,NULL,?)""",
            (vehicle_id, 1, 2, now),
        )
        await conn.commit()

    base = vehicle_config.repair_price("suzuki_swift_2005", "poor", None)
    quote = await vehicles.repair_quote(1, 2, vehicle_id)
    expected_saving = npc_favor_config.effect("jani_repair_discount").savings(base)
    assert quote == base - expected_saving

    result = await vehicles.repair_vehicle(1, 2, vehicle_id)
    assert result.base_price == base
    assert result.discount_saved == expected_saving
    assert result.paid == base - expected_saving
    assert result.favor_effect_key == "jani_repair_discount"
    assert await memory.active_favor_effect(
        1, 2, effect_key="jani_repair_discount", subject_key="jani_mechanic"
    ) is None
    facts = await memory.recall(1, 2, subject_type="character", subject_key="vehicles")
    assert any(f.state_key == "vehicle_repaired" for f in facts)


@pytest.mark.asyncio
async def test_failed_repair_does_not_consume_jani_voucher(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "jani-rollback.db")
    db = Database(path, 0)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)
    vehicles = VehicleService(db, CharacterService(db), memory, adapters)

    await _grant_and_redeem(adapters, followups, npc_key="jani_mechanic")
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO character_vehicles(
                   guild_id,user_id,model_key,condition_key,city_key,purchase_price,estimated_value,
                   status,acquired_at,updated_at,sold_at
               ) VALUES(?,?,?,?,?,?,?,'owned',?,?,NULL)""",
            (1, 2, "suzuki_swift_2005", "poor", "miskolc", 3_000_000, 2_730_000, now, now),
        )
        vehicle_id = int(cur.lastrowid or 0)
        await conn.execute(
            """INSERT INTO vehicle_state(vehicle_id,guild_id,user_id,is_primary,issue_key,issue_revealed,last_service_at,updated_at)
               VALUES(?,?,?,1,NULL,0,NULL,?)""",
            (vehicle_id, 1, 2, now),
        )
        await conn.commit()

    with pytest.raises(ValueError):
        await vehicles.repair_vehicle(1, 2, vehicle_id)
    assert await memory.active_favor_effect(
        1, 2, effect_key="jani_repair_discount", subject_key="jani_mechanic"
    ) is not None


@pytest.mark.asyncio
async def test_misi_discount_is_owned_by_vehicle_dealership_settlement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "misi-car.db")
    db = Database(path, 100_000_000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)
    vehicles = VehicleService(db, CharacterService(db), memory, adapters)

    await _grant_and_redeem(adapters, followups, npc_key="misi_car_dealer")
    model_key = "suzuki_swift_2005"
    base = vehicle_config.dealership_price(model_key)
    result = await vehicles.buy_dealership(1, 2, model_key)
    saving = npc_favor_config.effect("misi_dealership_discount").savings(base)
    assert result.source == "dealership"
    assert result.base_price == base
    assert result.discount_saved == saving
    assert result.price == base - saving
    assert result.favor_effect_key == "misi_dealership_discount"
    assert await memory.active_favor_effect(
        1, 2, effect_key="misi_dealership_discount", subject_key="misi_car_dealer"
    ) is None


@pytest.mark.asyncio
async def test_bence_discount_is_owned_by_business_license_settlement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "bence-business.db")
    db = Database(path, 100_000_000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)
    business = BusinessService(db, FakeStats(), memory=memory, memory_adapters=adapters)

    await _grant_and_redeem(adapters, followups, npc_key="bence_business_contact")
    quote = await business.license_quote(1, 2)
    effect = npc_favor_config.effect("bence_business_license_discount")
    assert quote.discount_saved == effect.savings(quote.base_price)

    result = await business.buy_license_result(1, 2)
    assert result.discount_saved == effect.savings(result.base_price)
    assert result.paid == result.base_price - result.discount_saved
    assert result.favor_effect_key == effect.key
    assert await memory.active_favor_effect(
        1, 2, effect_key=effect.key, subject_key=effect.npc_key
    ) is None
    facts = await memory.recall(1, 2, subject_type="contract", subject_key="business.license")
    assert any(f.state_key == "license_purchased" for f in facts)


@pytest.mark.asyncio
async def test_relationship_summary_has_semantic_labels_without_raw_numbers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "summary.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    followups = NPCFollowupService(memory, adapters)

    await adapters.npc_consequence(1, 2, npc_key="reka_property_agent", event_key="help", preset_key="player_helped")
    await adapters.npc_consequence(1, 2, npc_key="zoli_black_market_broker", event_key="rival", preset_key="rival_escalated")
    rows = await followups.relationship_summaries(1, 2)
    by_key = {row.npc_key: row for row in rows}
    assert by_key["zoli_black_market_broker"].status_label == "Rivális"
    assert by_key["reka_property_agent"].status_label == "Szívességgel tartozik"
    rendered = " ".join(f"{r.status_label} {r.note}" for r in rows).casefold()
    assert "trust_score" not in rendered
    assert "favor_owed" not in rendered
    assert "10" not in rendered and "-20" not in rendered


@pytest.mark.asyncio
async def test_new_outcome_adapters_are_idempotent_and_non_authoritative(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "outcome-adapters.db")
    db = Database(path, 1000)
    await db.initialize(); await db.ensure_user(1, 2); await _insert_character(path)
    memory = ConsequenceMemoryService(db)
    adapters = MemoryAdapterService(memory)
    now = datetime.now(timezone.utc).isoformat()

    one = await adapters.crime_resolved(
        1, 2, event_key="crime-one", success=True, scenario="teszt", amount=123, jailed=False, occurred_at=now
    )
    two = await adapters.crime_resolved(
        1, 2, event_key="crime-one", success=True, scenario="teszt", amount=123, jailed=False, occurred_at=now
    )
    assert one.memory_key == two.memory_key

    h1 = await adapters.heist_resolved(
        1, 2, lobby_id=77, target_key="test", status="success", payout=1000, fine=0, caught=False, occurred_at=now
    )
    h2 = await adapters.heist_resolved(
        1, 2, lobby_id=77, target_key="test", status="success", payout=1000, fine=0, caught=False, occurred_at=now
    )
    assert h1.memory_key == h2.memory_key


def test_phone_deep_link_and_relationship_ui_are_player_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    notifications = (root / "app/cogs/notifications.py").read_text(encoding="utf-8")
    character = (root / "app/cogs/character.py").read_text(encoding="utf-8")
    followups = (root / "app/services/npc_followups.py").read_text(encoding="utf-8")
    favor_cfg = (root / "app/npc_favor_config.py").read_text(encoding="utf-8")

    assert 'label="Kapcsolatok"' in notifications
    assert "focus_subject_key" in notifications
    assert "focus_key" in notifications
    assert "focus_subject_key" in character
    assert "trust_score" not in notifications
    assert "favor_owed_to_player" not in notifications
    for forbidden in ("add_wallet(", "remove_wallet(", "add_item(", "award_xp("):
        assert forbidden not in followups
        assert forbidden not in favor_cfg
