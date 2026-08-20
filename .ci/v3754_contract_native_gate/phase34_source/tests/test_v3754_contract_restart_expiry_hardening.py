from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import contract_config as cfg
from app import db_backend as aiosqlite
from app.database import Database
from app.services.contracts import ContractService, ObjectiveSpec


async def _stack(tmp_path: Path, monkeypatch, *, starting: int = 10_000_000):
    monkeypatch.setenv("YORU_DB_BACKEND", "sqlite")
    path = str(tmp_path / "contracts_w145.db")
    db = Database(path, starting)
    await db.initialize()
    contracts = ContractService(db)
    return path, db, contracts


def _future(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_restart_recovery_settles_verified_complete_before_expiry(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    before_creator = await db.get_balance(1, 10)
    before_worker = await db.get_balance(1, 20)
    job = await contracts.create_player_contract(
        1, 10, title="Crash-gap fuvar", reward_amount=200_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    assert await contracts.record_city_delivery(
        1, job.contract_id, 20, event_key="travel:restart-proof", route_key="miskolc:eger"
    ) is True

    # Simulate: verified event committed before deadline, process stopped before payout,
    # and wall-clock later passed the deadline.
    now = datetime.now(timezone.utc)
    completed_at = (now - timedelta(hours=2)).isoformat()
    expired_at = (now - timedelta(hours=1)).isoformat()
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "UPDATE contract_objectives SET updated_at=? WHERE guild_id=1 AND contract_id=?",
            (completed_at, job.contract_id),
        )
        await conn.execute(
            "UPDATE contracts SET expires_at=? WHERE guild_id=1 AND contract_id=?",
            (expired_at, job.contract_id),
        )
        await conn.commit()

    # Normal expiry must not steal a verified-complete contract.
    assert await contracts.expire_due(1) == 0
    report = await contracts.recover_restart_state(1)
    assert report.ready_settled == 1 and report.expired == 0
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status == "settled" and snap.escrow_state == "released"
    creator = await db.get_balance(1, 10)
    worker = await db.get_balance(1, 20)
    assert sum(before_creator) - sum(creator) == 200_000
    assert worker[0] - before_worker[0] == 200_000

    second = await contracts.recover_restart_state(1)
    assert second.ready_settled == 0 and second.expired == 0
    assert await db.get_balance(1, 20) == worker


@pytest.mark.asyncio
async def test_restart_recovery_expires_incomplete_once_and_refunds_once(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    before = await db.get_balance(1, 10)
    job = await contracts.create_player_contract(
        1, 10, title="Lejáró fuvar", reward_amount=150_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "UPDATE contracts SET expires_at=? WHERE guild_id=1 AND contract_id=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), job.contract_id),
        )
        await conn.commit()

    report = await contracts.recover_restart_state(1)
    assert report.ready_settled == 0 and report.expired == 1
    assert await db.get_balance(1, 10) == before
    second = await contracts.recover_restart_state(1)
    assert second.expired == 0
    assert await db.get_balance(1, 10) == before


@pytest.mark.asyncio
async def test_reward_budget_reconciliation_repairs_reserved_and_never_reduces_spent(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    source = cfg.SOURCE_BY_KEY["lilla_public_courier"]
    job = await contracts.create_system_contract(
        1, source=source, period_key="2099-01-01",
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "UPDATE contract_reward_budgets SET reserved_amount=0,spent_amount=123456 "
            "WHERE guild_id=1 AND budget_key=? AND period_key='2099-01-01'",
            (source.budget_key,),
        )
        await conn.commit()
    result = await contracts.reconcile_reward_budgets(1, repair=True)
    assert result["repaired"] == 1 and result["violations"] == 0
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets "
            "WHERE guild_id=1 AND budget_key=? AND period_key='2099-01-01'",
            (source.budget_key,),
        )
        reserved, spent = map(int, await cur.fetchone())
    assert reserved == job.reward_amount
    assert spent == 123456


@pytest.mark.asyncio
async def test_concurrent_same_domain_event_is_claimed_once_and_replay_follows_claim(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    jobs = []
    for idx in range(2):
        job = await contracts.create_player_contract(
            1, 10, title=f"Fuvar {idx}", reward_amount=50_000, expires_at=_future(),
            objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
        )
        await contracts.accept_contract(1, job.contract_id, 20)
        jobs.append(job)

    results = await asyncio.gather(
        contracts.record_matching_city_delivery(1, 20, travel_id=77, from_city_key="miskolc", to_city_key="eger"),
        contracts.record_matching_city_delivery(1, 20, travel_id=77, from_city_key="miskolc", to_city_key="eger"),
    )
    assert all(result is not None for result in results)
    ids = {result.contract.contract_id for result in results if result is not None}
    assert len(ids) == 1
    assert sum(bool(result.progressed) for result in results if result is not None) == 1
    assert sum(bool(result.replay) for result in results if result is not None) == 1


@pytest.mark.asyncio
async def test_accept_vs_cancel_race_has_single_terminal_or_active_owner(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    before_creator = await db.get_balance(1, 10)
    job = await contracts.create_player_contract(
        1, 10, title="Accept-cancel race", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )

    async def accept():
        try:
            return await contracts.accept_contract(1, job.contract_id, 20)
        except ValueError:
            return None

    async def cancel():
        try:
            return await contracts.cancel_open_contract(1, job.contract_id, 10)
        except ValueError:
            return None

    await asyncio.gather(accept(), cancel())
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None
    creator = await db.get_balance(1, 10)
    if snap.status == "cancelled":
        assert snap.escrow_state == "refunded" and creator == before_creator
    else:
        assert snap.status == "active" and snap.assignee_id == 20 and snap.escrow_state == "held"
        assert sum(before_creator) - sum(creator) == 100_000


@pytest.mark.asyncio
async def test_settle_vs_expiry_prefers_verified_completion(tmp_path: Path, monkeypatch) -> None:
    path, db, contracts = await _stack(tmp_path, monkeypatch)
    for uid in (10, 20):
        await db.ensure_user(1, uid)
    job = await contracts.create_player_contract(
        1, 10, title="Settle-expiry race", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    assert await contracts.record_city_delivery(
        1, job.contract_id, 20, event_key="travel:settle-expiry", route_key="miskolc:eger"
    )
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    older = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    async with aiosqlite.connect(path) as conn:
        await conn.execute("UPDATE contract_objectives SET updated_at=? WHERE contract_id=?", (older, job.contract_id))
        await conn.execute("UPDATE contracts SET expires_at=? WHERE contract_id=?", (old, job.contract_id))
        await conn.commit()
    settle_result, expire_result = await asyncio.gather(
        contracts.settle_ready_contract(1, job.contract_id), contracts.expire_due(1)
    )
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status == "settled" and snap.escrow_state == "released"
    assert settle_result[0].status == "settled"
    assert expire_result == 0


@pytest.mark.asyncio
async def test_telemetry_retention_and_row_cap_are_bounded(tmp_path: Path, monkeypatch) -> None:
    path, _db, contracts = await _stack(tmp_path, monkeypatch)
    monkeypatch.setattr(cfg, "CONTRACT_TELEMETRY_MAX_ROWS_PER_GUILD", 5)
    monkeypatch.setattr(cfg, "CONTRACT_TELEMETRY_RETENTION_DAYS", 30)
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(path) as conn:
        for idx in range(8):
            created = (now - timedelta(days=60)).isoformat() if idx == 0 else now.isoformat()
            await conn.execute(
                """INSERT INTO contract_telemetry(
                       guild_id,event_key,event_type,contract_id,actor_id,counterparty_id,source_key,reward_amount,details_json,created_at
                   ) VALUES(1,?,'rapid_completion',NULL,NULL,NULL,'test',0,'{}',?)""",
                (f"w145:{idx}", created),
            )
        await conn.commit()
    deleted = await contracts.prune_telemetry(1)
    assert deleted == 3
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM contract_telemetry WHERE guild_id=1")
        assert int((await cur.fetchone())[0]) == 5
    summary = await contracts.telemetry_summary(1, days=7)
    assert summary.get("rapid_completion") == 5



@pytest.mark.asyncio
async def test_small_server_service_discovery_keeps_public_npc_fallback(tmp_path: Path, monkeypatch) -> None:
    _path, db, contracts = await _stack(tmp_path, monkeypatch)
    await db.ensure_user(1, 20)
    rows = await contracts.list_service_contracts(1, 20, limit=25)
    public_keys = {
        row.source_ref.split(":", 1)[0]
        for row in rows
        if row.source_type == "public"
    }
    assert {"lilla_public_courier", "jani_public_service", "marci_public_courier"}.issubset(public_keys)


def test_w145_mysql_translation_keeps_budget_reconcile_upsert_native() -> None:
    sql = """INSERT INTO contract_reward_budgets(
                 guild_id,budget_key,period_key,limit_amount,reserved_amount,spent_amount,updated_at
             ) VALUES(?,?,?,?,?,?,?)
             ON CONFLICT(guild_id,budget_key,period_key) DO UPDATE SET
                 reserved_amount=excluded.reserved_amount,
                 spent_amount=MAX(spent_amount,excluded.spent_amount),
                 updated_at=excluded.updated_at"""
    translated = aiosqlite.translate_sql_for_mysql(sql)
    assert "ON CONFLICT" not in translated.upper()
    assert "ON DUPLICATE KEY UPDATE" in translated.upper()
    assert "GREATEST(" in translated.upper()
    assert translated.count("%s") == 7
