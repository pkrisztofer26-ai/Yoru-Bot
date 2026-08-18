from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any, AsyncIterator

from mysql.connector.aio import connect as mysql_async_connect

ROOT = Path(__file__).resolve().parent
RESULT_JSON = ROOT / "YORU_MYSQL_GATE_RESULT.json"
RESULT_TXT = ROOT / "YORU_MYSQL_GATE_RESULT.txt"

DB_HOST = os.getenv("YORU_CI_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ["YORU_CI_DB_PORT"])
DB_USER = os.getenv("YORU_CI_DB_USER", "yoru_ci")
DB_PASSWORD = os.getenv("YORU_CI_DB_PASSWORD", "yoru_ci_password")
DB_NAME = os.getenv("YORU_CI_DB_NAME", "yoru_ci_test")
POOL_SIZE = max(2, min(int(os.getenv("YORU_CI_POOL_SIZE", "4")), 8))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kwargs(*, pool_name: str | None = None, pool_size: int | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "database": DB_NAME,
        "charset": "utf8mb4",
        "autocommit": False,
        "connection_timeout": 10,
        "use_pure": True,
        "ssl_disabled": True,
    }
    if pool_name:
        data.update(
            pool_name=pool_name[:64],
            pool_size=int(pool_size or POOL_SIZE),
            pool_reset_session=True,
        )
    return data


@asynccontextmanager
async def connection(*, pool_name: str | None = None, pool_size: int | None = None) -> AsyncIterator[Any]:
    conn = await mysql_async_connect(**kwargs(pool_name=pool_name, pool_size=pool_size))
    try:
        yield conn
    finally:
        try:
            await conn.rollback()
        except Exception:
            pass
        await conn.close()


async def execute(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> None:
    cur = await conn.cursor()
    try:
        await cur.execute(sql, params)
    finally:
        await cur.close()


async def fetchone(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    cur = await conn.cursor()
    try:
        await cur.execute(sql, params)
        row = await cur.fetchone()
        return tuple(row) if row is not None else None
    finally:
        await cur.close()


async def fetchall(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    cur = await conn.cursor()
    try:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
        return [tuple(row) for row in rows]
    finally:
        await cur.close()


async def create_tables(kv: str, accounts: str) -> None:
    async with connection() as conn:
        await execute(conn, f"CREATE TABLE `{kv}` (id BIGINT PRIMARY KEY, value BIGINT NOT NULL) ENGINE=InnoDB")
        await execute(conn, f"CREATE TABLE `{accounts}` (id BIGINT PRIMARY KEY, balance BIGINT NOT NULL) ENGINE=InnoDB")
        await conn.commit()


async def drop_tables(kv: str, accounts: str) -> None:
    async with connection() as conn:
        await execute(conn, f"DROP TABLE IF EXISTS `{accounts}`")
        await execute(conn, f"DROP TABLE IF EXISTS `{kv}`")
        await conn.commit()


async def test_server_identity() -> dict[str, Any]:
    async with connection() as conn:
        version = await fetchone(conn, "SELECT VERSION()")
        engine = await fetchone(conn, "SELECT @@default_storage_engine")
    if not version or not engine:
        raise AssertionError("could not read MariaDB identity")
    if str(engine[0]).lower() != "innodb":
        raise AssertionError(f"expected InnoDB default engine, got {engine[0]!r}")
    return {"server_version": str(version[0]), "default_storage_engine": str(engine[0])}


async def test_commit_rollback(kv: str) -> dict[str, Any]:
    async with connection() as conn:
        await execute(conn, f"INSERT INTO `{kv}` (id, value) VALUES (1, 100)")
        await conn.commit()
        await execute(conn, f"UPDATE `{kv}` SET value=200 WHERE id=1")
        await conn.rollback()
        row = await fetchone(conn, f"SELECT value FROM `{kv}` WHERE id=1")
        if row != (100,):
            raise AssertionError(f"rollback failed: {row!r}")
        await execute(conn, f"UPDATE `{kv}` SET value=300 WHERE id=1")
        await conn.commit()
        row = await fetchone(conn, f"SELECT value FROM `{kv}` WHERE id=1")
        if row != (300,):
            raise AssertionError(f"commit failed: {row!r}")
    return {"rollback_value": 100, "commit_value": 300}


async def test_legacy_writer_lock(kv: str, suffix: str) -> dict[str, Any]:
    lock_name = f"yoru-v372-ci-writer-{suffix}"[:64]
    async with connection() as conn:
        await execute(conn, f"INSERT INTO `{kv}` (id, value) VALUES (2, 0)")
        await conn.commit()

    waits: dict[str, float] = {}

    async def writer(name: str, delay: float, hold: float) -> None:
        await asyncio.sleep(delay)
        async with connection() as conn:
            started = time.perf_counter()
            row = await fetchone(conn, "SELECT GET_LOCK(%s, 5)", (lock_name,))
            waits[name] = (time.perf_counter() - started) * 1000.0
            if row != (1,):
                raise AssertionError(f"{name}: GET_LOCK failed: {row!r}")
            try:
                await execute(conn, f"UPDATE `{kv}` SET value=value+1 WHERE id=2")
                await asyncio.sleep(hold)
                await conn.commit()
            finally:
                await fetchone(conn, "SELECT RELEASE_LOCK(%s)", (lock_name,))

    await asyncio.gather(writer("A", 0.0, 0.22), writer("B", 0.03, 0.01))
    async with connection() as conn:
        row = await fetchone(conn, f"SELECT value FROM `{kv}` WHERE id=2")
    if row != (2,):
        raise AssertionError(f"writer serialization final value invalid: {row!r}")
    if waits.get("B", 0.0) < 120.0:
        raise AssertionError(f"second writer did not visibly wait for advisory lock: {waits!r}")
    return {"final_value": 2, "writer_wait_ms": {k: round(v, 3) for k, v in waits.items()}}


async def test_pool_bounded_release(kv: str, suffix: str) -> dict[str, Any]:
    pool_name = f"yoru-v372-ci-pool-{suffix}"[:64]
    semaphore = asyncio.Semaphore(POOL_SIZE)
    counter_lock = asyncio.Lock()
    active = 0
    peak = 0

    async def worker(index: int) -> None:
        nonlocal active, peak
        async with semaphore:
            async with connection(pool_name=pool_name, pool_size=POOL_SIZE) as conn:
                async with counter_lock:
                    active += 1
                    peak = max(peak, active)
                try:
                    row = await fetchone(conn, f"SELECT value FROM `{kv}` WHERE id=1")
                    if row != (300,):
                        raise AssertionError(f"pool worker {index} read invalid row: {row!r}")
                    await asyncio.sleep(0.025)
                finally:
                    async with counter_lock:
                        active -= 1

    started = time.perf_counter()
    await asyncio.gather(*(worker(i) for i in range(24)))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if peak > POOL_SIZE or active != 0:
        raise AssertionError(f"pool bounds/lease release failed: peak={peak}, active={active}")

    await asyncio.gather(*(worker(i) for i in range(8)))
    if active != 0:
        raise AssertionError(f"pooled leases remained active after second wave: {active}")
    return {"workers": 32, "pool_size": POOL_SIZE, "peak_active": peak, "active_after": active, "elapsed_ms_first_wave": round(elapsed_ms, 3)}


async def test_native_row_lock_transfer(accounts: str) -> dict[str, Any]:
    async with connection() as conn:
        for account_id in range(1, 5):
            await execute(conn, f"INSERT INTO `{accounts}` (id, balance) VALUES (%s, %s)", (account_id, 1000))
        await conn.commit()

    sem = asyncio.Semaphore(8)
    transfers = [(1, 2, 7), (2, 3, 5), (3, 4, 3), (4, 1, 2)] * 20

    async def transfer(src: int, dst: int, amount: int) -> None:
        async with sem:
            async with connection() as conn:
                try:
                    first, second = sorted((src, dst))
                    rows = await fetchall(
                        conn,
                        f"SELECT id, balance FROM `{accounts}` WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
                        (first, second),
                    )
                    balances = {int(row[0]): int(row[1]) for row in rows}
                    if len(balances) != 2:
                        raise AssertionError("row-lock transfer lost an account row")
                    if balances[src] < amount:
                        await conn.rollback()
                        return
                    await execute(conn, f"UPDATE `{accounts}` SET balance=balance-%s WHERE id=%s", (amount, src))
                    await execute(conn, f"UPDATE `{accounts}` SET balance=balance+%s WHERE id=%s", (amount, dst))
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise

    started = time.perf_counter()
    await asyncio.gather(*(transfer(*item) for item in transfers))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    async with connection() as conn:
        rows = await fetchall(conn, f"SELECT id, balance FROM `{accounts}` ORDER BY id")
    balances = {int(row[0]): int(row[1]) for row in rows}
    total = sum(balances.values())
    if total != 4000:
        raise AssertionError(f"row-lock transfer did not conserve money: {balances!r}")
    if min(balances.values()) < 0:
        raise AssertionError(f"row-lock transfer produced negative balance: {balances!r}")
    return {"transfers": len(transfers), "elapsed_ms": round(elapsed_ms, 3), "final_balances": balances, "conserved_total": total, "negative_balance": False}


async def profile_unrelated_write_concurrency(kv: str, suffix: str) -> dict[str, Any]:
    lock_name = f"yoru-v372-ci-profile-{suffix}"[:64]
    async with connection() as conn:
        for row_id in range(10, 18):
            await execute(conn, f"INSERT INTO `{kv}` (id, value) VALUES (%s, 0)", (row_id,))
        await conn.commit()

    async def legacy_writer(row_id: int) -> None:
        async with connection() as conn:
            locked = await fetchone(conn, "SELECT GET_LOCK(%s, 5)", (lock_name,))
            if locked != (1,):
                raise AssertionError("profile GET_LOCK failed")
            try:
                await execute(conn, f"UPDATE `{kv}` SET value=value+1 WHERE id=%s", (row_id,))
                await asyncio.sleep(0.04)
                await conn.commit()
            finally:
                await fetchone(conn, "SELECT RELEASE_LOCK(%s)", (lock_name,))

    started = time.perf_counter()
    await asyncio.gather(*(legacy_writer(i) for i in range(10, 18)))
    legacy_ms = (time.perf_counter() - started) * 1000.0

    async def native_writer(row_id: int) -> None:
        async with connection() as conn:
            try:
                row = await fetchone(conn, f"SELECT value FROM `{kv}` WHERE id=%s FOR UPDATE", (row_id,))
                if row is None:
                    raise AssertionError("profile row disappeared")
                await execute(conn, f"UPDATE `{kv}` SET value=value+1 WHERE id=%s", (row_id,))
                await asyncio.sleep(0.04)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    started = time.perf_counter()
    await asyncio.gather(*(native_writer(i) for i in range(10, 18)))
    native_ms = (time.perf_counter() - started) * 1000.0
    return {
        "writers": 8,
        "hold_ms_each": 40,
        "legacy_global_lock_elapsed_ms": round(legacy_ms, 3),
        "native_independent_row_lock_elapsed_ms": round(native_ms, 3),
        "legacy_to_native_ratio": round((legacy_ms / native_ms) if native_ms else 0.0, 3),
        "note": "informational only; the v3.72 global writer lock is not changed by this gate",
    }


async def run_step(result: dict[str, Any], name: str, awaitable: Any) -> None:
    started = time.perf_counter()
    try:
        details = await awaitable
        result["tests"][name] = {"status": "PASS", "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3), "details": details}
    except Exception as exc:
        result["tests"][name] = {"status": "FAIL", "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3), "error_type": type(exc).__name__, "error": str(exc)}
        raise


def report_text(result: dict[str, Any]) -> str:
    lines = [
        "YORU v3.72.0 NATIVE MARIADB / INNODB CI GATE",
        f"Status: {result.get('status', 'FAIL')}",
        f"Started: {result.get('started_at', '-')}",
        f"Finished: {result.get('finished_at', '-')}",
        "",
    ]
    for name, row in result.get("tests", {}).items():
        lines.append(f"[{row.get('status', '?')}] {name} - {row.get('elapsed_ms', 0)} ms")
        details = row.get("details")
        if isinstance(details, dict):
            for key, value in details.items():
                lines.append(f"    {key}: {value}")
        if row.get("error"):
            lines.append(f"    {row.get('error_type')}: {row.get('error')}")
    if result.get("error"):
        lines.extend(["", f"ERROR: {result.get('error_type')}: {result.get('error')}"])
    lines.extend(["", "This CI gate uses only UUID-named temporary tables in an ephemeral GitHub Actions MariaDB service.", "No PebbleHost/live credentials are used or written to the result files."])
    return "\n".join(lines) + "\n"


def write_result(result: dict[str, Any]) -> None:
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    RESULT_TXT.write_text(report_text(result), encoding="utf-8")


async def main_async() -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:12]
    kv = f"yoru_v372_ci_{suffix}_kv"
    accounts = f"yoru_v372_ci_{suffix}_acct"
    result: dict[str, Any] = {"status": "FAIL", "started_at": now(), "tests": {}, "temporary_tables": [kv, accounts]}
    await create_tables(kv, accounts)
    try:
        await run_step(result, "server_identity_innodb", test_server_identity())
        await run_step(result, "commit_rollback", test_commit_rollback(kv))
        await run_step(result, "legacy_writer_lock", test_legacy_writer_lock(kv, suffix))
        await run_step(result, "pool_bounded_release", test_pool_bounded_release(kv, suffix))
        await run_step(result, "native_row_lock_transfer_candidate", test_native_row_lock_transfer(accounts))
        await run_step(result, "unrelated_write_concurrency_profile", profile_unrelated_write_concurrency(kv, suffix))
        result["status"] = "PASS"
        return result
    finally:
        try:
            await drop_tables(kv, accounts)
        finally:
            result["finished_at"] = now()


def main() -> int:
    result: dict[str, Any] = {"status": "FAIL", "started_at": now(), "tests": {}}
    try:
        result = asyncio.run(main_async())
        return_code = 0
    except Exception as exc:
        result["finished_at"] = now()
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        return_code = 2
    finally:
        write_result(result)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
