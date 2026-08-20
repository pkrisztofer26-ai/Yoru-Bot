from __future__ import annotations

"""Disposable native MariaDB/InnoDB closure gate for Phase 4 contracts.

This suite never auto-discovers live credentials. It runs only when an operator
supplies YORU_TEST_MYSQL_* and confirms DISPOSABLE_SCHEMA. The selected database
name must visibly be test/qa/staging/sandbox and must not equal MYSQL_DATABASE.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
import re
import uuid

import pytest
import pytest_asyncio

from app import contract_config as cfg
from app import db_backend
from app.database import Database
from app.services.contracts import ContractService, ObjectiveSpec


_REQUIRED = (
    "YORU_TEST_MYSQL_HOST",
    "YORU_TEST_MYSQL_USER",
    "YORU_TEST_MYSQL_PASSWORD",
    "YORU_TEST_MYSQL_DATABASE",
)


def _credentials_or_skip() -> dict[str, str]:
    if os.getenv("YORU_TEST_MYSQL_CONFIRM", "") != "DISPOSABLE_SCHEMA":
        pytest.skip("Disposable MariaDB contract DB not explicitly confirmed")
    missing = [name for name in _REQUIRED if not os.getenv(name, "").strip()]
    if missing:
        pytest.skip("Disposable MariaDB credentials missing: " + ", ".join(missing))
    database = os.environ["YORU_TEST_MYSQL_DATABASE"].strip()
    if not re.search(r"(?:test|testing|qa|staging|sandbox)", database, flags=re.I):
        pytest.fail("Refusing native contract tests: database name is not visibly disposable")
    live_database = os.getenv("MYSQL_DATABASE", "").strip()
    if live_database and live_database.casefold() == database.casefold():
        pytest.fail("Refusing native contract tests against MYSQL_DATABASE/live schema")
    return {
        "host": os.environ["YORU_TEST_MYSQL_HOST"].strip(),
        "port": os.getenv("YORU_TEST_MYSQL_PORT", "3306").strip() or "3306",
        "user": os.environ["YORU_TEST_MYSQL_USER"].strip(),
        "password": os.environ["YORU_TEST_MYSQL_PASSWORD"],
        "database": database,
    }


class NativeContractDatabase(Database):
    async def get_starting_balance(self, guild_id: int, *, db=None) -> int:  # type: ignore[override]
        return int(self.starting_balance)


_DROP_TABLES = (
    "business_delivery_history",
    "contract_telemetry",
    "contract_source_state",
    "contract_reward_budgets",
    "item_transfer_history",
    "contract_event_claims",
    "contract_history",
    "contract_events",
    "contract_objectives",
    "contracts",
    "transactions",
    "user_statistics",
    "users",
)


@pytest_asyncio.fixture
async def native_contract_stack(monkeypatch: pytest.MonkeyPatch):
    creds = _credentials_or_skip()
    suffix = uuid.uuid4().hex[:10]
    monkeypatch.setenv("YORU_DB_BACKEND", "mysql")
    monkeypatch.setenv("MYSQL_HOST", creds["host"])
    monkeypatch.setenv("MYSQL_PORT", creds["port"])
    monkeypatch.setenv("MYSQL_USER", creds["user"])
    monkeypatch.setenv("MYSQL_PASSWORD", creds["password"])
    monkeypatch.setenv("MYSQL_DATABASE", creds["database"])
    monkeypatch.setenv("MYSQL_POOL_NAME", f"yoru-v3754-{suffix}")
    monkeypatch.setenv("MYSQL_POOL_SIZE", "8")
    monkeypatch.setenv("MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("MYSQL_LEGACY_WRITE_LOCK", f"yoru-v3754-contract-{suffix}")
    monkeypatch.setenv("MYSQL_LEGACY_LOCK_TIMEOUT", "8")
    db_backend._MYSQL_POOL_SEMAPHORE = None
    db_backend._MYSQL_POOL_LOOP = None

    db = NativeContractDatabase("native-contract-cert", 10_000_000)
    async with db_backend.connect(None) as conn:
        for table in _DROP_TABLES:
            cur = await conn._run_raw(
                "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s LIMIT 1",
                (creds["database"], table),
            )
            if await cur.fetchone() is not None:
                pytest.fail(f"Disposable schema is not empty; found table {table}")
        await db_backend.execute_backend_ddl(
            conn,
            sqlite_sql="CREATE TABLE users(guild_id INTEGER,user_id INTEGER,wallet INTEGER,bank INTEGER,created_at TEXT)",
            mysql_sql="""CREATE TABLE users(
                guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                wallet DECIMAL(65,0) NOT NULL DEFAULT 0,bank DECIMAL(65,0) NOT NULL DEFAULT 0,
                money_lost DECIMAL(65,0) NOT NULL DEFAULT 0,money_earned DECIMAL(65,0) NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,PRIMARY KEY(guild_id,user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        )
        await db_backend.execute_backend_ddl(
            conn,
            sqlite_sql="CREATE TABLE transactions(id INTEGER PRIMARY KEY,guild_id INTEGER,user_id INTEGER,amount INTEGER,reason TEXT,created_at TEXT)",
            mysql_sql="""CREATE TABLE transactions(
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
                amount DECIMAL(65,0) NOT NULL,reason VARCHAR(190) NOT NULL,created_at VARCHAR(64) NOT NULL,PRIMARY KEY(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        )
        await db_backend.execute_backend_ddl(
            conn,
            sqlite_sql="CREATE TABLE user_statistics(guild_id INTEGER,user_id INTEGER,stat_name TEXT,value INTEGER,updated_at TEXT)",
            mysql_sql="""CREATE TABLE user_statistics(
                guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,stat_name VARCHAR(96) NOT NULL,
                value DECIMAL(65,0) NOT NULL DEFAULT 0,updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(guild_id,user_id,stat_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        )
        await db._ensure_contract_economy_schema(conn)
        await conn.commit()

    contracts = ContractService(db)
    try:
        yield db, contracts
    finally:
        async with db_backend.connect(None) as conn:
            await conn._run_raw("SET FOREIGN_KEY_CHECKS=0")
            try:
                for table in _DROP_TABLES:
                    await conn._run_raw(f"DROP TABLE IF EXISTS `{table}`")
                await conn.commit()
            finally:
                await conn._run_raw("SET FOREIGN_KEY_CHECKS=1")


async def _ensure(db: NativeContractDatabase, *users: int) -> None:
    for user_id in users:
        await db.ensure_user(1, user_id)


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()


@pytest.mark.asyncio
async def test_native_accept_cancel_cross_connection_race(native_contract_stack) -> None:
    db, contracts = native_contract_stack
    await _ensure(db, 10, 20)
    before = await db.get_balance(1, 10)
    job = await contracts.create_player_contract(
        1, 10, title="Native accept-cancel", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )

    async def accept():
        try:
            await contracts.accept_contract(1, job.contract_id, 20)
        except ValueError:
            pass

    async def cancel():
        try:
            await contracts.cancel_open_contract(1, job.contract_id, 10)
        except ValueError:
            pass

    await asyncio.wait_for(asyncio.gather(accept(), cancel()), timeout=15)
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status in {"active", "cancelled"}
    balance = await db.get_balance(1, 10)
    if snap.status == "cancelled":
        assert balance == before and snap.escrow_state == "refunded"
    else:
        assert sum(before) - sum(balance) == 100_000 and snap.escrow_state == "held"


@pytest.mark.asyncio
async def test_native_same_event_claim_and_settlement_are_idempotent(native_contract_stack) -> None:
    db, contracts = native_contract_stack
    await _ensure(db, 10, 20)
    job = await contracts.create_player_contract(
        1, 10, title="Native event claim", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    before = await db.get_balance(1, 20)
    results = await asyncio.wait_for(asyncio.gather(
        contracts.record_matching_city_delivery(1, 20, travel_id=9001, from_city_key="miskolc", to_city_key="eger"),
        contracts.record_matching_city_delivery(1, 20, travel_id=9001, from_city_key="miskolc", to_city_key="eger"),
    ), timeout=20)
    assert sum(bool(r and r.progressed) for r in results) == 1
    assert sum(bool(r and r.replay) for r in results) == 1
    after = await db.get_balance(1, 20)
    assert after[0] - before[0] == 100_000


@pytest.mark.asyncio
async def test_native_reward_budget_reserve_spend_once(native_contract_stack) -> None:
    db, contracts = native_contract_stack
    await _ensure(db, 20)
    source = cfg.SOURCE_BY_KEY["lilla_public_courier"]
    job = await contracts.create_system_contract(
        1, source=source, period_key="2099-01-01",
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    before = await db.get_balance(1, 20)
    result = await contracts.record_matching_city_delivery(
        1, 20, travel_id=9002, from_city_key="miskolc", to_city_key="eger"
    )
    assert result is not None and result.settled
    replay = await contracts.record_matching_city_delivery(
        1, 20, travel_id=9002, from_city_key="miskolc", to_city_key="eger"
    )
    assert replay is not None and replay.replay
    after = await db.get_balance(1, 20)
    assert after[0] - before[0] == job.reward_amount
    async with db_backend.connect(None) as conn:
        cur = await conn.execute(
            "SELECT reserved_amount,spent_amount FROM contract_reward_budgets WHERE guild_id=? AND budget_key=? AND period_key=?",
            (1, source.budget_key, "2099-01-01"),
        )
        reserved, spent = map(int, await cur.fetchone())
    assert reserved == 0 and spent == job.reward_amount


@pytest.mark.asyncio
async def test_native_restart_recovery_settles_complete_before_expiry(native_contract_stack) -> None:
    db, contracts = native_contract_stack
    await _ensure(db, 10, 20)
    job = await contracts.create_player_contract(
        1, 10, title="Native restart recovery", reward_amount=100_000, expires_at=_future(),
        objectives=[ObjectiveSpec("route", "city_delivery", "miskolc:eger")],
    )
    await contracts.accept_contract(1, job.contract_id, 20)
    await contracts.record_city_delivery(
        1, job.contract_id, 20, event_key="native:restart:9003", route_key="miskolc:eger"
    )
    older = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    async with db_backend.connect(None) as conn:
        await conn.execute("UPDATE contract_objectives SET updated_at=? WHERE contract_id=?", (older, job.contract_id))
        await conn.execute("UPDATE contracts SET expires_at=? WHERE contract_id=?", (expired, job.contract_id))
        await conn.commit()
    report = await contracts.recover_restart_state(1)
    assert report.ready_settled == 1 and report.expired == 0
    snap = await contracts.get_contract(1, job.contract_id)
    assert snap is not None and snap.status == "settled"
