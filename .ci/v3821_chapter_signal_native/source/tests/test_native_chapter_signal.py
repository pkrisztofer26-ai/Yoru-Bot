from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from app import db_backend as db
from app.services.chapters import ChapterService


DB = SimpleNamespace(path="native")
DDL = [item.strip() for item in Path("HISTORY_SCHEMA.sql").read_text().split(";") if item.strip()]
TABLES = (
    "character_memory_state", "contract_objectives", "contracts",
    "rp_world_community_project_outcomes", "player_scenario_history",
    "rp_world_causality_signals", "rp_world_chapters",
)


@pytest.fixture(autouse=True)
async def reset_schema():
    async with db.connect(DB.path) as conn:
        for table in TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
        for statement in DDL:
            await conn.execute(statement)
        await conn.execute("INSERT INTO rp_world_chapters(guild_id,chapter_key,status,current_stage_key,started_at,stage_started_at,deadline_at,updated_at,resolution_snapshot_json) VALUES(42,'fault_lines','active','omens','2026-08-01T00:00:00+00:00','2026-08-01T00:00:00+00:00','2026-08-22T00:00:00+00:00','2026-08-01T00:00:00+00:00','{}')")
        await conn.commit()
    yield


async def seed():
    async with db.connect(DB.path) as conn:
        await conn.execute("INSERT INTO rp_world_causality_signals(guild_id,domain,units,occurred_at) VALUES(42,'community',8,'2026-08-02T00:00:00+00:00'),(42,'business',7,'2026-08-03T00:00:00+00:00'),(42,'crime',2,'2026-08-04T00:00:00+00:00')")
        await conn.execute("INSERT INTO player_scenario_history(guild_id,domain,completed_at) VALUES(42,'social','2026-08-05T00:00:00+00:00'),(42,'crime','2026-08-06T00:00:00+00:00')")
        await conn.execute("INSERT INTO rp_world_community_project_outcomes(guild_id,result_status,branch_key,career_units,business_units,recorded_at) VALUES(42,'completed','community_recovery',20,20,'2026-08-07T00:00:00+00:00')")
        await conn.execute("INSERT INTO contracts VALUES(5,42,'settled','2026-08-08T00:00:00+00:00')")
        await conn.execute("INSERT INTO contract_objectives(contract_id,guild_id,objective_type,status) VALUES(5,42,'business_delivery','completed')")
        await conn.execute("INSERT INTO character_memory_state(guild_id,category,active,occurred_at) VALUES(42,'favor',1,'2026-08-09T00:00:00+00:00'),(42,'crime',1,'2026-08-10T00:00:00+00:00')")
        await conn.commit()


@pytest.mark.asyncio
async def test_01_all_history_tables_are_innodb():
    async with db.connect(DB.path) as conn:
        for table in TABLES:
            row = await (await conn.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?", (table,))).fetchone()
            assert row and str(row[0]).lower() == "innodb"


@pytest.mark.asyncio
async def test_02_projection_is_replay_stable():
    await seed(); svc = ChapterService(DB, None)
    assert await svc.ending_weights(42, ensure=False) == await svc.ending_weights(42, ensure=False)


@pytest.mark.asyncio
async def test_03_committed_sources_map_to_expected_direction():
    await seed(); result = await ChapterService(DB, None).ending_weights(42, ensure=False)
    assert result is not None
    assert dict(result.source_counts) == {"causality": 3, "scenario": 2, "community_project": 1, "contract": 1, "memory": 2}
    assert dict(result.weights)["shared_recovery"] > dict(result.weights)["shadow_network"]


def test_04_normalization_and_hard_cap():
    empty = ChapterService._normalize_weights({})
    extreme = ChapterService._normalize_weights({"shadow_network": 10000})
    assert empty == (("shared_recovery",34),("fractured_balance",33),("shadow_network",33))
    assert sum(value for _, value in extreme) == 100
    assert dict(extreme)["shadow_network"] == 65


@pytest.mark.asyncio
async def test_05_projection_does_not_write_chapter_resolution():
    await seed(); svc = ChapterService(DB, None)
    await svc.ending_weights(42, ensure=False)
    async with db.connect(DB.path) as conn:
        row = await (await conn.execute("SELECT status,ending_key,resolution_snapshot_json FROM rp_world_chapters WHERE guild_id=42")).fetchone()
    assert row == ("active", None, "{}")


@pytest.mark.asyncio
async def test_06_no_score_choice_or_reward_tables():
    async with db.connect(DB.path) as conn:
        rows = await (await conn.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('chapter_scores','chapter_choices','chapter_rewards')")).fetchall()
    assert rows == []
