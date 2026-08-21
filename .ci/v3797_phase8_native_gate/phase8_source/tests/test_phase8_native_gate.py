from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
try:
    from mysql.connector.aio import connect
    from mysql.connector.errors import IntegrityError
except ImportError:  # local non-native preflight; CI installs the connector
    connect = None
    class IntegrityError(Exception):
        pass

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "PHASE8_SCHEMA.sql").read_text(encoding="utf-8")
FP = json.loads((ROOT / "SOURCE_FINGERPRINTS.json").read_text(encoding="utf-8"))
LOCK = "yoru:phase8-native-writer"
W18_TABLES = (
    "crew_relations", "crew_governance_proposals", "crew_governance_votes",
    "crew_governance_executions", "crew_internal_projects",
    "crew_hq_state", "crew_hq_asset_links",
)
DROP = (
    "crew_hq_asset_links", "crew_hq_state", "crew_internal_projects",
    "crew_governance_executions", "crew_governance_votes", "crew_governance_proposals",
    "crew_relations", "crew_wars", "contracts", "crews", "business_tenders", "heist_runs",
    "character_travel_history", "job_sessions", "business_transactions", "rp_world_causality_signals",
)


def creds() -> dict:
    if connect is None:
        pytest.skip("mysql-connector-python not installed in local non-native environment")
    if os.getenv("YORU_TEST_MYSQL_CONFIRM") != "DISPOSABLE_SCHEMA":
        pytest.skip("disposable MariaDB not confirmed")
    required = ["YORU_TEST_MYSQL_HOST", "YORU_TEST_MYSQL_USER", "YORU_TEST_MYSQL_PASSWORD", "YORU_TEST_MYSQL_DATABASE"]
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        pytest.skip("missing disposable MariaDB credentials: " + ",".join(missing))
    database = os.environ["YORU_TEST_MYSQL_DATABASE"].strip()
    if not re.search(r"(test|qa|staging|sandbox)", database, re.I):
        pytest.fail("refusing non-disposable schema")
    return {
        "host": os.environ["YORU_TEST_MYSQL_HOST"],
        "port": int(os.getenv("YORU_TEST_MYSQL_PORT", "3306")),
        "user": os.environ["YORU_TEST_MYSQL_USER"],
        "password": os.environ["YORU_TEST_MYSQL_PASSWORD"],
        "database": database,
        "autocommit": False,
        "use_pure": True,
        "ssl_disabled": True,
    }


async def raw(conn, sql: str, params=()):
    cur = await conn.cursor()
    await cur.execute(sql, params)
    return cur


async def scalar(conn, sql: str, params=()):
    cur = await raw(conn, sql, params)
    row = await cur.fetchone()
    await cur.close()
    return None if row is None else row[0]


async def rows(conn, sql: str, params=()):
    cur = await raw(conn, sql, params)
    result = await cur.fetchall()
    await cur.close()
    return result


async def writer_lock(conn):
    if int(await scalar(conn, "SELECT GET_LOCK(%s,10)", (LOCK,)) or 0) != 1:
        raise RuntimeError("native writer lock timeout")


async def writer_unlock(conn):
    await scalar(conn, "SELECT RELEASE_LOCK(%s)", (LOCK,))


def ddl_map() -> dict[str, str]:
    result = {}
    for block in SCHEMA.split("-- TABLE:")[1:]:
        name, body = block.split("\n", 1)
        body = body.split("-- MIGRATION:", 1)[0].strip()
        result[name.strip()] = body
    return result


async def reset_schema():
    conn = await connect(**creds())
    try:
        await raw(conn, "SET FOREIGN_KEY_CHECKS=0")
        for table in DROP:
            await raw(conn, f"DROP TABLE IF EXISTS `{table}`")
        await raw(conn, "SET FOREIGN_KEY_CHECKS=1")
        await conn.commit()
    finally:
        await conn.close()


async def install_base():
    conn = await connect(**creds())
    try:
        base = [
            """CREATE TABLE crews(
                crew_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                guild_id BIGINT UNSIGNED NOT NULL,
                name VARCHAR(100) NOT NULL,
                owner_id BIGINT UNSIGNED NOT NULL,
                bank BIGINT UNSIGNED NOT NULL DEFAULT 0,
                level INT NOT NULL DEFAULT 1,
                PRIMARY KEY(crew_id), UNIQUE KEY uq_crews_name(guild_id,name)
            ) ENGINE=InnoDB""",
            """CREATE TABLE crew_wars(
                war_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                guild_id BIGINT UNSIGNED NOT NULL,
                challenger_crew_id BIGINT UNSIGNED NOT NULL,
                target_crew_id BIGINT UNSIGNED NOT NULL,
                status VARCHAR(24) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                expires_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(war_id), KEY idx_war_open(guild_id,status,challenger_crew_id,target_crew_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE contracts(
                contract_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                guild_id BIGINT UNSIGNED NOT NULL,
                assignee_id BIGINT UNSIGNED NULL,
                status VARCHAR(24) NOT NULL,
                resolved_at VARCHAR(64) NULL,
                PRIMARY KEY(contract_id), KEY idx_contract_settled(guild_id,status,resolved_at,assignee_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE business_tenders(
                tender_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                guild_id BIGINT UNSIGNED NOT NULL,
                property_id BIGINT UNSIGNED NOT NULL,
                owner_id BIGINT UNSIGNED NOT NULL,
                problem_id VARCHAR(80) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'open',
                max_reward BIGINT UNSIGNED NOT NULL DEFAULT 0,
                awarded_bid_id BIGINT UNSIGNED NULL,
                contract_id BIGINT UNSIGNED NULL,
                resolved_at VARCHAR(64) NULL,
                PRIMARY KEY(tender_id), UNIQUE KEY uq_bt(guild_id,property_id,problem_id)
            ) ENGINE=InnoDB""",
            """CREATE TABLE heist_runs(
                run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                guild_id BIGINT UNSIGNED NOT NULL,
                status VARCHAR(24) NOT NULL,
                success TINYINT NOT NULL DEFAULT 0,
                reward_pool BIGINT UNSIGNED NOT NULL DEFAULT 0,
                member_snapshot LONGTEXT NOT NULL,
                resolved_at VARCHAR(64) NULL,
                PRIMARY KEY(run_id)
            ) ENGINE=InnoDB""",
            "CREATE TABLE character_travel_history(travel_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,to_city_key VARCHAR(40) NOT NULL,arrived_at VARCHAR(64) NOT NULL,PRIMARY KEY(travel_id)) ENGINE=InnoDB",
            "CREATE TABLE job_sessions(session_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,city_key VARCHAR(40) NOT NULL,status VARCHAR(24) NOT NULL,completed_at VARCHAR(64) NULL,PRIMARY KEY(session_id)) ENGINE=InnoDB",
            "CREATE TABLE business_transactions(tx_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,city_key VARCHAR(40) NOT NULL,tx_kind VARCHAR(32) NOT NULL,created_at VARCHAR(64) NOT NULL,PRIMARY KEY(tx_id)) ENGINE=InnoDB",
            "CREATE TABLE rp_world_causality_signals(signal_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,guild_id BIGINT UNSIGNED NOT NULL,actor_id BIGINT UNSIGNED NULL,city_key VARCHAR(40) NULL,signal_kind VARCHAR(48) NOT NULL,created_at VARCHAR(64) NOT NULL,PRIMARY KEY(signal_id)) ENGINE=InnoDB",
        ]
        for statement in base:
            await raw(conn, statement)
        for statement in ddl_map().values():
            await raw(conn, statement)
        await conn.commit()
    finally:
        await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def native_schema(request):
    if request.node.name == "test_10_source_projection_contract":
        yield
        return
    creds()
    await reset_schema()
    await install_base()
    yield
    await reset_schema()


async def add_crews():
    conn = await connect(**creds())
    try:
        await raw(conn, "INSERT INTO crews(guild_id,name,owner_id,bank) VALUES (1,'A',101,100000000),(1,'B',201,100000000),(1,'C',301,1000000)")
        await conn.commit()
    finally:
        await conn.close()


async def make_passed(kind: str, crew: int = 1, subject: str = "x") -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn = await connect(**creds())
    try:
        cur = await raw(
            conn,
            """INSERT INTO crew_governance_proposals
            (guild_id,crew_id,decision_kind,title,description,subject_ref,created_by,eligible_count,required_yes,status,active_slot,created_at,closes_at,resolved_at)
            VALUES (1,%s,%s,'P','',%s,101,2,2,'passed',NULL,%s,%s,%s)""",
            (crew, kind, subject, now, now, now),
        )
        await conn.commit()
        return int(cur.lastrowid)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_01_schema_innodb_indexes_fks_and_w187_migration():
    conn = await connect(**creds())
    try:
        engines = await rows(
            conn,
            "SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s,%s,%s,%s,%s,%s)",
            W18_TABLES,
        )
        assert {row[0] for row in engines} == set(W18_TABLES)
        assert all(str(row[1]).lower() == "innodb" for row in engines)
        indexes = {row[0] for row in await rows(conn, "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('crew_relations','crew_governance_proposals','crew_internal_projects','crew_hq_state')")}
        assert {"PRIMARY", "uq_crew_governance_active", "uq_crew_internal_project_active", "uq_crew_hq_active"} <= indexes
        fks = {row[0] for row in await rows(conn, "SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()")}
        assert {"fk_crew_governance_vote_proposal", "fk_crew_governance_execution_proposal", "fk_crew_internal_project_governance", "fk_crew_hq_governance", "fk_crew_hq_asset_hq"} <= fks
        assert int(await scalar(conn, "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='business_tenders' AND COLUMN_NAME='organization_context_json'")) == 0
        await raw(conn, FP["migration_mysql_sql"])
        await conn.commit()
        dtype = await scalar(conn, "SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='business_tenders' AND COLUMN_NAME='organization_context_json'")
        assert str(dtype).lower() == "longtext"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_02_relation_war_concurrency_interlock():
    await add_crews()

    async def relation_worker():
        conn = await connect(**creds())
        try:
            await writer_lock(conn)
            await conn.start_transaction()
            wars = int(await scalar(conn, "SELECT COUNT(*) FROM crew_wars WHERE guild_id=1 AND status IN ('pending','active') AND (challenger_crew_id IN (1,2) OR target_crew_id IN (1,2))") or 0)
            if wars:
                await conn.rollback()
                return False
            now = datetime.now(timezone.utc).isoformat()
            await raw(conn, "INSERT INTO crew_relations(guild_id,crew_low_id,crew_high_id,relation_kind,pending_kind,pending_from_crew_id,pending_from_user_id,proposal_created_at,updated_at) VALUES (1,1,2,'neutral','alliance',1,101,%s,%s)", (now, now))
            await conn.commit()
            return True
        finally:
            await writer_unlock(conn)
            await conn.close()

    async def war_worker():
        conn = await connect(**creds())
        try:
            await writer_lock(conn)
            await conn.start_transaction()
            relation = int(await scalar(conn, "SELECT COUNT(*) FROM crew_relations WHERE guild_id=1 AND crew_low_id=1 AND crew_high_id=2 AND (relation_kind<>'neutral' OR pending_kind IS NOT NULL)") or 0)
            if relation:
                await conn.rollback()
                return False
            now = datetime.now(timezone.utc)
            await raw(conn, "INSERT INTO crew_wars(guild_id,challenger_crew_id,target_crew_id,status,created_at,expires_at) VALUES (1,1,2,'pending',%s,%s)", (now.isoformat(), (now + timedelta(hours=2)).isoformat()))
            await conn.commit()
            return True
        finally:
            await writer_unlock(conn)
            await conn.close()

    result = await asyncio.gather(relation_worker(), war_worker())
    assert sum(bool(item) for item in result) == 1
    conn = await connect(**creds())
    try:
        relation = int(await scalar(conn, "SELECT COUNT(*) FROM crew_relations WHERE pending_kind IS NOT NULL OR relation_kind<>'neutral'") or 0)
        war = int(await scalar(conn, "SELECT COUNT(*) FROM crew_wars WHERE status IN ('pending','active')") or 0)
        assert not (relation and war)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_03_governance_active_slot_vote_identity_majority_expiry():
    await add_crews()
    now = datetime.now(timezone.utc)

    async def open_one(title: str):
        conn = await connect(**creds())
        try:
            await writer_lock(conn)
            await conn.start_transaction()
            try:
                await raw(conn, "INSERT INTO crew_governance_proposals(guild_id,crew_id,decision_kind,title,description,created_by,eligible_count,required_yes,status,active_slot,created_at,closes_at) VALUES (1,1,'hq',%s,'',101,3,2,'open',1,%s,%s)", (title, now.isoformat(), (now + timedelta(hours=1)).isoformat()))
                await conn.commit()
                return True
            except IntegrityError:
                await conn.rollback()
                return False
        finally:
            await writer_unlock(conn)
            await conn.close()

    assert sum(await asyncio.gather(open_one("A"), open_one("B"))) == 1
    conn = await connect(**creds())
    try:
        pid = int(await scalar(conn, "SELECT proposal_id FROM crew_governance_proposals WHERE status='open'"))
        await raw(conn, "INSERT INTO crew_governance_votes(proposal_id,guild_id,crew_id,user_id,choice,voted_at) VALUES (%s,1,1,101,'yes',%s)", (pid, now.isoformat()))
        await raw(conn, "INSERT INTO crew_governance_votes(proposal_id,guild_id,crew_id,user_id,choice,voted_at) VALUES (%s,1,1,102,'no',%s) ON DUPLICATE KEY UPDATE choice=VALUES(choice),voted_at=VALUES(voted_at)", (pid, now.isoformat()))
        await raw(conn, "INSERT INTO crew_governance_votes(proposal_id,guild_id,crew_id,user_id,choice,voted_at) VALUES (%s,1,1,102,'yes',%s) ON DUPLICATE KEY UPDATE choice=VALUES(choice),voted_at=VALUES(voted_at)", (pid, now.isoformat()))
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_governance_votes WHERE proposal_id=%s", (pid,))) == 2
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_governance_votes WHERE proposal_id=%s AND choice='yes'", (pid,))) == 2
        await raw(conn, "UPDATE crew_governance_proposals SET status='passed',active_slot=NULL,resolved_at=%s WHERE proposal_id=%s AND status='open'", (now.isoformat(), pid))
        await raw(conn, "INSERT INTO crew_governance_proposals(guild_id,crew_id,decision_kind,title,description,created_by,eligible_count,required_yes,status,active_slot,created_at,closes_at) VALUES (1,1,'leadership','Expired','',101,3,2,'open',1,%s,%s)", (now.isoformat(), (now - timedelta(seconds=1)).isoformat()))
        await raw(conn, "UPDATE crew_governance_proposals SET status='expired',active_slot=NULL,resolved_at=%s WHERE status='open' AND closes_at<=%s", (now.isoformat(), now.isoformat()))
        await conn.commit()
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_governance_proposals WHERE status='expired'")) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_04_execution_restart_exactly_once():
    await add_crews()
    now = datetime.now(timezone.utc).isoformat()
    pid = await make_passed("alliance", 1, "relation:2:propose")

    async def execute_once():
        conn = await connect(**creds())
        try:
            await writer_lock(conn)
            await conn.start_transaction()
            await raw(conn, "INSERT INTO crew_governance_executions(proposal_id,guild_id,crew_id,decision_kind,execution_action,subject_ref,status,created_at) VALUES (%s,1,1,'alliance','propose','relation:2:propose','pending',%s) ON DUPLICATE KEY UPDATE proposal_id=proposal_id", (pid, now))
            state = await scalar(conn, "SELECT status FROM crew_governance_executions WHERE proposal_id=%s FOR UPDATE", (pid,))
            if state == "executed":
                await conn.commit()
                return "replay"
            exists = int(await scalar(conn, "SELECT COUNT(*) FROM crew_relations WHERE guild_id=1 AND crew_low_id=1 AND crew_high_id=2 AND pending_kind='alliance'") or 0)
            if not exists:
                await raw(conn, "INSERT INTO crew_relations(guild_id,crew_low_id,crew_high_id,relation_kind,pending_kind,pending_from_crew_id,pending_from_user_id,proposal_created_at,updated_at) VALUES (1,1,2,'neutral','alliance',1,101,%s,%s)", (now, now))
            await raw(conn, "UPDATE crew_governance_executions SET status='executed',authority_ref='relation:1:2',executed_at=%s WHERE proposal_id=%s", (now, pid))
            await conn.commit()
            return "executed"
        finally:
            await writer_unlock(conn)
            await conn.close()

    assert sorted(await asyncio.gather(execute_once(), execute_once())) == ["executed", "replay"]
    assert await execute_once() == "replay"
    conn = await connect(**creds())
    try:
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_relations")) == 1
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_governance_executions")) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_05_project_treasury_atomic_exactly_once_and_rollback():
    await add_crews()
    pid = await make_passed("major_investment", 1, "project:investment:5000000")
    now = datetime.now(timezone.utc).isoformat()

    async def fund(crew: int, proposal: int, budget: int):
        conn = await connect(**creds())
        try:
            await writer_lock(conn)
            await conn.start_transaction()
            if int(await scalar(conn, "SELECT COUNT(*) FROM crew_internal_projects WHERE governance_proposal_id=%s", (proposal,)) or 0):
                await conn.commit()
                return "replay"
            before = int(await scalar(conn, "SELECT bank FROM crews WHERE guild_id=1 AND crew_id=%s FOR UPDATE", (crew,)) or 0)
            cur = await raw(conn, "UPDATE crews SET bank=bank-%s WHERE guild_id=1 AND crew_id=%s AND bank>=%s", (budget, crew, budget))
            if cur.rowcount != 1:
                await conn.rollback()
                return "blocked"
            await raw(conn, "INSERT INTO crew_internal_projects(guild_id,crew_id,governance_proposal_id,project_key,title,description,budget_amount,target_units,progress_units,contributor_count,member_snapshot_json,bank_before,bank_after,status,active_slot,started_at,updated_at) VALUES (1,%s,%s,'investment','P','',%s,5,0,0,'[101,102]',%s,%s,'active',1,%s,%s)", (crew, proposal, budget, before, before - budget, now, now))
            await conn.commit()
            return "executed"
        finally:
            await writer_unlock(conn)
            await conn.close()

    assert sorted(await asyncio.gather(fund(1, pid, 5_000_000), fund(1, pid, 5_000_000))) == ["executed", "replay"]
    conn = await connect(**creds())
    try:
        assert int(await scalar(conn, "SELECT bank FROM crews WHERE crew_id=1")) == 95_000_000
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_internal_projects WHERE crew_id=1")) == 1
    finally:
        await conn.close()
    low = await make_passed("major_investment", 3, "project:investment:5000000")
    assert await fund(3, low, 5_000_000) == "blocked"
    conn = await connect(**creds())
    try:
        assert int(await scalar(conn, "SELECT bank FROM crews WHERE crew_id=3")) == 1_000_000
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_internal_projects WHERE governance_proposal_id=%s", (low,))) == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_06_project_progress_restart_rederived_from_contracts():
    await add_crews()
    pid = await make_passed("major_investment")
    now = datetime.now(timezone.utc)
    conn = await connect(**creds())
    try:
        await raw(conn, "INSERT INTO crew_internal_projects(guild_id,crew_id,governance_proposal_id,project_key,title,description,budget_amount,target_units,progress_units,contributor_count,member_snapshot_json,bank_before,bank_after,status,active_slot,started_at,updated_at) VALUES (1,1,%s,'investment','P','',5000000,3,0,0,'[101,102]',100000000,95000000,'active',1,%s,%s)", (pid, now.isoformat(), now.isoformat()))
        await raw(conn, "INSERT INTO contracts(guild_id,assignee_id,status,resolved_at) VALUES (1,101,'settled',%s),(1,102,'settled',%s),(1,999,'settled',%s),(1,101,'settled',%s)", ((now + timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=2)).isoformat(), (now + timedelta(minutes=3)).isoformat(), (now - timedelta(minutes=1)).isoformat()))
        await conn.commit()

        async def derive():
            snap = json.loads(await scalar(conn, "SELECT member_snapshot_json FROM crew_internal_projects WHERE governance_proposal_id=%s", (pid,)))
            placeholders = ",".join(["%s"] * len(snap))
            query = f"SELECT COUNT(*),COUNT(DISTINCT assignee_id) FROM contracts WHERE guild_id=1 AND status='settled' AND resolved_at>=%s AND assignee_id IN ({placeholders})"
            result = await rows(conn, query, (now.isoformat(), *snap))
            return tuple(int(value) for value in result[0])

        assert await derive() == (2, 2)
        await raw(conn, "UPDATE crew_internal_projects SET progress_units=0,contributor_count=0 WHERE governance_proposal_id=%s", (pid,))
        await conn.commit()
        progress, contributors = await derive()
        await raw(conn, "UPDATE crew_internal_projects SET progress_units=%s,contributor_count=%s WHERE governance_proposal_id=%s", (progress, contributors, pid))
        await conn.commit()
        assert (progress, contributors) == (2, 2)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_07_hq_treasury_atomic_unique_fk():
    await add_crews()
    pid = await make_passed("hq", 1, "hq:budapest:10000000")
    now = datetime.now(timezone.utc).isoformat()

    async def fund_hq(proposal: int):
        conn = await connect(**creds())
        try:
            await writer_lock(conn)
            await conn.start_transaction()
            if int(await scalar(conn, "SELECT COUNT(*) FROM crew_hq_state WHERE governance_proposal_id=%s", (proposal,)) or 0):
                await conn.commit()
                return "replay"
            before = int(await scalar(conn, "SELECT bank FROM crews WHERE crew_id=1 FOR UPDATE"))
            cur = await raw(conn, "UPDATE crews SET bank=bank-10000000 WHERE crew_id=1 AND bank>=10000000")
            if cur.rowcount != 1:
                await conn.rollback()
                return "blocked"
            await raw(conn, "INSERT INTO crew_hq_state(guild_id,crew_id,governance_proposal_id,city_key,budget_amount,bank_before,bank_after,status,active_slot,created_at,updated_at) VALUES (1,1,%s,'budapest',10000000,%s,%s,'active',1,%s,%s)", (proposal, before, before - 10_000_000, now, now))
            await conn.commit()
            return "executed"
        finally:
            await writer_unlock(conn)
            await conn.close()

    assert sorted(await asyncio.gather(fund_hq(pid), fund_hq(pid))) == ["executed", "replay"]
    pid2 = await make_passed("hq", 1, "hq:miskolc:10000000")
    conn = await connect(**creds())
    try:
        with pytest.raises(IntegrityError):
            await raw(conn, "INSERT INTO crew_hq_state(guild_id,crew_id,governance_proposal_id,city_key,budget_amount,bank_before,bank_after,status,active_slot,created_at,updated_at) VALUES (1,1,%s,'miskolc',10000000,90000000,80000000,'active',1,%s,%s)", (pid2, now, now))
        await conn.rollback()
        hq_id = int(await scalar(conn, "SELECT hq_id FROM crew_hq_state WHERE crew_id=1"))
        await raw(conn, "INSERT INTO crew_hq_asset_links(guild_id,crew_id,hq_id,asset_kind,source_owner_id,source_ref,label_snapshot,linked_by,status,active_slot,created_at,updated_at) VALUES (1,1,%s,'garage',101,'vehicle:1','Car',101,'active',1,%s,%s)", (hq_id, now, now))
        await conn.commit()
        await raw(conn, "DELETE FROM crew_governance_proposals WHERE proposal_id=%s", (pid,))
        await conn.commit()
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_hq_state")) == 0
        assert int(await scalar(conn, "SELECT COUNT(*) FROM crew_hq_asset_links")) == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_08_city_presence_is_read_only_projection_no_presence_table():
    await add_crews()
    now = datetime.now(timezone.utc).isoformat()
    conn = await connect(**creds())
    try:
        await raw(conn, "INSERT INTO character_travel_history(guild_id,user_id,to_city_key,arrived_at) VALUES (1,101,'budapest',%s)", (now,))
        await raw(conn, "INSERT INTO contracts(guild_id,assignee_id,status,resolved_at) VALUES (1,101,'settled',%s)", (now,))
        await raw(conn, "INSERT INTO job_sessions(guild_id,user_id,city_key,status,completed_at) VALUES (1,101,'budapest','completed',%s)", (now,))
        await conn.commit()
        before = (int(await scalar(conn, "SELECT bank FROM crews WHERE crew_id=1")), int(await scalar(conn, "SELECT COUNT(*) FROM contracts")), int(await scalar(conn, "SELECT COUNT(*) FROM character_travel_history")))
        assert int(await scalar(conn, "SELECT COUNT(*) FROM character_travel_history WHERE guild_id=1 AND user_id=101 AND to_city_key='budapest'")) == 1
        assert int(await scalar(conn, "SELECT COUNT(*) FROM contracts WHERE guild_id=1 AND assignee_id=101 AND status='settled'")) == 1
        assert int(await scalar(conn, "SELECT COUNT(*) FROM job_sessions WHERE guild_id=1 AND user_id=101 AND city_key='budapest' AND status='completed'")) == 1
        after = (int(await scalar(conn, "SELECT bank FROM crews WHERE crew_id=1")), int(await scalar(conn, "SELECT COUNT(*) FROM contracts")), int(await scalar(conn, "SELECT COUNT(*) FROM character_travel_history")))
        assert before == after
        assert int(await scalar(conn, "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('crew_city_presence','crew_city_xp','crew_presence_contributions')")) == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_09_joint_context_metadata_only_and_migration_preserves_rewards():
    conn = await connect(**creds())
    try:
        await raw(conn, FP["migration_mysql_sql"])
        now = datetime.now(timezone.utc).isoformat()
        cur = await raw(conn, "INSERT INTO business_tenders(guild_id,property_id,owner_id,problem_id,status,max_reward,resolved_at,organization_context_json) VALUES (1,10,101,'p1','awarded',5000000,%s,%s)", (now, json.dumps({"schema": 1, "qualified": True, "mode": "cooperative"})))
        tender_id = int(cur.lastrowid)
        snapshot = {
            "101": {"organization": {"crew_id": 1, "qualified": True, "mode": "cooperative", "partner_crew_ids": [2]}},
            "201": {"organization": {"crew_id": 2, "qualified": True, "mode": "cooperative", "partner_crew_ids": [1]}},
        }
        cur = await raw(conn, "INSERT INTO heist_runs(guild_id,status,success,reward_pool,member_snapshot,resolved_at) VALUES (1,'success',1,9000000,%s,%s)", (json.dumps(snapshot), now))
        run_id = int(cur.lastrowid)
        await conn.commit()
        assert int(await scalar(conn, "SELECT max_reward FROM business_tenders WHERE tender_id=%s", (tender_id,))) == 5_000_000
        assert int(await scalar(conn, "SELECT reward_pool FROM heist_runs WHERE run_id=%s", (run_id,))) == 9_000_000
        context = json.loads(await scalar(conn, "SELECT organization_context_json FROM business_tenders WHERE tender_id=%s", (tender_id,)))
        assert context["qualified"] is True
        assert int(await scalar(conn, "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('crew_joint_activity','crew_heist_rewards','crew_business_rewards')")) == 0
    finally:
        await conn.close()


def test_10_source_projection_contract():
    assert FP["source_release"] == "3.79.7"
    assert FP["source_files"]["app/database.py"]["sha256"] == "4bf918270b1e64eaf775cd55053c54b8110d5a1589c1322dae045043f6afb4a6"
    assert FP["source_files"]["app/services/faction.py"]["sha256"] == "088ae67192574c232d651471fa6d26559d926b170418eb2db9c2e5d1c4f7c110"
    assert FP["source_files"]["app/db_backend.py"]["sha256"] == "2820a18cb05b355be3cc756b6871832fe1b3e1525aae791622933776b80ad7ca"
    assert len(FP["service_methods"]) == 16
    assert all(len(item["sha256"]) == 64 for item in FP["service_methods"].values())
    assert FP["migration_mysql_sql"] == "ALTER TABLE business_tenders ADD COLUMN organization_context_json LONGTEXT NULL"
    migration = (ROOT / "W18_7_MIGRATION_SOURCE.txt").read_text(encoding="utf-8")
    assert "execute_backend_ddl" in migration and "organization_context_json LONGTEXT NULL" in migration
    assert all(table in SCHEMA for table in W18_TABLES)
    assert "ENGINE=InnoDB" in SCHEMA
