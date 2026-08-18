from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import uuid
from typing import Any

from mysql.connector.aio import connect as mysql_async_connect

HERE = Path(__file__).resolve().parent
W10_DIR = HERE.parent / "v372_mysql_gate"
W10_SOURCE_PARTS = [W10_DIR / f"w10_source_{index:02d}.b64" for index in range(4)]
W10_SOURCE_ZIP_SHA256 = "ca2db6f82bedb9679b38ace75956e583c91f1d6b712309c0b0d3f4fc47d06839"
EXPECTED_BASE_FILES = {
    "app/core/metrics.py": "fc7b9a463d8219186960098f0684972c95aaa673c1b2692f72637991440dd75c",
    "app/db_backend.py": "2820a18cb05b355be3cc756b6871832fe1b3e1525aae791622933776b80ad7ca",
}
SCENARIO_SOURCE_DIR = HERE / "source"
EXPECTED_SCENARIO_FILES = {
    "app/scenarios/models.py": "9dabbd3fd5c233cbc5ae3dde1cb1d235f7dad02ddd0aa40f15e4f4dcf3237b6b",
    "app/repositories/scenario.py": "bf88f9b5f834a2001dbaab623650232781f11ad3ecabab76f0f87b1d94109954",
}
RESULT_JSON = HERE / "YORU_V373_W11_2_SCENARIO_MARIADB_RESULT.json"
RESULT_TXT = HERE / "YORU_V373_W11_2_SCENARIO_MARIADB_RESULT.txt"
TABLES = ("player_scenario_history", "scenario_runs", "scenario_shuffle_bags")


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


def require_disposable_environment() -> None:
    if os.environ.get("YORU_W11_DISPOSABLE_SCHEMA") != "1":
        raise RuntimeError("W11.2 refuses to run without YORU_W11_DISPOSABLE_SCHEMA=1")
    database = os.environ.get("MYSQL_DATABASE", "").strip().lower()
    if not any(token in database for token in ("test", "qa", "staging", "sandbox", "ci")):
        raise RuntimeError(f"W11.2 refuses non-disposable database name: {database!r}")
    host = os.environ.get("MYSQL_HOST", "").strip().lower()
    if host not in {"127.0.0.1", "localhost", "mariadb"}:
        raise RuntimeError(f"W11.2 refuses non-local CI database host: {host!r}")


def extract_source() -> Path:
    encoded = "".join(part.read_text(encoding="ascii") for part in W10_SOURCE_PARTS)
    archive_bytes = base64.b64decode(encoded)
    actual_archive = sha256(archive_bytes)
    if actual_archive != W10_SOURCE_ZIP_SHA256:
        raise AssertionError(f"v3.72 W10 source fixture SHA mismatch: {actual_archive}")

    work = Path(tempfile.mkdtemp(prefix="yoru-w11-scenario-"))
    archive = work / "source.zip"
    archive.write_bytes(archive_bytes)
    shutil.unpack_archive(str(archive), str(work / "src"))
    src = work / "src"

    for rel, expected in EXPECTED_BASE_FILES.items():
        path = src / rel
        if not path.is_file():
            raise AssertionError(f"missing base source fixture: {rel}")
        actual = sha256(path.read_bytes())
        if actual != expected:
            raise AssertionError(f"base source hash mismatch for {rel}: {actual}")

    for rel, expected in EXPECTED_SCENARIO_FILES.items():
        source = SCENARIO_SOURCE_DIR / rel
        if not source.is_file():
            raise AssertionError(f"missing W11.2 Scenario source fixture: {rel}")
        actual = sha256(source.read_bytes())
        if actual != expected:
            raise AssertionError(f"Scenario source hash mismatch for {rel}: {actual}")
        destination = src / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    (src / "app" / "scenarios" / "__init__.py").write_text("", encoding="utf-8")
    (src / "app" / "repositories" / "__init__.py").write_text("", encoding="utf-8")
    sys.path.insert(0, str(src))
    return work


async def direct_rows(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    conn = await mysql_async_connect(**direct_mysql_kwargs())
    try:
        cur = await conn.cursor()
        try:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
            return [tuple(row) for row in rows]
        finally:
            await cur.close()
    finally:
        await conn.close()


async def direct_scalar(sql: str, params: tuple[Any, ...] = ()) -> Any:
    rows = await direct_rows(sql, params)
    return rows[0][0] if rows else None


async def reset_scenario_tables() -> None:
    conn = await mysql_async_connect(**direct_mysql_kwargs())
    try:
        cur = await conn.cursor()
        try:
            for table in TABLES:
                await cur.execute(f"DROP TABLE IF EXISTS `{table}`")
            await conn.commit()
        finally:
            await cur.close()
    finally:
        await conn.close()


async def contract_native_ddl(repo: Any) -> dict[str, Any]:
    await reset_scenario_tables()
    await repo.initialize()

    rows = await direct_rows(
        "SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s) ORDER BY TABLE_NAME",
        (os.environ["MYSQL_DATABASE"], *TABLES),
    )
    engines = {str(name): str(engine) for name, engine in rows}
    assert set(engines) == set(TABLES), engines
    assert all(engine.lower() == "innodb" for engine in engines.values()), engines

    index_rows = await direct_rows(
        "SELECT TABLE_NAME,INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s)",
        (os.environ["MYSQL_DATABASE"], *TABLES),
    )
    indexes = {(str(table), str(index)) for table, index in index_rows}
    required = {
        ("player_scenario_history", "PRIMARY"),
        ("player_scenario_history", "idx_scenario_history_recent"),
        ("player_scenario_history", "idx_scenario_history_run"),
        ("scenario_runs", "PRIMARY"),
        ("scenario_runs", "idx_scenario_runs_active"),
        ("scenario_shuffle_bags", "PRIMARY"),
    }
    assert required.issubset(indexes), sorted(required - indexes)
    return {"engines": engines, "required_indexes": len(required)}


async def contract_initialize_idempotent(repo: Any) -> dict[str, Any]:
    await repo.initialize()
    await repo.initialize()
    count = int(await direct_scalar(
        "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s)",
        (os.environ["MYSQL_DATABASE"], *TABLES),
    ) or 0)
    assert count == 3, count
    return {"table_count": count}


async def contract_history(repo: Any) -> dict[str, Any]:
    gid, uid, family = 730001, 730101, "w11_history"
    run_id = f"w11-history-{uuid.uuid4().hex[:12]}"
    first = await repo.record_shown(
        guild_id=gid, user_id=uid, domain="work", family=family,
        scenario_key="work_alpha", topic_hash="topic.alpha", context_digest="ctx-a", run_id=run_id,
    )
    second = await repo.record_shown(
        guild_id=gid, user_id=uid, domain="work", family=family,
        scenario_key="work_beta", topic_hash="topic.beta", context_digest="ctx-b", run_id=None,
    )
    assert first > 0 and second > first, (first, second)
    await repo.complete_history(run_id=run_id, outcome="success")
    rows = await repo.recent_history(gid, uid, family, limit=10)
    assert len(rows) == 2, rows
    target = next(row for row in rows if row["run_id"] == run_id)
    assert target["outcome"] == "success", target
    assert target["completed_at"], target
    return {"rows": len(rows), "ids": [row["id"] for row in rows]}


async def contract_shuffle_bag(repo: Any) -> dict[str, Any]:
    gid, uid, family = 730002, 730102, "w11_bag"
    assert await repo.get_bag(gid, uid, family) == ([], None)
    await repo.save_bag(gid, uid, family, ["a", "b", "c"], "digest-1")
    bag, digest = await repo.get_bag(gid, uid, family)
    assert bag == ["a", "b", "c"] and digest == "digest-1", (bag, digest)
    await repo.save_bag(gid, uid, family, ["z"], "digest-2")
    bag, digest = await repo.get_bag(gid, uid, family)
    assert bag == ["z"] and digest == "digest-2", (bag, digest)
    count = int(await direct_scalar(
        "SELECT COUNT(*) FROM scenario_shuffle_bags WHERE guild_id=%s AND user_id=%s AND family=%s",
        (gid, uid, family),
    ) or 0)
    assert count == 1, count
    return {"bag": bag, "digest": digest, "rows": count}


async def contract_run_restart(repo_cls: Any) -> dict[str, Any]:
    run_id = f"w11-run-{uuid.uuid4().hex[:12]}"
    repo = repo_cls("unused")
    created = await repo.create_run(
        run_id=run_id, guild_id=730003, user_id=730103, domain="career", family="w11_run",
        scenario_key="career_alpha", current_node="start", state={"score": 1},
        source="deterministic", expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    assert created.status.value == "active"
    await repo.update_run(run_id, scenario_key="career_beta", current_node="branch_b", state={"score": 9})
    restarted = repo_cls("unused")
    loaded = await restarted.get_run(run_id)
    assert loaded is not None
    assert loaded.scenario_key == "career_beta"
    assert loaded.current_node == "branch_b"
    assert dict(loaded.state) == {"score": 9}
    active = await restarted.active_runs(guild_id=730003, user_id=730103)
    assert [item.run_id for item in active] == [run_id]
    return {"run_id": run_id, "state": dict(loaded.state)}


async def contract_stale_expiration(repo: Any) -> dict[str, Any]:
    past_run = f"w11-expired-{uuid.uuid4().hex[:10]}"
    future_run = f"w11-future-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    await repo.create_run(
        run_id=past_run, guild_id=730004, user_id=730104, domain="work", family="w11_expire",
        scenario_key="past", current_node="start", state={}, source="deterministic",
        expires_at=(now - timedelta(minutes=5)).isoformat(),
    )
    await repo.create_run(
        run_id=future_run, guild_id=730004, user_id=730104, domain="work", family="w11_expire",
        scenario_key="future", current_node="start", state={}, source="deterministic",
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    changed = await repo.expire_stale_runs(now_iso=now.isoformat())
    past = await repo.get_run(past_run)
    future = await repo.get_run(future_run)
    assert changed >= 1, changed
    assert past is not None and past.status.value == "expired"
    assert future is not None and future.status.value == "active"
    return {"changed": changed, "past": past.status.value, "future": future.status.value}


async def contract_concurrent_history(repo: Any) -> dict[str, Any]:
    gid, uid, family = 730005, 730105, "w11_concurrent_history"

    async def write(i: int) -> int:
        return await repo.record_shown(
            guild_id=gid, user_id=uid, domain="work", family=family,
            scenario_key=f"scenario_{i}", topic_hash=f"topic_{i}", context_digest=f"ctx_{i}",
            run_id=f"w11-ch-{i}",
        )

    ids = await asyncio.gather(*(write(i) for i in range(32)))
    assert len(ids) == 32 and len(set(ids)) == 32, ids
    count = int(await direct_scalar(
        "SELECT COUNT(*) FROM player_scenario_history WHERE guild_id=%s AND user_id=%s AND family=%s",
        (gid, uid, family),
    ) or 0)
    assert count == 32, count
    return {"writes": len(ids), "unique_ids": len(set(ids)), "rows": count}


async def contract_concurrent_bag(repo: Any) -> dict[str, Any]:
    gid, uid, family = 730006, 730106, "w11_concurrent_bag"

    async def write(i: int) -> None:
        await repo.save_bag(gid, uid, family, [f"item_{i}"], f"digest_{i}")

    await asyncio.gather(*(write(i) for i in range(16)))
    bag, digest = await repo.get_bag(gid, uid, family)
    assert len(bag) == 1 and bag[0].startswith("item_"), (bag, digest)
    assert digest is not None and digest.startswith("digest_"), (bag, digest)
    count = int(await direct_scalar(
        "SELECT COUNT(*) FROM scenario_shuffle_bags WHERE guild_id=%s AND user_id=%s AND family=%s",
        (gid, uid, family),
    ) or 0)
    assert count == 1, count
    return {"rows": count, "final_bag": bag, "final_digest": digest}


async def run_contracts() -> dict[str, Any]:
    require_disposable_environment()
    work = extract_source()
    try:
        from app import db_backend
        from app.repositories.scenario import ScenarioRepository

        repo = ScenarioRepository("unused")
        contracts = [
            ("native_ddl_innodb_and_indexes", lambda: contract_native_ddl(repo)),
            ("initialize_idempotent", lambda: contract_initialize_idempotent(repo)),
            ("history_record_complete_recent", lambda: contract_history(repo)),
            ("shuffle_bag_upsert_roundtrip", lambda: contract_shuffle_bag(repo)),
            ("run_create_update_restart_resume", lambda: contract_run_restart(ScenarioRepository)),
            ("stale_run_expiration", lambda: contract_stale_expiration(repo)),
            ("concurrent_history_integrity", lambda: contract_concurrent_history(repo)),
            ("concurrent_shuffle_bag_single_row", lambda: contract_concurrent_bag(repo)),
        ]
        results: list[dict[str, Any]] = []
        for name, factory in contracts:
            started = asyncio.get_running_loop().time()
            try:
                details = await factory()
                results.append({
                    "name": name,
                    "status": "PASS",
                    "duration_ms": round((asyncio.get_running_loop().time() - started) * 1000, 3),
                    "details": details,
                })
            except Exception as exc:
                results.append({
                    "name": name,
                    "status": "FAIL",
                    "duration_ms": round((asyncio.get_running_loop().time() - started) * 1000, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })
                break

        metrics = db_backend.mysql_runtime_metrics()
        metrics_ok = (
            int(metrics.get("active", -1)) == 0
            and int(metrics.get("acquire_timeouts", -1)) == 0
            and int(metrics.get("query_errors", -1)) == 0
        )
        all_pass = len(results) == len(contracts) and all(item["status"] == "PASS" for item in results) and metrics_ok
        return {
            "gate": "Yoru v3.73 W11.2 ScenarioRepository native MariaDB/InnoDB",
            "generated_at": utcnow(),
            "status": "PASS" if all_pass else "FAIL",
            "source": {
                "base_fixture": "existing W10 v3.72 certified source snapshot",
                "base_zip_sha256": W10_SOURCE_ZIP_SHA256,
                "authoritative_hashes": {**EXPECTED_BASE_FILES, **EXPECTED_SCENARIO_FILES},
            },
            "environment": {
                "database": os.environ.get("MYSQL_DATABASE"),
                "host": os.environ.get("MYSQL_HOST"),
                "backend": os.environ.get("YORU_DB_BACKEND"),
            },
            "contracts": results,
            "metrics": metrics,
            "metrics_ok": metrics_ok,
        }
    finally:
        if str(work / "src") in sys.path:
            sys.path.remove(str(work / "src"))
        shutil.rmtree(work, ignore_errors=True)


def write_report(report: dict[str, Any]) -> None:
    RESULT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        report["gate"],
        f"STATUS: {report['status']}",
        f"Generated: {report['generated_at']}",
        "",
    ]
    for item in report["contracts"]:
        lines.append(f"[{item['status']}] {item['name']} ({item['duration_ms']} ms)")
        if item["status"] == "FAIL":
            lines.append(f"  {item.get('error', '')}")
            lines.append(item.get("traceback", ""))
    lines.extend([
        "",
        f"metrics_ok={report['metrics_ok']}",
        f"active={report['metrics'].get('active')}",
        f"peak_active={report['metrics'].get('peak_active')}",
        f"queries={report['metrics'].get('queries')}",
        f"query_errors={report['metrics'].get('query_errors')}",
        f"acquire_timeouts={report['metrics'].get('acquire_timeouts')}",
    ])
    RESULT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        report = asyncio.run(run_contracts())
    except Exception as exc:
        report = {
            "gate": "Yoru v3.73 W11.2 ScenarioRepository native MariaDB/InnoDB",
            "generated_at": utcnow(),
            "status": "FAIL",
            "fatal_error": f"{type(exc).__name__}: {exc}",
            "fatal_traceback": traceback.format_exc(),
            "contracts": [],
            "metrics": {},
            "metrics_ok": False,
        }
    write_report(report)
    print(RESULT_TXT.read_text(encoding="utf-8"))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
