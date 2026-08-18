from __future__ import annotations

import asyncio
import base64
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import types
import uuid
from typing import Any, Awaitable

from mysql.connector.aio import connect as mysql_async_connect

HERE = Path(__file__).resolve().parent
HEIST_PARTS = [HERE / f"w10_heist_source_{i:02d}.b64" for i in range(2)]
HEIST_SCHEMA_B64 = HERE / "w10_heist_schema.b64"
RESULT_JSON = HERE / "YORU_W10_HEIST_CONTRACT_RESULT.json"
RESULT_TXT = HERE / "YORU_W10_HEIST_CONTRACT_RESULT.txt"
HEIST_ZIP_SHA256 = "d79bd3971beda36e44b3665fad262492daec5a2dc750832d294cebbf68e7ae6f"
HEIST_SCHEMA_SHA256 = "c9a698e0a03b24aa2df44e8dd152b189247ad58bd33413d6f7a5d8a896792a6e"
HEIST_FILE_SHA256 = "a565ac17d20c9abe68bdfdb4b0329b92a4f055194ac1a0f53383879f77c71751"
HEIST_CONFIG_SHA256 = "ecc49d925128030ac4632c6abb43a89a059e3e3aa5ff649c085bc9f56539a977"

VEHICLE_DDL = """
CREATE TABLE IF NOT EXISTS heist_vehicle_choices (
    guild_id BIGINT UNSIGNED NOT NULL,
    lobby_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    vehicle_id BIGINT UNSIGNED NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (guild_id, lobby_id, user_id),
    KEY idx_heist_vehicle_user (guild_id, user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""".strip()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mysql_kwargs() -> dict[str, Any]:
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.environ["MYSQL_DATABASE"],
        "autocommit": False,
        "charset": "utf8mb4",
        "connection_timeout": 10,
        "use_pure": True,
        "ssl_disabled": True,
    }


async def bootstrap_heist_schema() -> None:
    raw = base64.b64decode(HEIST_SCHEMA_B64.read_text(encoding="ascii"))
    actual = sha256(raw)
    if actual != HEIST_SCHEMA_SHA256:
        raise AssertionError(f"Heist schema fixture SHA mismatch: {actual}")
    statements = [s.strip() for s in raw.decode("utf-8").split(";") if s.strip()]
    statements.append(VEHICLE_DDL)
    conn = await mysql_async_connect(**mysql_kwargs())
    try:
        cur = await conn.cursor()
        try:
            for statement in statements:
                await cur.execute(statement)
            await conn.commit()
        finally:
            await cur.close()
    finally:
        await conn.close()


def overlay_and_verify_heist(src: Path) -> None:
    encoded = "".join(p.read_text(encoding="ascii") for p in HEIST_PARTS)
    raw = base64.b64decode(encoded)
    actual = sha256(raw)
    if actual != HEIST_ZIP_SHA256:
        raise AssertionError(f"Heist source snapshot SHA mismatch: {actual}")
    archive = src.parent / "heist-source.zip"
    archive.write_bytes(raw)
    shutil.unpack_archive(str(archive), str(src))
    services = src / "app" / "services"
    services.mkdir(parents=True, exist_ok=True)
    (services / "__init__.py").touch(exist_ok=True)
    checks = {
        src / "app" / "services" / "heist.py": HEIST_FILE_SHA256,
        src / "app" / "heist_config.py": HEIST_CONFIG_SHA256,
    }
    for path, expected in checks.items():
        actual_file = sha256(path.read_bytes())
        if actual_file != expected:
            raise AssertionError(f"Heist source hash mismatch for {path.name}: {actual_file}")


def install_support_stubs() -> None:
    server_settings = types.ModuleType("app.services.server_settings")

    class ServerSettingsService:
        def __init__(self, database: Any) -> None:
            self.database = database

        async def get_int(self, guild_id: int, key: str, default: int = 0) -> int:
            return int(default)

        async def get_bool(self, guild_id: int, key: str, default: bool = False) -> bool:
            return bool(default)

        async def set_int(self, guild_id: int, key: str, value: int) -> None:
            return None

        async def set_bool(self, guild_id: int, key: str, value: bool) -> None:
            return None

    server_settings.ServerSettingsService = ServerSettingsService
    sys.modules["app.services.server_settings"] = server_settings

    ui = types.ModuleType("app.ui")
    ui.money = lambda value: f"{int(value):,}"
    sys.modules["app.ui"] = ui

    text_hu = types.ModuleType("app.text_hu")
    text_hu.format_hu_relative = lambda value: str(value)
    sys.modules["app.text_hu"] = text_hu


class DummyStats:
    async def increment(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def add(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def set_max(self, *args: Any, **kwargs: Any) -> None:
        return None


async def backend_row(backend: Any, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    async with backend.connect("unused") as conn:
        cur = await conn.execute(sql, params)
        value = await cur.fetchone()
        return tuple(value) if value is not None else None


async def backend_rows(backend: Any, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    async with backend.connect("unused") as conn:
        cur = await conn.execute(sql, params)
        values = await cur.fetchall()
        return [tuple(v) for v in values]


async def seed_case(db: Any, backend: Any, gid: int, lobby_id: int, run_id: int, users: tuple[int, int], reward: int = 1_000_000) -> dict[str, Any]:
    now = utcnow()
    for uid in users:
        await db.ensure_user(gid, uid)
        await db.set_wallet(gid, uid, 100_000, "w10_heist_seed")
    phase_results = [
        {"phase": 0, "passed": True},
        {"phase": 1, "passed": True},
        {"phase": 2, "passed": True},
    ]
    snapshot = {
        str(users[0]): {"police_points": 0, "vehicle": {"quality": 0}},
        str(users[1]): {"police_points": 0, "vehicle": {"quality": 0}},
    }
    async with backend.connect("unused") as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute(
            "INSERT INTO heist_lobbies(lobby_id,guild_id,leader_id,target_key,status,phase,created_at,expires_at,started_at,resolved_at) VALUES(?,?,?,?,?,?,?,?,?,NULL)",
            (lobby_id, gid, users[0], "miskolc_hollo", "running", 2, now, "2099-12-31T23:59:59+00:00", now),
        )
        for uid, cut, role in ((users[0], 60, "leader"), (users[1], 40, "support")):
            await conn.execute(
                "INSERT INTO heist_lobby_members(guild_id,lobby_id,user_id,status,role_key,cut_percent,cut_accepted,gear_key,joined_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (gid, lobby_id, uid, "accepted", role, cut, 1, None, now),
            )
            await conn.execute(
                "INSERT INTO heist_vehicle_choices(guild_id,lobby_id,user_id,vehicle_id,updated_at) VALUES(?,?,?,?,?)",
                (gid, lobby_id, uid, 9000 + uid, now),
            )
        await conn.execute(
            "INSERT INTO heist_runs(run_id,guild_id,lobby_id,target_key,status,phase,reward_pool,phase_results,member_snapshot,success,total_reward,started_at,resolved_at) VALUES(?,?,?,?,?,?,?,?,?,NULL,0,?,NULL)",
            (run_id, gid, lobby_id, "miskolc_hollo", "running", 2, reward, json.dumps(phase_results), json.dumps(snapshot), now),
        )
        await conn.commit()
    return {
        "run_id": run_id,
        "guild_id": gid,
        "lobby_id": lobby_id,
        "target_key": "miskolc_hollo",
        "status": "running",
        "phase": 2,
        "reward_pool": reward,
        "phase_results": phase_results,
        "member_snapshot": snapshot,
        "started_at": now,
    }


async def assert_success_state(db: Any, backend: Any, gid: int, lobby_id: int, run_id: int, users: tuple[int, int]) -> dict[str, Any]:
    wallets = {uid: (await db.get_balance(gid, uid))[0] for uid in users}
    expected = {users[0]: 700_000, users[1]: 500_000}
    if wallets != expected:
        raise AssertionError(f"Heist payout mismatch: {wallets!r} != {expected!r}")
    txs = await backend_rows(
        backend,
        "SELECT user_id,amount,reason FROM transactions WHERE guild_id=? AND reason LIKE ? ORDER BY user_id",
        (gid, f"heist_payout:{lobby_id}:%"),
    )
    if len(txs) != 2 or sum(int(r[1]) for r in txs) != 1_000_000:
        raise AssertionError(f"Heist transaction ledger mismatch: {txs!r}")
    run_row = await backend_row(backend, "SELECT status,success,total_reward,phase FROM heist_runs WHERE guild_id=? AND run_id=?", (gid, run_id))
    lobby_row = await backend_row(backend, "SELECT status,phase FROM heist_lobbies WHERE guild_id=? AND lobby_id=?", (gid, lobby_id))
    vehicle_count = await backend_row(backend, "SELECT COUNT(*) FROM heist_vehicle_choices WHERE guild_id=? AND lobby_id=?", (gid, lobby_id))
    earned = await backend_rows(backend, "SELECT user_id,value FROM user_statistics WHERE guild_id=? AND stat_name='earned' ORDER BY user_id", (gid,))
    peaks = await backend_rows(backend, "SELECT user_id,value FROM user_statistics WHERE guild_id=? AND stat_name='wallet_peak' ORDER BY user_id", (gid,))
    if run_row is None or run_row[0] != "success" or int(run_row[1]) != 1 or int(run_row[2]) != 1_000_000 or int(run_row[3]) != 3:
        raise AssertionError(f"Heist run finalize mismatch: {run_row!r}")
    if lobby_row is None or lobby_row[0] != "finished" or int(lobby_row[1]) != 3:
        raise AssertionError(f"Heist lobby finalize mismatch: {lobby_row!r}")
    if vehicle_count != (0,):
        raise AssertionError(f"Heist vehicle choices were not cleared: {vehicle_count!r}")
    if {int(u): int(v) for u, v in earned} != {users[0]: 600_000, users[1]: 400_000}:
        raise AssertionError(f"Heist earned stats mismatch: {earned!r}")
    if {int(u): int(v) for u, v in peaks} != expected:
        raise AssertionError(f"Heist wallet peak mismatch: {peaks!r}")
    return {
        "wallets": wallets,
        "transaction_rows": len(txs),
        "ledger_payout_total": sum(int(r[1]) for r in txs),
        "run_status": run_row[0],
        "lobby_status": lobby_row[0],
        "vehicle_choices_after": 0,
    }


async def success_contract(service: Any, db: Any, backend: Any, gid: int, lobby_id: int, run_id: int, users: tuple[int, int]) -> dict[str, Any]:
    run = await seed_case(db, backend, gid, lobby_id, run_id, users)
    result = await service._resolve_run(run)
    if not bool(result.get("success")) or int(result.get("total_reward", -1)) != 1_000_000:
        raise AssertionError(f"Unexpected Heist success result: {result!r}")
    state = await assert_success_state(db, backend, gid, lobby_id, run_id, users)
    state["result_total_reward"] = int(result["total_reward"])
    return state


async def exactly_once_contract(service: Any, db: Any, backend: Any, gid: int, lobby_id: int, run_id: int, users: tuple[int, int]) -> dict[str, Any]:
    run = await seed_case(db, backend, gid, lobby_id, run_id, users)
    outcomes = await asyncio.gather(service._resolve_run(dict(run)), service._resolve_run(dict(run)), return_exceptions=True)
    successes = [x for x in outcomes if isinstance(x, dict)]
    failures = [x for x in outcomes if isinstance(x, BaseException)]
    if len(successes) != 1 or len(failures) != 1 or not isinstance(failures[0], ValueError):
        raise AssertionError(f"Heist concurrent resolve outcome mismatch: {outcomes!r}")
    state = await assert_success_state(db, backend, gid, lobby_id, run_id, users)
    state.update({"parallel_calls": 2, "authoritative_resolves": 1, "rejected_replays": 1, "replay_error": str(failures[0])})
    return state


class FaultConnection:
    def __init__(self, inner: Any, trip: dict[str, bool]) -> None:
        self._inner = inner
        self._trip = trip

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def execute(self, sql: str, parameters: tuple[Any, ...] | list[Any] = ()) -> Any:
        cur = await self._inner.execute(sql, parameters)
        normalized = " ".join(str(sql).split()).lower()
        if not self._trip["done"] and normalized.startswith("update users set wallet=?"):
            self._trip["done"] = True
            raise RuntimeError("W10 injected failure after first Heist wallet UPDATE")
        return cur


class FaultConnectContext(AbstractAsyncContextManager[Any]):
    def __init__(self, original_factory: Any, trip: dict[str, bool], *args: Any, **kwargs: Any) -> None:
        self._ctx = original_factory(*args, **kwargs)
        self._trip = trip

    async def __aenter__(self) -> Any:
        inner = await self._ctx.__aenter__()
        return FaultConnection(inner, self._trip)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return await self._ctx.__aexit__(exc_type, exc, tb)


async def rollback_contract(service: Any, heist_module: Any, db: Any, backend: Any, gid: int, lobby_id: int, run_id: int, users: tuple[int, int]) -> dict[str, Any]:
    run = await seed_case(db, backend, gid, lobby_id, run_id, users)
    original_connect = backend.connect
    trip = {"done": False}

    def faulty_connect(*args: Any, **kwargs: Any) -> FaultConnectContext:
        return FaultConnectContext(original_connect, trip, *args, **kwargs)

    backend.connect = faulty_connect
    try:
        try:
            await service._resolve_run(run)
            raise AssertionError("Injected Heist failure did not abort settlement")
        except RuntimeError as exc:
            if "W10 injected failure" not in str(exc):
                raise
    finally:
        backend.connect = original_connect

    if not trip["done"]:
        raise AssertionError("Injected Heist wallet failure was never reached")
    wallets = {uid: (await db.get_balance(gid, uid))[0] for uid in users}
    if wallets != {users[0]: 100_000, users[1]: 100_000}:
        raise AssertionError(f"Heist rollback left partial wallet writes: {wallets!r}")
    run_row = await backend_row(backend, "SELECT status,phase,success,total_reward FROM heist_runs WHERE guild_id=? AND run_id=?", (gid, run_id))
    lobby_row = await backend_row(backend, "SELECT status,phase FROM heist_lobbies WHERE guild_id=? AND lobby_id=?", (gid, lobby_id))
    tx_count = await backend_row(backend, "SELECT COUNT(*) FROM transactions WHERE guild_id=? AND reason LIKE ?", (gid, f"heist_payout:{lobby_id}:%"))
    vehicle_count = await backend_row(backend, "SELECT COUNT(*) FROM heist_vehicle_choices WHERE guild_id=? AND lobby_id=?", (gid, lobby_id))
    stat_count = await backend_row(backend, "SELECT COUNT(*) FROM user_statistics WHERE guild_id=? AND stat_name IN ('earned','wallet_peak')", (gid,))
    if run_row is None or run_row[0] != "running" or int(run_row[1]) != 2 or run_row[2] is not None or int(run_row[3]) != 0:
        raise AssertionError(f"Heist run claim/finalize was not rolled back: {run_row!r}")
    if lobby_row != ("running", 2):
        raise AssertionError(f"Heist lobby changed despite rollback: {lobby_row!r}")
    if tx_count != (0,) or vehicle_count != (2,) or stat_count != (0,):
        raise AssertionError(f"Heist rollback side effects mismatch: tx={tx_count}, vehicles={vehicle_count}, stats={stat_count}")
    return {
        "injected_after_first_wallet_update": True,
        "wallets_after": wallets,
        "run_status_after": run_row[0],
        "lobby_status_after": lobby_row[0],
        "transaction_rows_after": 0,
        "vehicle_choices_after": 2,
        "authoritative_stats_after": 0,
    }


async def run_test(result: dict[str, Any], name: str, task: Awaitable[dict[str, Any]]) -> None:
    started = time.perf_counter()
    try:
        details = await task
        result["tests"][name] = {"status": "PASS", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "details": details}
    except Exception as exc:
        result["tests"][name] = {"status": "FAIL", "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error_type": type(exc).__name__, "error": str(exc)}
        raise


def render_text(result: dict[str, Any]) -> str:
    lines = [
        "YORU v3.72.0 W10.2 NATIVE HEIST TRANSACTION CONTRACTS",
        f"Status: {result.get('status', 'FAIL')}",
        f"Started: {result.get('started_at', '-')}",
        f"Finished: {result.get('finished_at', '-')}",
        f"Heist source snapshot SHA-256: {HEIST_ZIP_SHA256}",
        "",
    ]
    for name, item in result.get("tests", {}).items():
        lines.append(f"[{item.get('status')}] {name} - {item.get('elapsed_ms')} ms")
        for key, value in (item.get("details") or {}).items():
            lines.append(f"    {key}: {value}")
        if item.get("error"):
            lines.append(f"    {item.get('error_type')}: {item.get('error')}")
    if result.get("error"):
        lines.extend(["", f"ERROR: {result.get('error_type')}: {result.get('error')}"])
    lines.extend([
        "",
        "Scope: actual v3.72 HeistService._resolve_run + actual v3.72 Database/db_backend on ephemeral MariaDB/InnoDB.",
        "Only non-authoritative Discord/settings/text support dependencies are stubbed.",
        "The production/global compatibility writer lock remains enabled.",
        "No live/PebbleHost credentials or data are used.",
    ])
    return "\n".join(lines) + "\n"


def write_result(result: dict[str, Any]) -> None:
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    RESULT_TXT.write_text(render_text(result), encoding="utf-8")


async def main_async() -> dict[str, Any]:
    result: dict[str, Any] = {"status": "FAIL", "started_at": utcnow(), "tests": {}, "heist_source_sha256": HEIST_ZIP_SHA256}
    await bootstrap_heist_schema()
    import w10_transaction_contracts

    work = w10_transaction_contracts.extract_and_verify_source()
    src = work / "src"
    result["foundation_source_sha256"] = w10_transaction_contracts.EXPECTED_ZIP_SHA256
    try:
        overlay_and_verify_heist(src)
        install_support_stubs()
        from app.database import Database
        from app import db_backend
        from app.services import heist as heist_module
        from app.services.heist import HeistService

        db = Database("data/w10-heist-unused.db", 75_000)
        service = HeistService(db, DummyStats(), characters=None, vehicles=None, world=None, police=None, bot=None)
        base = 8_000_000_000_000 + int(uuid.uuid4().hex[:7], 16) * 100
        await run_test(result, "heist_success_payout_conservation", success_contract(service, db, db_backend, base, base + 1, base + 2, (101, 102)))
        await run_test(result, "heist_concurrent_exactly_once", exactly_once_contract(service, db, db_backend, base + 10, base + 11, base + 12, (201, 202)))
        await run_test(result, "heist_injected_failure_full_rollback", rollback_contract(service, heist_module, db, db_backend, base + 20, base + 21, base + 22, (301, 302)))
        result["db_backend_metrics"] = db_backend.mysql_runtime_metrics()
        result["status"] = "PASS"
        return result
    finally:
        result["finished_at"] = utcnow()
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    result: dict[str, Any] = {"status": "FAIL", "started_at": utcnow(), "tests": {}, "heist_source_sha256": HEIST_ZIP_SHA256}
    try:
        result = asyncio.run(main_async())
        code = 0
    except Exception as exc:
        result["finished_at"] = utcnow()
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        code = 2
    finally:
        write_result(result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
