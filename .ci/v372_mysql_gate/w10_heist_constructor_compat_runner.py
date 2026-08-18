from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
import traceback
import types
import uuid
from typing import Any

import w10_heist_canonical_runner as canonical

gate = canonical.gate


def install_support_stubs() -> None:
    """Only replace non-authoritative support services required to import Heist."""
    server_settings = types.ModuleType("app.services.server_settings")

    class ServerSettingsService:
        def __init__(self, database: Any) -> None:
            self.database = database

        async def get_int(self, guild_id: int, key: str) -> int | None:
            return None

        async def get_bool(self, guild_id: int, key: str, default: bool = False) -> bool:
            return bool(default)

        async def set_int(self, guild_id: int, key: str, value: int | None) -> None:
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


async def assert_success_state(db, backend, gid, lobby_id, run_id, users):
    wallets = {uid: (await db.get_balance(gid, uid))[0] for uid in users}
    expected = {users[0]: 700_000, users[1]: 500_000}
    if wallets != expected:
        raise AssertionError(f"Heist payout mismatch: {wallets!r} != {expected!r}")

    txs = await gate.backend_rows(
        backend,
        "SELECT user_id,amount,reason FROM transactions WHERE guild_id=? AND reason LIKE ? ORDER BY user_id",
        (gid, f"heist_payout:{lobby_id}:%"),
    )
    if len(txs) != 2 or sum(int(row[1]) for row in txs) != 1_000_000:
        raise AssertionError(f"Heist transaction ledger mismatch: {txs!r}")

    run_row = await gate.backend_row(
        backend,
        "SELECT status,success,total_reward,phase FROM heist_runs WHERE guild_id=? AND run_id=?",
        (gid, run_id),
    )
    lobby_row = await gate.backend_row(
        backend,
        "SELECT status,phase FROM heist_lobbies WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    vehicle_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM heist_vehicle_choices WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    earned = await gate.backend_rows(
        backend,
        "SELECT user_id,value FROM user_statistics WHERE guild_id=? AND stat_name='economy.earned' ORDER BY user_id",
        (gid,),
    )
    peaks = await gate.backend_rows(
        backend,
        "SELECT user_id,value FROM user_statistics WHERE guild_id=? AND stat_name='economy.wallet_peak' ORDER BY user_id",
        (gid,),
    )

    if run_row is None or run_row[0] != "success" or int(run_row[1]) != 1 or int(run_row[2]) != 1_000_000 or int(run_row[3]) != 3:
        raise AssertionError(f"Heist run finalize mismatch: {run_row!r}")
    if lobby_row != ("finished", 3):
        raise AssertionError(f"Heist lobby finalize mismatch: {lobby_row!r}")
    if vehicle_count != (0,):
        raise AssertionError(f"Heist vehicle choices were not cleared: {vehicle_count!r}")
    if {int(uid): int(value) for uid, value in earned} != {users[0]: 600_000, users[1]: 400_000}:
        raise AssertionError(f"Heist earned stats mismatch: {earned!r}")
    if {int(uid): int(value) for uid, value in peaks} != expected:
        raise AssertionError(f"Heist wallet peak mismatch: {peaks!r}")

    return {
        "wallets": wallets,
        "transaction_rows": len(txs),
        "ledger_payout_total": sum(int(row[1]) for row in txs),
        "run_status": run_row[0],
        "lobby_status": lobby_row[0],
        "vehicle_choices_after": 0,
    }


async def success_contract(service, db, backend, gid, lobby_id, run_id, users):
    run = await gate.seed_case(db, backend, gid, lobby_id, run_id, users)
    result = await service._resolve_run(gid, lobby_id, run, list(run["phase_results"]))
    if not bool(result.get("success")) or int(result.get("total_reward", -1)) != 1_000_000:
        raise AssertionError(f"Unexpected Heist success result: {result!r}")
    state = await assert_success_state(db, backend, gid, lobby_id, run_id, users)
    state["result_total_reward"] = int(result["total_reward"])
    return state


async def exactly_once_contract(service, db, backend, gid, lobby_id, run_id, users):
    run = await gate.seed_case(db, backend, gid, lobby_id, run_id, users)
    outcomes = await asyncio.gather(
        service._resolve_run(gid, lobby_id, dict(run), list(run["phase_results"])),
        service._resolve_run(gid, lobby_id, dict(run), list(run["phase_results"])),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if isinstance(item, dict)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    if len(successes) != 1 or len(failures) != 1 or not isinstance(failures[0], ValueError):
        raise AssertionError(f"Heist concurrent resolve outcome mismatch: {outcomes!r}")
    state = await assert_success_state(db, backend, gid, lobby_id, run_id, users)
    state.update(
        parallel_calls=2,
        authoritative_resolves=1,
        rejected_replays=1,
        replay_error=str(failures[0]),
    )
    return state


async def rollback_contract(service, db, backend, gid, lobby_id, run_id, users):
    run = await gate.seed_case(db, backend, gid, lobby_id, run_id, users)
    original_connect = backend.connect
    trip = {"done": False}

    def faulty_connect(*args, **kwargs):
        return gate.FaultConnectContext(original_connect, trip, *args, **kwargs)

    backend.connect = faulty_connect
    try:
        try:
            await service._resolve_run(gid, lobby_id, run, list(run["phase_results"]))
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

    run_row = await gate.backend_row(
        backend,
        "SELECT status,phase,success,total_reward FROM heist_runs WHERE guild_id=? AND run_id=?",
        (gid, run_id),
    )
    lobby_row = await gate.backend_row(
        backend,
        "SELECT status,phase FROM heist_lobbies WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    tx_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM transactions WHERE guild_id=? AND reason LIKE ?",
        (gid, f"heist_payout:{lobby_id}:%"),
    )
    vehicle_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM heist_vehicle_choices WHERE guild_id=? AND lobby_id=?",
        (gid, lobby_id),
    )
    stat_count = await gate.backend_row(
        backend,
        "SELECT COUNT(*) FROM user_statistics WHERE guild_id=? AND stat_name IN ('economy.earned','economy.wallet_peak')",
        (gid,),
    )

    if run_row is None or run_row[0] != "running" or int(run_row[1]) != 2 or run_row[2] is not None or int(run_row[3]) != 0:
        raise AssertionError(f"Heist run claim/finalize was not rolled back: {run_row!r}")
    if lobby_row != ("running", 2):
        raise AssertionError(f"Heist lobby changed despite rollback: {lobby_row!r}")
    if tx_count != (0,) or vehicle_count != (2,) or stat_count != (0,):
        raise AssertionError(
            f"Heist rollback side effects mismatch: tx={tx_count}, vehicles={vehicle_count}, stats={stat_count}"
        )

    return {
        "injected_after_first_wallet_update": True,
        "wallets_after": wallets,
        "run_status_after": run_row[0],
        "lobby_status_after": lobby_row[0],
        "transaction_rows_after": 0,
        "vehicle_choices_after": 2,
        "authoritative_stats_after": 0,
    }


async def run_test(result: dict[str, Any], name: str, task) -> None:
    started = time.perf_counter()
    result["stage"] = f"running:{name}"
    try:
        details = await task
        result["tests"][name] = {
            "status": "PASS",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "details": details,
        }
    except Exception as exc:
        result["tests"][name] = {
            "status": "FAIL",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        raise


async def main_async(result: dict[str, Any]) -> None:
    result["stage"] = "bootstrap_schema"
    await gate.bootstrap_heist_schema()

    import w10_transaction_contracts

    result["stage"] = "extract_foundation_source"
    work = w10_transaction_contracts.extract_and_verify_source()
    result["foundation_source_sha256"] = w10_transaction_contracts.EXPECTED_ZIP_SHA256
    src = work / "src"

    try:
        result["stage"] = "overlay_heist_source"
        gate.overlay_and_verify_heist(src)

        result["stage"] = "install_support_stubs"
        install_support_stubs()

        result["stage"] = "import_runtime"
        from app.database import Database
        from app import db_backend
        from app.services.heist import HeistService

        result["stage"] = "construct_service"
        db = Database("data/w10-heist-unused.db", 75_000)
        service = HeistService(
            db,
            gate.DummyStats(),
            characters=None,
            vehicles=None,
            world=None,
            police=None,
        )

        base = 8_000_000_000_000 + int(uuid.uuid4().hex[:7], 16) * 100
        await run_test(
            result,
            "heist_success_payout_conservation",
            success_contract(service, db, db_backend, base, base + 1, base + 2, (101, 102)),
        )
        await run_test(
            result,
            "heist_concurrent_exactly_once",
            exactly_once_contract(service, db, db_backend, base + 10, base + 11, base + 12, (201, 202)),
        )
        await run_test(
            result,
            "heist_injected_failure_full_rollback",
            rollback_contract(service, db, db_backend, base + 20, base + 21, base + 22, (301, 302)),
        )

        result["db_backend_metrics"] = db_backend.mysql_runtime_metrics()
        result["stage"] = "complete"
        result["status"] = "PASS"
    finally:
        result["finished_at"] = gate.utcnow()
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    result: dict[str, Any] = {
        "status": "FAIL",
        "started_at": gate.utcnow(),
        "tests": {},
        "heist_source_sha256": canonical.CANONICAL_SOURCE_SHA256,
        "stage": "startup",
    }
    try:
        asyncio.run(main_async(result))
        code = 0 if result.get("status") == "PASS" else 2
    except Exception as exc:
        result["finished_at"] = gate.utcnow()
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
        code = 2
    finally:
        gate.write_result(result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
