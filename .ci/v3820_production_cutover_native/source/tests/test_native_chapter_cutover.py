from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from app import db_backend as aiosqlite
from app.services.chapters import ChapterService

DDL=Path('CHAPTER_SCHEMA.sql').read_text(encoding='utf-8')
DB=SimpleNamespace(path='unused-under-mysql')

async def reset_table():
    async with aiosqlite.connect(DB.path) as conn:
        await conn.execute('DROP TABLE IF EXISTS rp_world_chapters')
        await conn.execute(DDL)
        await conn.commit()

@pytest.fixture(autouse=True)
async def _fresh_schema():
    await reset_table()
    yield

@pytest.mark.asyncio
async def test_01_innodb_schema_and_indexes():
    async with aiosqlite.connect(DB.path) as conn:
        cur=await conn.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='rp_world_chapters'")
        row=await cur.fetchone(); assert row and str(row[0]).lower()=='innodb'
        rows=await (await conn.execute('SHOW INDEX FROM rp_world_chapters')).fetchall()
        keys={str(r[2]) for r in rows}
        assert {'PRIMARY','uq_rp_world_chapter_active','idx_rp_world_chapter_history','idx_rp_world_chapter_status'} <= keys

@pytest.mark.asyncio
async def test_02_replay_start_is_single_row():
    svc=ChapterService(DB, None); at=datetime(2026,8,25,tzinfo=timezone.utc)
    a=await svc.start(1,at=at); b=await svc.start(1,at=at+timedelta(minutes=5))
    assert a.chapter_run_id==b.chapter_run_id
    assert len(await svc.history(1))==1

@pytest.mark.asyncio
async def test_03_concurrent_start_converges():
    svc=ChapterService(DB, None); at=datetime(2026,8,25,tzinfo=timezone.utc)
    rows=await asyncio.gather(*(svc.start(77,at=at) for _ in range(5)))
    assert len({r.chapter_run_id for r in rows})==1
    assert len(await svc.history(77))==1

@pytest.mark.asyncio
async def test_04_unique_active_slot_rejects_second_active():
    now='2026-08-25T00:00:00+00:00'; deadline='2026-09-15T00:00:00+00:00'
    async with aiosqlite.connect(DB.path) as conn:
        await conn.execute("INSERT INTO rp_world_chapters(guild_id,chapter_key,status,active_slot,current_stage_key,started_at,stage_started_at,deadline_at,updated_at,resolution_snapshot_json) VALUES(1,'fault_lines','active',1,'omens',?,?,?,?, '{}')",(now,now,deadline,now))
        await conn.commit()
    with pytest.raises(Exception):
        async with aiosqlite.connect(DB.path) as conn:
            await conn.execute("INSERT INTO rp_world_chapters(guild_id,chapter_key,status,active_slot,current_stage_key,started_at,stage_started_at,deadline_at,updated_at,resolution_snapshot_json) VALUES(1,'fault_lines','active',1,'omens',?,?,?,?, '{}')",(now,now,deadline,now))
            await conn.commit()
    async with aiosqlite.connect(DB.path) as conn:
        count=(await (await conn.execute('SELECT COUNT(*) FROM rp_world_chapters WHERE guild_id=1')).fetchone())[0]
    assert int(count)==1

@pytest.mark.asyncio
async def test_05_stage_pacing_native():
    svc=ChapterService(DB,None); start=datetime(2026,8,25,tzinfo=timezone.utc)
    r=await svc.start(2,at=start); assert r.current_stage_key=='omens'
    r=await svc.refresh(2,at=start+timedelta(days=8)); assert (r.current_stage_key,r.status)==('pressure','active')
    r=await svc.refresh(2,at=start+timedelta(days=15)); assert (r.current_stage_key,r.status)==('turning_point','active') and r.ending_key is None

@pytest.mark.asyncio
async def test_06_deadline_stops_without_ending():
    svc=ChapterService(DB,None); start=datetime(2026,8,25,tzinfo=timezone.utc)
    await svc.start(3,at=start)
    r=await svc.refresh(3,at=start+timedelta(days=22))
    assert r.status=='awaiting_resolution' and r.current_stage_key=='turning_point'
    assert r.ending_key is None and r.resolved_at is None and r.resolution_snapshot=={}

@pytest.mark.asyncio
async def test_07_awaiting_resolution_is_replay_stable():
    svc=ChapterService(DB,None); start=datetime(2026,8,25,tzinfo=timezone.utc)
    await svc.start(4,at=start)
    a=await svc.refresh(4,at=start+timedelta(days=22))
    b=await svc.refresh(4,at=start+timedelta(days=25))
    assert b.chapter_run_id==a.chapter_run_id and b.status=='awaiting_resolution' and b.ending_key is None


def test_08_source_has_no_ending_or_reward_authority():
    source=Path('app/services/chapters.py').read_text(encoding='utf-8').lower()
    for bad in ('random.choice','rng.random','chapter_xp','chapter_score','chapter_payout','credit_wallet','reserve_wallet','insert into contracts'):
        assert bad not in source
    assert "status='awaiting_resolution'" in source
