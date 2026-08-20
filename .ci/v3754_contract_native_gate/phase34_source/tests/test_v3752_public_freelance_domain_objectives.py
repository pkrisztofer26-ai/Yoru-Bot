from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db_backend as aiosqlite
from app.database import Database
from app.services.characters import CharacterService
from app.services.contracts import ContractService, ObjectiveSpec
from app.services.crew import CrewService
from app.services.memory import ConsequenceMemoryService
from app.services.memory_adapters import MemoryAdapterService
from app.services.opportunities import OpportunityResolver
from app.services.statistics import StatisticsService
from app.services.vehicles import VehicleService


class FakeStats:
    async def add(self, *args, **kwargs): return None
    async def increment(self, *args, **kwargs): return None
    async def set_max(self, *args, **kwargs): return None


async def _stack(tmp_path: Path, monkeypatch, *, starting: int = 100_000_000):
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "contracts_w143.db")
    db = Database(path, starting)
    await db.initialize()
    memory = ConsequenceMemoryService(db)
    resolver = OpportunityResolver(db, memory)
    contracts = ContractService(db)
    contracts.bind_opportunity_resolver(resolver)
    return path, db, memory, contracts


async def _insert_character(path: str, user_id: int, city: str = "miskolc") -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            """INSERT INTO characters(
                   guild_id,user_id,character_name,age,birthplace,background_key,home_city_key,current_city_key,
                   status,schema_version,created_at,updated_at,finalized_at
               ) VALUES(1,?,?,?,?,?,?,?,'active',1,?,?,?)""",
            (user_id, f"Teszt {user_id}", 22, "Miskolc", "worker_family", city, city, now, now, now),
        )
        await conn.commit()


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()


@pytest.mark.asyncio
async def test_public_sources_are_deterministic_idempotent_and_budget_reserved(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    first = await contracts.list_open_contracts(1, 20)
    public = [row for row in first if row.source_type == "public"]
    assert {"lilla_public_courier", "jani_public_service"}.issubset({row.source_ref.split(":", 1)[0] for row in public})
    second = await contracts.list_open_contracts(1, 20)
    assert {row.contract_id for row in public} == {row.contract_id for row in second if row.source_type == "public"}
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets WHERE guild_id=1 AND budget_key='npc_public_freelance'"
        )
        row = await cur.fetchone()
        assert row is not None and int(row[0]) >= 420_000 and int(row[1]) == 0
        cur = await conn.execute("SELECT COUNT(*) FROM contract_source_state WHERE guild_id=1 AND target_user_id=0")
        assert int((await cur.fetchone())[0]) >= 2


@pytest.mark.asyncio
async def test_public_city_contract_settlement_moves_reserved_budget_to_spent_once(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    before = await db.get_balance(1, 20)
    rows = await contracts.list_open_contracts(1, 20)
    city = next(row for row in rows if row.source_ref.startswith("lilla_public_courier:"))
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets WHERE guild_id=1 AND budget_key='npc_public_freelance'"
        )
        before_reserved, before_spent = map(int, await cur.fetchone())
    objective = (await contracts.objectives(1, city.contract_id))[0]
    start, end = str(objective["target_ref"]).split(":", 1)
    await contracts.accept_contract(1, city.contract_id, 20)
    result = await contracts.record_matching_city_delivery(1, 20, travel_id=991, from_city_key=start, to_city_key=end)
    assert result is not None and result.settled is True
    replay = await contracts.record_matching_city_delivery(1, 20, travel_id=991, from_city_key=start, to_city_key=end)
    assert replay is not None and replay.replay is True
    after = await db.get_balance(1, 20)
    assert after[0] - before[0] == 240_000
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets WHERE guild_id=1 AND budget_key='npc_public_freelance'"
        )
        reserved, spent = map(int, await cur.fetchone())
        assert before_reserved - reserved == city.reward_amount
        assert spent - before_spent == city.reward_amount


@pytest.mark.asyncio
async def test_private_source_requires_relationship_resolver_and_is_targeted(tmp_path: Path, monkeypatch) -> None:
    _path, db, memory, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (20, 30):
        await db.ensure_user(1, uid)
    before = await contracts.list_open_contracts(1, 20)
    assert not any(row.source_type == "private" for row in before)
    for key in ("private_access_a", "private_access_b"):
        await memory.record_consequence(
            1, 20, memory_key=f"npc:lilla:{key}", category="relationship", subject_type="npc",
            subject_key="lilla_dispatcher", state_key=key, value={"source": "test"}, trust_delta=25,
        )
    after = await contracts.list_open_contracts(1, 20)
    private = next(row for row in after if row.source_type == "private")
    assert private.source_ref.startswith("lilla_private_courier:")
    other = await contracts.list_open_contracts(1, 30)
    assert private.contract_id not in {row.contract_id for row in other}
    with pytest.raises(ValueError, match="nem neked"):
        await contracts.accept_contract(1, private.contract_id, 30)
    accepted = await contracts.accept_contract(1, private.contract_id, 20)
    assert accepted.assignee_id == 20 and accepted.status == "active"


@pytest.mark.asyncio
async def test_vehicle_repair_owning_domain_emits_stable_contract_event(tmp_path: Path, monkeypatch) -> None:
    path, db, memory, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    await _insert_character(path, 20)
    created = await contracts.create_player_contract(
        1, 10, title="Javíts meg egy járművet", reward_amount=200_000, expires_at=_future(),
        objectives=[ObjectiveSpec("service", "vehicle_service", "service:repair")],
    )
    await contracts.accept_contract(1, created.contract_id, 20)
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO character_vehicles(
                   guild_id,user_id,model_key,condition_key,city_key,purchase_price,estimated_value,status,acquired_at,updated_at,sold_at
               ) VALUES(1,20,'suzuki_swift_2005','poor','miskolc',3000000,2730000,'owned',?,?,NULL)""",
            (now, now),
        )
        vehicle_id = int(cur.lastrowid or 0)
        await conn.execute(
            """INSERT INTO vehicle_state(vehicle_id,guild_id,user_id,is_primary,issue_key,issue_revealed,last_service_at,updated_at)
               VALUES(?,1,20,1,NULL,0,NULL,?)""", (vehicle_id, now),
        )
        await conn.commit()
    adapters = MemoryAdapterService(memory)
    vehicles = VehicleService(db, CharacterService(db), memory, adapters)
    vehicles.bind_contracts(contracts)
    await vehicles.repair_vehicle(1, 20, vehicle_id)
    snap = await contracts.get_contract(1, created.contract_id)
    assert snap is not None and snap.status == "settled"
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT event_key FROM contract_event_claims WHERE guild_id=1 AND contract_id=?", (created.contract_id,))
        event_key = str((await cur.fetchone())[0])
    assert event_key.startswith("vehicle_repair_tx:")


@pytest.mark.asyncio
async def test_crew_deposit_owning_domain_progresses_contribution(tmp_path: Path, monkeypatch) -> None:
    _path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    created_crew = await db.create_crew(1, 20, "Teszt Crew", "teszt crew", 0)
    crew_id = int(created_crew["crew_id"])
    job = await contracts.create_player_contract(
        1, 10, title="Közös kassza hozzájárulás", reward_amount=150_000, expires_at=_future(),
        objectives=[ObjectiveSpec("contribution", "contribution", f"crew:{crew_id}", 100_000)],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    crew = CrewService(db, StatisticsService(db)); crew.bind_contracts(contracts)
    await crew.deposit(1, 20, 100_000)
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status == "settled"
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute("SELECT event_key FROM contract_event_claims WHERE contract_id=?", (job.contract_id,))
        assert str((await cur.fetchone())[0]).startswith("crew_deposit_tx:")


@pytest.mark.asyncio
async def test_business_delivery_consumes_real_inventory_and_settles(tmp_path: Path, monkeypatch) -> None:
    from app.services.business import BusinessService
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            """INSERT INTO business_properties(
                   guild_id,template_key,name,emoji,category,city,district,street,base_price,base_hourly_revenue,
                   hourly_upkeep,max_workers,owner_id,level,reputation,last_claim_at,acquired_at,created_at
               ) VALUES(1,'w143_test','Teszt Műhely','🏢','service','miskolc','Belváros','Teszt utca',1000000,1000,100,2,10,1,0,NULL,?,?)""",
            (now, now),
        )
        property_id = int(cur.lastrowid or 0)
        await conn.commit()
    await db.add_item(1, 20, "lottery_ticket", 5)
    job = await contracts.create_player_contract(
        1, 10, title="Vállalkozási beszállítás", reward_amount=200_000, expires_at=_future(),
        objectives=[ObjectiveSpec("supply", "business_delivery", f"property:{property_id}", 3, {"item_id": "lottery_ticket", "quantity": 3})],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    objective = (await contracts.objectives(1, job.contract_id))[0]
    business = BusinessService(db, FakeStats()); business.bind_contracts(contracts)
    result = await business.deliver_contract_supply(1, 20, job.contract_id, int(objective["objective_id"]))
    assert result["quantity"] == 3
    assert await db.get_item_quantity(1, 20, "lottery_ticket") == 2
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status == "settled"
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM business_delivery_history WHERE guild_id=1 AND property_id=?", (property_id,))
        assert int((await cur.fetchone())[0]) == 1


def test_w143_system_participation_hook_and_bindings_are_after_authoritative_domains() -> None:
    root = Path(__file__).resolve().parents[1]
    heist = (root / "app/services/heist.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    service = (root / "app/services/contracts.py").read_text(encoding="utf-8")
    assert 'event_type="system_participation"' in heist
    assert 'event_key=f"heist_run:' in heist
    assert heist.index("await conn.commit()") < heist.index('event_type="system_participation"')
    for token in (
        "self.contracts.bind_opportunity_resolver(self.world.opportunity_resolver)",
        "self.crew.bind_contracts(self.contracts)", "self.businesses.bind_contracts(self.contracts)",
        "self.heists.bind_contracts(self.contracts)",
    ):
        assert token in main
    assert "c.source_type='player'" not in service[service.index("async def record_matching_domain_event"):service.index("async def record_matching_city_delivery")]

@pytest.mark.asyncio
async def test_expired_system_contract_releases_reserved_budget_without_payout(tmp_path: Path, monkeypatch) -> None:
    path, db, _memory, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    rows = await contracts.list_open_contracts(1, 20)
    service_job = next(row for row in rows if row.source_ref.startswith("jani_public_service:"))
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets WHERE guild_id=1 AND budget_key='npc_public_freelance'"
        )
        before_reserved, before_spent = map(int, await cur.fetchone())
        await conn.execute(
            "UPDATE contracts SET expires_at=? WHERE guild_id=1 AND contract_id=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), service_job.contract_id),
        )
        await conn.commit()
    assert await contracts.expire_due(1) == 1
    expired = await contracts.get_contract(1, service_job.contract_id)
    assert expired is not None and expired.status == "expired" and expired.escrow_state == "refunded"
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets WHERE guild_id=1 AND budget_key='npc_public_freelance'"
        )
        after_reserved, after_spent = map(int, await cur.fetchone())
    assert before_reserved - after_reserved == service_job.reward_amount
    assert after_spent == before_spent
