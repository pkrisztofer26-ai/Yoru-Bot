from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import contract_config as cfg
from app import db_backend as aiosqlite
from app.database import Database
from app.services.contracts import ContractService, ObjectiveSpec
from app.services.memory import ConsequenceMemoryService
from app.services.opportunities import OpportunityResolver


class FakeStats:
    async def add(self, *args, **kwargs): return None
    async def increment(self, *args, **kwargs): return None
    async def set_max(self, *args, **kwargs): return None


async def _stack(tmp_path: Path, monkeypatch, *, starting: int = 100_000_000):
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "contracts_w144.db")
    db = Database(path, starting)
    await db.initialize()
    memory = ConsequenceMemoryService(db)
    resolver = OpportunityResolver(db, memory)
    contracts = ContractService(db)
    contracts.bind_opportunity_resolver(resolver)
    return path, db, memory, contracts


async def _insert_business(path: str, owner_id: int, *, name: str = "Teszt Műhely") -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO business_properties(
                   guild_id,template_key,name,emoji,category,city,district,street,base_price,base_hourly_revenue,
                   hourly_upkeep,max_workers,owner_id,level,reputation,last_claim_at,acquired_at,created_at
               ) VALUES(1,'w144_test',?,'🏢','service','miskolc','Belváros','Teszt utca',1000000,1000,100,2,?,1,0,NULL,?,?)""",
            (name, owner_id, now, now),
        )
        await conn.commit()
        return int(cur.lastrowid or 0)


def _future(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_public_modifier_sources_are_deterministic_and_service_discoverable(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    rows = await contracts.list_open_contracts(1, 20)
    public = {row.source_ref.split(":", 1)[0]: row for row in rows if row.source_type == "public"}
    assert {"lilla_public_courier", "jani_public_service", "marci_public_courier"}.issubset(public)

    marci = public["marci_public_courier"]
    assert marci.reward_amount == 230_000
    created = datetime.fromisoformat(marci.created_at)
    expires = datetime.fromisoformat(marci.expires_at)
    assert 17.5 <= (expires - created).total_seconds() / 3600 <= 18.5
    state = await contracts.source_state(1, marci.contract_id)
    assert state is not None and "priority_window" in state["modifiers"]

    services = await contracts.list_service_contracts(1, 20)
    service_keys = {row.source_ref.split(":", 1)[0] for row in services if row.source_type == "public"}
    assert {"lilla_public_courier", "jani_public_service", "marci_public_courier"}.issubset(service_keys)

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets "
            "WHERE guild_id=1 AND budget_key='npc_public_freelance'"
        )
        reserved, spent = map(int, await cur.fetchone())
    assert reserved == 650_000 and spent == 0


@pytest.mark.asyncio
async def test_unknown_or_incompatible_modifier_is_rejected_before_contract_creation(tmp_path: Path, monkeypatch) -> None:
    _path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    base = cfg.SOURCE_BY_KEY["lilla_public_courier"]
    unknown = replace(base, key="test_unknown_modifier", modifiers=("not_allowed",))
    with pytest.raises(ValueError, match="Ismeretlen contract modifier"):
        await contracts.create_system_contract(
            1, source=unknown, objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")], period_key="2099-01-01"
        )
    incompatible = replace(base, key="test_bad_objective_modifier", modifiers=("bulk_support",))
    with pytest.raises(ValueError, match="nem alkalmazható"):
        await contracts.create_system_contract(
            1, source=incompatible, objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")], period_key="2099-01-02"
        )


@pytest.mark.asyncio
async def test_bence_private_business_support_scales_quantity_and_settles_via_business_domain(tmp_path: Path, monkeypatch) -> None:
    from app.services.business import BusinessService

    path, db, memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    property_id = await _insert_business(path, 20, name="Bence célvállalkozás")
    await memory.record_consequence(
        1, 20, memory_key="npc:bence:w144_access", category="relationship", subject_type="npc",
        subject_key="bence_business_contact", state_key="w144_access", value={"source": "test"}, trust_delta=25,
    )

    rows = await contracts.list_open_contracts(1, 20)
    bence = next(row for row in rows if row.source_ref.startswith("bence_private_business_support:"))
    assert bence.source_type == "private" and bence.reward_amount == 450_000
    objectives = await contracts.objectives(1, bence.contract_id)
    objective = objectives[0]
    assert objective["objective_type"] == "business_delivery"
    assert objective["target_ref"] == f"property:{property_id}"
    assert int(objective["required_value"]) == 2
    assert objective["metadata"]["item_id"] == "used_phone"

    await contracts.accept_contract(1, bence.contract_id, 20)
    await db.add_item(1, 20, "used_phone", 2)
    business = BusinessService(db, FakeStats())
    business.bind_contracts(contracts)
    result = await business.deliver_contract_supply(1, 20, bence.contract_id, int(objective["objective_id"]))
    assert result["quantity"] == 2
    assert await db.get_item_quantity(1, 20, "used_phone") == 0
    settled = await contracts.get_contract(1, bence.contract_id)
    assert settled is not None and settled.status == "settled" and settled.escrow_state == "released"


@pytest.mark.asyncio
async def test_player_business_support_appears_in_shared_service_discovery(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    property_id = await _insert_business(path, 10, name="Player supply target")
    job = await contracts.create_player_contract(
        1, 10, title="Beszerzési segítség", reward_amount=175_000, expires_at=_future(),
        objectives=[ObjectiveSpec("supply", "business_delivery", f"property:{property_id}", 2, {"item_id": "used_phone", "quantity": 2})],
        source_ref=f"business_supply:{property_id}",
    )
    services = await contracts.list_service_contracts(1, 20, service_family="business_delivery")
    assert job.contract_id in {row.contract_id for row in services}


@pytest.mark.asyncio
async def test_repeated_pair_and_rapid_completion_are_telemetry_only_not_punishment(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)

    settled_ids: list[int] = []
    for index in range(3):
        job = await contracts.create_player_contract(
            1, 10, title=f"Gyors fuvar {index}", reward_amount=50_000, expires_at=_future(),
            objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
        )
        await contracts.accept_contract(1, job.contract_id, 20)
        result = await contracts.record_matching_city_delivery(
            1, 20, travel_id=8_000 + index, from_city_key="miskolc", to_city_key="eger"
        )
        assert result is not None and result.settled is True
        settled_ids.append(job.contract_id)

    third = await contracts.get_contract(1, settled_ids[-1])
    assert third is not None and third.status == "settled"
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT event_type,COUNT(*) FROM contract_telemetry WHERE guild_id=1 "
            "AND event_type IN ('rapid_completion','repeated_pair') GROUP BY event_type"
        )
        counts = {str(row[0]): int(row[1]) for row in await cur.fetchall()}
    assert counts.get("rapid_completion", 0) >= 3
    assert counts.get("repeated_pair", 0) >= 1


@pytest.mark.asyncio
async def test_high_value_contract_is_audited_but_can_be_cancelled_normally(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    job = await contracts.create_player_contract(
        1, 10, title="Nagy értékű teszt", reward_amount=cfg.CONTRACT_HIGH_VALUE_THRESHOLD, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM contract_telemetry WHERE guild_id=1 AND contract_id=? AND event_type='high_value'",
            (job.contract_id,),
        )
        assert int((await cur.fetchone())[0]) >= 1
    refunded = await contracts.cancel_open_contract(1, job.contract_id, 10)
    assert refunded == cfg.CONTRACT_HIGH_VALUE_THRESHOLD
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status == "cancelled" and snap.escrow_state == "refunded"


@pytest.mark.asyncio
async def test_system_reward_budget_and_source_events_are_audited_on_settlement(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    rows = await contracts.list_open_contracts(1, 20)
    lilla = next(row for row in rows if row.source_ref.startswith("lilla_public_courier:"))
    objective = (await contracts.objectives(1, lilla.contract_id))[0]
    start, end = str(objective["target_ref"]).split(":", 1)
    await contracts.accept_contract(1, lilla.contract_id, 20)
    result = await contracts.record_matching_city_delivery(
        1, 20, travel_id=9_001, from_city_key=start, to_city_key=end
    )
    assert result is not None and result.settled is True
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT event_type,source_key,details_json FROM contract_telemetry "
            "WHERE guild_id=1 AND contract_id=? ORDER BY telemetry_id",
            (lilla.contract_id,),
        )
        rows = await cur.fetchall()
    assert any(str(row[0]) == "source_created" and str(row[1]) == "lilla_public_courier" for row in rows)
    assert any(str(row[0]) == "reward_budget" and str(row[1]) == "lilla_public_courier" and '"action":"spent"' in str(row[2]) for row in rows)


def test_w144_player_service_ui_uses_existing_domain_surfaces_and_no_auto_punishment() -> None:
    root = Path(__file__).resolve().parents[1]
    board = (root / "app/cogs/character_views/contracts.py").read_text(encoding="utf-8")
    business = (root / "app/cogs/business.py").read_text(encoding="utf-8")
    service = (root / "app/services/contracts.py").read_text(encoding="utf-8")
    assert 'label="Szolgáltatások"' in board
    assert 'label="Ellátmány átadása"' in board
    assert 'label="Szervezet"' in board
    assert 'label="Nagy Meló"' in board
    assert "BusinessSupplyContractModal" in business
    assert 'source_ref=f"business_supply:' in business
    for forbidden in ("auto_ban", "auto_punish", "auto_suspend", "automatic_ban", "contract_ban"):
        assert forbidden not in service.lower()
