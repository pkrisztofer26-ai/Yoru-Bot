from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid
from typing import Any, Awaitable

from mysql.connector.aio import connect as mysql_async_connect

HERE = Path(__file__).resolve().parent
SOURCE_PARTS = [HERE / f"w10_source_{index:02d}.b64" for index in range(4)]
RESULT_JSON = HERE / "YORU_W10_TRANSACTION_CONTRACT_RESULT.json"
RESULT_TXT = HERE / "YORU_W10_TRANSACTION_CONTRACT_RESULT.txt"
EXPECTED_ZIP_SHA256 = "ca2db6f82bedb9679b38ace75956e583c91f1d6b712309c0b0d3f4fc47d06839"
EXPECTED_FILES = {
    "app/core/metrics.py": "fc7b9a463d8219186960098f0684972c95aaa673c1b2692f72637991440dd75c",
    "app/database.py": "8993e1d0abbc52d857750e0a73d9466191c0ccb62812218847554e55b4ca1668",
    "app/db_backend.py": "2820a18cb05b355be3cc756b6871832fe1b3e1525aae791622933776b80ad7ca",
    "app/economy_config.py": "6dc01af00b2454675f41508a8b2e04cf944d1e8b450dda08d4312625cb09274d",
    "app/repositories/guild_state.py": "cd5743911e2466b9773cb1c62cb5296151344b72e3166cc5a400d4d0d0c53a33",
    "app/shop_config.py": "5911e92df52c5b8b52e0524e46627c4a5c1027b66dbf1b3f554391ee029cc8c7",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def direct_mysql_kwargs() -> dict[str, Any]:
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


async def bootstrap_cutover_marker() -> None:
    conn = await mysql_async_connect(**direct_mysql_kwargs())
    try:
        cur = await conn.cursor()
        try:
            await cur.execute(
                """CREATE TABLE IF NOT EXISTS `_yoru_migration_meta` (
                    meta_key VARCHAR(64) NOT NULL PRIMARY KEY,
                    meta_value VARCHAR(255) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
            await cur.execute(
                "INSERT INTO `_yoru_migration_meta` (meta_key,meta_value) VALUES ('schema_version','db1') "
                "ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value)"
            )
            await cur.execute(
                "INSERT INTO `_yoru_migration_meta` (meta_key,meta_value) VALUES ('status','verified') "
                "ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value)"
            )
            await conn.commit()
        finally:
            await cur.close()
    finally:
        await conn.close()


def extract_and_verify_source() -> Path:
    encoded = "".join(part.read_text(encoding="ascii") for part in SOURCE_PARTS)
    zip_bytes = base64.b64decode(encoded)
    actual = sha256(zip_bytes)
    if actual != EXPECTED_ZIP_SHA256:
        raise AssertionError(f"v3.72 source snapshot SHA mismatch: {actual}")
    work = Path(tempfile.mkdtemp(prefix="yoru-w10-v372-"))
    archive = work / "source.zip"
    archive.write_bytes(zip_bytes)
    shutil.unpack_archive(str(archive), str(work / "src"))
    src = work / "src"
    for rel, expected in EXPECTED_FILES.items():
        path = src / rel
        if not path.is_file():
            raise AssertionError(f"missing v3.72 source file: {rel}")
        actual_file = sha256(path.read_bytes())
        if actual_file != expected:
            raise AssertionError(f"source hash mismatch for {rel}: {actual_file}")
    sys.path.insert(0, str(src))
    return work


async def row(db_backend: Any, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    async with db_backend.connect("unused") as conn:
        cur = await conn.execute(sql, params)
        value = await cur.fetchone()
        return tuple(value) if value is not None else None


async def rows(db_backend: Any, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    async with db_backend.connect("unused") as conn:
        cur = await conn.execute(sql, params)
        values = await cur.fetchall()
        return [tuple(v) for v in values]


async def scalar(db_backend: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    value = await row(db_backend, sql, params)
    return int(value[0]) if value else 0


async def wallet_bank_contract(db: Any, backend: Any, gid: int, uid: int) -> dict[str, Any]:
    await db.set_wallet(gid, uid, 500_000, "w10_seed_wallet")
    await db.add_bank(gid, uid, 500_000, "w10_seed_bank")

    async def debit(i: int) -> tuple[int, int, int, int]:
        return await db.debit_wallet_and_bank(gid, uid, 100_000, f"w10_debit_{i}")

    debits = await asyncio.gather(*(debit(i) for i in range(8)))
    wallet, bank = await db.get_balance(gid, uid)
    if wallet + bank != 200_000 or wallet < 0 or bank < 0:
        raise AssertionError(f"wallet/bank atomic debit mismatch: {(wallet, bank)!r}")

    await asyncio.gather(*(
        db.refund_wallet_and_bank(gid, uid, d[0], d[1], f"w10_refund_{i}")
        for i, d in enumerate(debits)
    ))
    restored = await db.get_balance(gid, uid)
    if restored != (500_000, 500_000):
        raise AssertionError(f"wallet/bank refund did not restore sources: {restored!r}")
    tx_delta = await scalar(
        backend,
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE guild_id=? AND user_id=? AND (reason LIKE 'w10_debit_%' OR reason LIKE 'w10_refund_%')",
        (gid, uid),
    )
    if tx_delta != 0:
        raise AssertionError(f"debit/refund transaction ledger does not net to zero: {tx_delta}")
    return {"concurrent_debits": 8, "debit_amount": 100_000, "post_debit": [wallet, bank], "restored": list(restored), "ledger_net": tx_delta}


async def transfer_conservation_contract(db: Any, gid: int, users: list[int]) -> dict[str, Any]:
    for uid in users:
        await db.set_wallet(gid, uid, 1_000_000, "w10_transfer_seed")
    operations: list[tuple[int, int, int]] = []
    for _ in range(20):
        operations.extend([
            (users[0], users[1], 10_000),
            (users[1], users[2], 10_000),
            (users[2], users[3], 10_000),
            (users[3], users[0], 10_000),
        ])
    await asyncio.gather(*(db.transfer_wallet(gid, a, b, amount) for a, b, amount in operations))
    balances = {uid: (await db.get_balance(gid, uid))[0] for uid in users}
    if sum(balances.values()) != 4_000_000:
        raise AssertionError(f"wallet transfer did not conserve money: {balances!r}")
    if min(balances.values()) < 0:
        raise AssertionError(f"wallet transfer produced negative balance: {balances!r}")
    return {"transfers": len(operations), "final_wallets": balances, "conserved_total": sum(balances.values())}


async def gamble_contract(db: Any, backend: Any, gid: int, uid: int) -> dict[str, Any]:
    await db.set_wallet(gid, uid, 2_000_000, "w10_gamble_seed")
    before = await row(backend, "SELECT gambling_profit,game_wins FROM users WHERE guild_id=? AND user_id=?", (gid, uid))
    before_profit, before_wins = (int(before[0]), int(before[1])) if before else (0, 0)
    profits = [10_000 if i % 2 == 0 else -10_000 for i in range(20)]
    await asyncio.gather(*(
        db.settle_gamble(gid, uid, 10_000, profit, "w10_contract", profit > 0)
        for profit in profits
    ))
    wallet = (await db.get_balance(gid, uid))[0]
    state = await row(backend, "SELECT gambling_profit,game_wins FROM users WHERE guild_id=? AND user_id=?", (gid, uid))
    tx_count = await scalar(backend, "SELECT COUNT(*) FROM transactions WHERE guild_id=? AND user_id=? AND reason='gamble:w10_contract'", (gid, uid))
    if wallet != 2_000_000:
        raise AssertionError(f"gamble net-zero batch changed wallet: {wallet}")
    if not state or int(state[0]) - before_profit != 0 or int(state[1]) - before_wins != 10:
        raise AssertionError(f"gamble aggregate stats mismatch: before={before!r}, after={state!r}")
    if tx_count != 20:
        raise AssertionError(f"gamble transaction count mismatch: {tx_count}")
    return {"settlements": 20, "wins": 10, "losses": 10, "wallet_after": wallet, "transaction_rows": tx_count}


async def casino_exactly_once_contract(db: Any, backend: Any, gid: int, uid: int) -> dict[str, Any]:
    await db.set_wallet(gid, uid, 1_000_000, "w10_casino_seed")
    game_id = f"w10-{uuid.uuid4().hex}"
    await db.reserve_casino_session(game_id, gid, uid, "w10-casino", 100_000, {"contract": True})
    results = await asyncio.gather(*(
        db.settle_casino_session(game_id, 200_000, result="w10-win", multiplier=2.0)
        for _ in range(8)
    ))
    first_count = sum(1 for item in results if not bool(item.get("idempotent")))
    idem_count = sum(1 for item in results if bool(item.get("idempotent")))
    wallet = (await db.get_balance(gid, uid))[0]
    payout_ledger = await scalar(backend, "SELECT COUNT(*) FROM casino_ledger WHERE game_id=? AND entry_key='settlement'", (game_id,))
    payout_tx = await scalar(backend, "SELECT COUNT(*) FROM transactions WHERE guild_id=? AND user_id=? AND reason=?", (gid, uid, f"casino_payout:w10-casino:{game_id}"))
    if (first_count, idem_count) != (1, 7):
        raise AssertionError(f"casino settlement idempotency mismatch: first={first_count}, idempotent={idem_count}")
    if wallet != 1_100_000 or payout_ledger != 1 or payout_tx != 1:
        raise AssertionError(f"casino exactly-once mismatch: wallet={wallet}, ledger={payout_ledger}, tx={payout_tx}")
    return {"parallel_settle_calls": 8, "authoritative_settlements": first_count, "idempotent_replays": idem_count, "wallet_after": wallet, "payout_ledger_rows": payout_ledger}


async def casino_refund_contract(db: Any, backend: Any, gid: int, uid: int) -> dict[str, Any]:
    await db.set_wallet(gid, uid, 1_000_000, "w10_casino_refund_seed")
    game_id = f"w10-refund-{uuid.uuid4().hex}"
    await db.reserve_casino_session(game_id, gid, uid, "w10-refund", 100_000, {})
    results = await asyncio.gather(*(db.refund_casino_session(game_id, "w10") for _ in range(8)))
    first_count = sum(1 for item in results if not bool(item.get("idempotent")))
    idem_count = sum(1 for item in results if bool(item.get("idempotent")))
    wallet = (await db.get_balance(gid, uid))[0]
    refund_ledger = await scalar(backend, "SELECT COUNT(*) FROM casino_ledger WHERE game_id=? AND entry_key='refund'", (game_id,))
    if (first_count, idem_count) != (1, 7) or wallet != 1_000_000 or refund_ledger != 1:
        raise AssertionError(f"casino refund exactly-once mismatch: first={first_count}, idem={idem_count}, wallet={wallet}, ledger={refund_ledger}")
    return {"parallel_refund_calls": 8, "authoritative_refunds": first_count, "idempotent_replays": idem_count, "wallet_after": wallet}


async def crew_contract(db: Any, gid: int, uid: int) -> dict[str, Any]:
    await db.set_wallet(gid, uid, 2_000_000, "w10_crew_seed")
    crew = await db.create_crew(gid, uid, "W10 Crew", f"w10-crew-{uuid.uuid4().hex}", 0)
    crew_id = int(crew["crew_id"])
    await asyncio.gather(*(db.deposit_to_crew(gid, crew_id, uid, 50_000) for _ in range(10)))
    wallet_mid = (await db.get_balance(gid, uid))[0]
    crew_mid = await db.get_crew(gid, crew_id)
    if crew_mid is None or wallet_mid != 1_500_000 or int(crew_mid["bank"]) != 500_000:
        raise AssertionError(f"crew deposit contract mismatch: wallet={wallet_mid}, crew={crew_mid!r}")
    await asyncio.gather(*(db.withdraw_from_crew(gid, crew_id, uid, 60_000) for _ in range(5)))
    wallet_end = (await db.get_balance(gid, uid))[0]
    crew_end = await db.get_crew(gid, crew_id)
    if crew_end is None or wallet_end != 1_800_000 or int(crew_end["bank"]) != 200_000:
        raise AssertionError(f"crew withdrawal contract mismatch: wallet={wallet_end}, crew={crew_end!r}")
    if wallet_end + int(crew_end["bank"]) != 2_000_000:
        raise AssertionError("crew treasury did not conserve wallet+bank total")
    return {"deposits": 10, "withdrawals": 5, "wallet_after": wallet_end, "crew_bank_after": int(crew_end["bank"]), "conserved_total": 2_000_000}


async def market_contract(db: Any, gid: int, uid: int) -> dict[str, Any]:
    await db.set_wallet(gid, uid, 5_000_000, "w10_market_seed")
    market_date = "2099-12-31"
    await db.create_market_state(gid, "silver", market_date, 100_000, 20)
    await asyncio.gather(*(db.buy_market_item(gid, uid, "silver", 1, market_date) for _ in range(10)))
    wallet_mid = (await db.get_balance(gid, uid))[0]
    stock_mid = await db.get_market_state(gid, "silver", market_date)
    inv_mid = await db.get_item_quantity(gid, uid, "silver")
    if wallet_mid != 4_000_000 or stock_mid is None or stock_mid[1] != 10 or inv_mid != 10:
        raise AssertionError(f"market buy contract mismatch: wallet={wallet_mid}, stock={stock_mid}, inv={inv_mid}")
    await asyncio.gather(*(db.sell_market_item(gid, uid, "silver", 1, market_date, 0.8) for _ in range(5)))
    wallet_end = (await db.get_balance(gid, uid))[0]
    stock_end = await db.get_market_state(gid, "silver", market_date)
    inv_end = await db.get_item_quantity(gid, uid, "silver")
    if wallet_end != 4_400_000 or stock_end is None or stock_end[1] != 15 or inv_end != 5:
        raise AssertionError(f"market sell contract mismatch: wallet={wallet_end}, stock={stock_end}, inv={inv_end}")
    return {"buys": 10, "sells": 5, "wallet_after": wallet_end, "stock_after": stock_end[1], "inventory_after": inv_end}


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
        "YORU v3.72.0 W10 NATIVE MYSQL TRANSACTION CONTRACTS",
        f"Status: {result.get('status', 'FAIL')}",
        f"Started: {result.get('started_at', '-')}",
        f"Finished: {result.get('finished_at', '-')}",
        f"Source snapshot SHA-256: {EXPECTED_ZIP_SHA256}",
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
        "Scope: actual v3.72 Database/db_backend source snapshot, running on ephemeral MariaDB/InnoDB.",
        "The global compatibility writer lock is intentionally still enabled in this W10 proof.",
        "No live/PebbleHost credentials or data are used.",
    ])
    return "\n".join(lines) + "\n"


def write_result(result: dict[str, Any]) -> None:
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    RESULT_TXT.write_text(render_text(result), encoding="utf-8")


async def main_async() -> dict[str, Any]:
    result: dict[str, Any] = {"status": "FAIL", "started_at": utcnow(), "tests": {}, "source_snapshot_sha256": EXPECTED_ZIP_SHA256}
    work = extract_and_verify_source()
    result["source_root"] = str(work / "src")
    try:
        await bootstrap_cutover_marker()
        from app.database import Database
        from app import db_backend

        db = Database("data/w10-ci-unused.db", 75_000)
        started = time.perf_counter()
        await db.initialize()
        result["database_initialize_ms"] = round((time.perf_counter() - started) * 1000, 3)

        base_gid = 9_000_000_000_000 + int(uuid.uuid4().hex[:8], 16)
        result["test_guild_id"] = base_gid
        await run_test(result, "wallet_bank_atomic_debit_refund", wallet_bank_contract(db, db_backend, base_gid, 101))
        await run_test(result, "wallet_transfer_conservation", transfer_conservation_contract(db, base_gid + 1, [201, 202, 203, 204]))
        await run_test(result, "gamble_settlement_consistency", gamble_contract(db, db_backend, base_gid + 2, 301))
        await run_test(result, "casino_settlement_exactly_once", casino_exactly_once_contract(db, db_backend, base_gid + 3, 401))
        await run_test(result, "casino_refund_exactly_once", casino_refund_contract(db, db_backend, base_gid + 4, 501))
        await run_test(result, "crew_treasury_conservation", crew_contract(db, base_gid + 5, 601))
        await run_test(result, "market_stock_inventory_conservation", market_contract(db, base_gid + 6, 701))
        result["db_backend_metrics"] = db_backend.mysql_runtime_metrics()
        result["status"] = "PASS"
        return result
    finally:
        result["finished_at"] = utcnow()
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    result: dict[str, Any] = {"status": "FAIL", "started_at": utcnow(), "tests": {}, "source_snapshot_sha256": EXPECTED_ZIP_SHA256}
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
