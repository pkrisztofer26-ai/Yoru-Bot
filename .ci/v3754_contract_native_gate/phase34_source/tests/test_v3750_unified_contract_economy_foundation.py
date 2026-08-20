from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import contract_config
from app import db_backend as aiosqlite
from app.database import Database
from app.services.contracts import ContractService, ObjectiveSpec


def _future(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _stack(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "contracts.db")
    db = Database(path, 1_000_000)
    await db.initialize()
    return path, db, ContractService(db)


async def _balance(path: str, guild_id: int, user_id: int) -> tuple[int, int]:
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT wallet,bank FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
    return (int(row[0]), int(row[1]))


def test_w141_objective_vocabulary_and_overlap_audit_are_explicit() -> None:
    assert set(contract_config.OBJECTIVE_BY_KEY) == {
        "item_delivery",
        "city_delivery",
        "business_delivery",
        "vehicle_service",
        "contribution",
        "system_participation",
    }
    assert set(contract_config.EXISTING_TRANSACTION_PRIMITIVES) == {
        "business_offers", "pvp_duels", "player_market_listings", "crew_wars"
    }
    assert len(contract_config.EVENT_TO_OBJECTIVE) == len(contract_config.OBJECTIVE_BY_KEY)


@pytest.mark.asyncio
async def test_shared_public_wallet_bank_reserve_refund_wrapper_keeps_legacy_contract(tmp_path: Path, monkeypatch) -> None:
    path, db, _contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("UPDATE users SET wallet=100000,bank=200000 WHERE guild_id=1 AND user_id=10")
        await conn.commit()
    result = await db.debit_wallet_and_bank(1, 10, 250_000, "compat_reserve")
    assert result == (100_000, 150_000, 0, 50_000)
    assert await _balance(path, 1, 10) == (0, 50_000)
    refunded = await db.refund_wallet_and_bank(1, 10, 100_000, 150_000, "compat_refund")
    assert refunded == (100_000, 200_000)
    assert await _balance(path, 1, 10) == (100_000, 200_000)
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT money_lost FROM users WHERE guild_id=1 AND user_id=10")
        assert int((await cur.fetchone())[0]) == 0


@pytest.mark.asyncio
async def test_create_contract_reserves_wallet_then_bank_atomically(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("UPDATE users SET wallet=100000,bank=900000 WHERE guild_id=1 AND user_id=10")
        await conn.commit()

    created = await contracts.create_player_contract(
        1,
        10,
        title="Szállíts három csomagot",
        reward_amount=600_000,
        expires_at=_future(),
        objectives=[ObjectiveSpec("delivery", "item_delivery", "parcel", 3)],
    )
    assert created.status == "open"
    assert created.escrow_state == "held"
    assert await _balance(path, 1, 10) == (0, 400_000)

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT escrow_wallet_amount,escrow_bank_amount FROM contracts WHERE contract_id=?",
            (created.contract_id,),
        )
        row = await cur.fetchone()
        assert tuple(map(int, row)) == (100_000, 500_000)
        cur = await conn.execute(
            "SELECT amount,reason FROM transactions WHERE guild_id=1 AND user_id=10 ORDER BY rowid DESC LIMIT 1"
        )
        tx = await cur.fetchone()
    assert int(tx[0]) == -600_000
    assert str(tx[1]) == f"contract_escrow:{created.contract_id}"


@pytest.mark.asyncio
async def test_insufficient_escrow_rolls_back_contract_and_wallet_state(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("UPDATE users SET wallet=50000,bank=25000 WHERE guild_id=1 AND user_id=10")
        await conn.commit()
    with pytest.raises(ValueError):
        await contracts.create_player_contract(
            1, 10, title="Túl drága", reward_amount=100_000, expires_at=_future(),
            objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
        )
    assert await _balance(path, 1, 10) == (50_000, 25_000)
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM contracts WHERE guild_id=1 AND creator_id=10")
        assert int((await cur.fetchone())[0]) == 0
        cur = await conn.execute("SELECT COUNT(*) FROM transactions WHERE reason LIKE 'contract_%'")
        assert int((await cur.fetchone())[0]) == 0


@pytest.mark.asyncio
async def test_cancel_refunds_original_wallet_bank_sources_without_income_farm(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    async with aiosqlite.connect(path) as conn:
        await conn.execute("UPDATE users SET wallet=125000,bank=875000 WHERE guild_id=1 AND user_id=10")
        await conn.commit()

    created = await contracts.create_player_contract(
        1, 10, title="Fuvar", reward_amount=500_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    refunded = await contracts.cancel_open_contract(1, created.contract_id, 10)
    assert refunded == 500_000
    assert await _balance(path, 1, 10) == (125_000, 875_000)
    snapshot = await contracts.get_contract(1, created.contract_id)
    assert snapshot is not None and snapshot.status == "cancelled" and snapshot.escrow_state == "refunded"

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT money_earned,money_lost FROM users WHERE guild_id=1 AND user_id=10"
        )
        earned, lost = await cur.fetchone()
    assert int(earned) == 0
    assert int(lost) == 0


@pytest.mark.asyncio
async def test_accept_race_has_exactly_one_assignee_and_blocks_self_contract(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20, 30):
        await db.ensure_user(1, uid)
    created = await contracts.create_player_contract(
        1, 10, title="Versenyfuvar", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    with pytest.raises(ValueError):
        await contracts.accept_contract(1, created.contract_id, 10)

    results = await asyncio.gather(
        contracts.accept_contract(1, created.contract_id, 20),
        contracts.accept_contract(1, created.contract_id, 30),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    snapshot = await contracts.get_contract(1, created.contract_id)
    assert snapshot is not None and snapshot.status == "active"
    assert snapshot.assignee_id in {20, 30}


@pytest.mark.asyncio
async def test_domain_event_is_idempotent_and_double_settlement_is_impossible(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    await db.ensure_user(1, 20)
    before_assignee = await _balance(path, 1, 20)

    created = await contracts.create_player_contract(
        1, 10, title="Csomagok", reward_amount=300_000, expires_at=_future(),
        objectives=[ObjectiveSpec("packages", "item_delivery", "parcel", 3)],
    )
    await contracts.accept_contract(1, created.contract_id, 20)

    first = await contracts.record_item_delivery(
        1, created.contract_id, 20, event_key="market-trade:101", item_id="parcel", quantity=2
    )
    replay = await contracts.record_item_delivery(
        1, created.contract_id, 20, event_key="market-trade:101", item_id="parcel", quantity=2
    )
    assert first is True
    assert replay is False
    objectives = await contracts.objectives(1, created.contract_id)
    assert int(objectives[0]["current_value"]) == 2
    assert objectives[0]["status"] == "pending"

    await contracts.record_item_delivery(
        1, created.contract_id, 20, event_key="market-trade:102", item_id="parcel", quantity=1
    )
    with pytest.raises(ValueError):
        await contracts.record_item_delivery(
            1, created.contract_id, 20, event_key="wrong-target", item_id="other", quantity=1
        )

    settled, paid = await contracts.settle_ready_contract(1, created.contract_id)
    assert paid is True
    assert settled.status == "settled" and settled.escrow_state == "released"
    after_first = await _balance(path, 1, 20)
    assert after_first[0] - before_assignee[0] == 300_000

    settled_again, paid_again = await contracts.settle_ready_contract(1, created.contract_id)
    assert settled_again.status == "settled"
    assert paid_again is False
    assert await _balance(path, 1, 20) == after_first

    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE reason=?",
            (f"contract_settlement:{created.contract_id}",),
        )
        assert int((await cur.fetchone())[0]) == 1
        cur = await conn.execute(
            "SELECT COUNT(*) FROM contract_events WHERE contract_id=?",
            (created.contract_id,),
        )
        assert int((await cur.fetchone())[0]) == 2


@pytest.mark.asyncio
async def test_unfinished_objective_cannot_settle_and_wrong_actor_cannot_progress(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20, 30):
        await db.ensure_user(1, uid)
    created = await contracts.create_player_contract(
        1, 10, title="Szerviz", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("service", "vehicle_service", "vehicle:55")],
    )
    await contracts.accept_contract(1, created.contract_id, 20)
    with pytest.raises(ValueError):
        await contracts.settle_ready_contract(1, created.contract_id)
    with pytest.raises(ValueError):
        await contracts.record_vehicle_service(
            1, created.contract_id, 30, event_key="repair:55", service_ref="vehicle:55"
        )


@pytest.mark.asyncio
async def test_expiry_refunds_even_after_accept_without_settlement(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    before = await _balance(path, 1, 10)
    created = await contracts.create_player_contract(
        1, 10, title="Lejáró", reward_amount=200_000, expires_at=_future(),
        objectives=[ObjectiveSpec("participate", "system_participation", "crew_war:7")],
    )
    await contracts.accept_contract(1, created.contract_id, 20)
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "UPDATE contracts SET expires_at=? WHERE contract_id=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), created.contract_id),
        )
        await conn.commit()
    assert await contracts.expire_due(1) == 1
    assert await _balance(path, 1, 10) == before
    snapshot = await contracts.get_contract(1, created.contract_id)
    assert snapshot is not None and snapshot.status == "expired" and snapshot.escrow_state == "refunded"


@pytest.mark.asyncio
async def test_all_six_state_backed_event_wrappers_progress_only_matching_objectives(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 10)
    await db.ensure_user(1, 20)
    specs = [
        ObjectiveSpec("item", "item_delivery", "steel", 2),
        ObjectiveSpec("city", "city_delivery", "eger:miskolc"),
        ObjectiveSpec("business", "business_delivery", "property:9"),
        ObjectiveSpec("vehicle", "vehicle_service", "vehicle:4"),
        ObjectiveSpec("contrib", "contribution", "project:2", 5),
        ObjectiveSpec("participate", "system_participation", "heist:bank"),
    ]
    created = await contracts.create_player_contract(
        1, 10, title="Vegyes contract", reward_amount=250_000, expires_at=_future(), objectives=specs
    )
    await contracts.accept_contract(1, created.contract_id, 20)
    assert await contracts.record_item_delivery(1, created.contract_id, 20, event_key="e1", item_id="steel", quantity=2)
    assert await contracts.record_city_delivery(1, created.contract_id, 20, event_key="e2", route_key="eger:miskolc")
    assert await contracts.record_business_delivery(1, created.contract_id, 20, event_key="e3", business_ref="property:9")
    assert await contracts.record_vehicle_service(1, created.contract_id, 20, event_key="e4", service_ref="vehicle:4")
    assert await contracts.record_contribution(1, created.contract_id, 20, event_key="e5", contribution_ref="project:2", amount=5)
    assert await contracts.record_system_participation(1, created.contract_id, 20, event_key="e6", participation_ref="heist:bank")
    objectives = await contracts.objectives(1, created.contract_id)
    assert len(objectives) == 6
    assert all(row["status"] == "completed" for row in objectives)
