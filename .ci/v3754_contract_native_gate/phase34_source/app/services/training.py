# STATIC_CONTRACT: training_enrolled
# STATIC_CONTRACT: training_enrolled(
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Any
from app import db_backend as aiosqlite
from app import training_config as cfg
from app.database import Database
from app.services.characters import CharacterService
from app.services.memory_adapters import MemoryAdapterService
logger = logging.getLogger('vaultbot.training')

def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _score_stat(course_key: str) -> str:
    return f'training.score.{course_key}'

def _attempt_stat(course_key: str) -> str:
    return f'training.attempts.{course_key}'

def _failure_stat(course_key: str) -> str:
    return f'training.failures.{course_key}'

def _success_stat(course_key: str) -> str:
    return f'training.successes.{course_key}'

@dataclass(frozen=True, slots=True)
class Qualification:
    guild_id: int
    user_id: int
    qualification_key: str
    course_key: str
    acquired_at: str

@dataclass(frozen=True, slots=True)
class TrainingSession:
    guild_id: int
    user_id: int
    course_key: str
    status: str
    stage_index: int
    started_at: str
    updated_at: str
    completed_at: str | None

@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    session: TrainingSession
    price: int
    wallet_used: int
    bank_used: int
    new_wallet: int
    new_bank: int
    retry: bool = False

@dataclass(frozen=True, slots=True)
class StageResult:
    session: TrainingSession
    message: str
    advanced: bool
    completed: bool
    failed: bool = False
    qualification: Qualification | None = None

class TrainingService:
    """Restart-safe, scored RP training and qualification service.

    v3.56 keeps assessment state in the namespaced statistics table so the
    rework remains compatible with the already-migrated MySQL schema. Exact
    scores are deliberately internal; the player only receives situational
    feedback and the final exam result.
    """

    def __init__(self, database: Database, characters: CharacterService, memory_adapters: MemoryAdapterService | None=None) -> None:
        self.database = database
        self.characters = characters
        self.memory_adapters = memory_adapters

    @staticmethod
    def _session_from_row(row: Any) -> TrainingSession:
        return TrainingSession(guild_id=int(row[0]), user_id=int(row[1]), course_key=str(row[2]), status=str(row[3]), stage_index=int(row[4]), started_at=str(row[5]), updated_at=str(row[6]), completed_at=str(row[7]) if row[7] is not None else None)

    @staticmethod
    def _qualification_from_row(row: Any) -> Qualification:
        return Qualification(guild_id=int(row[0]), user_id=int(row[1]), qualification_key=str(row[2]), course_key=str(row[3]), acquired_at=str(row[4]))

    @staticmethod
    async def _set_stat(db: Any, guild_id: int, user_id: int, stat_name: str, value: int, now: str) -> None:
        await db.execute('INSERT INTO user_statistics (guild_id,user_id,stat_name,value,updated_at)\n               VALUES (?,?,?,?,?)\n               ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET\n                   value=excluded.value, updated_at=excluded.updated_at', (guild_id, user_id, stat_name, int(value), now))

    @staticmethod
    async def _increment_stat(db: Any, guild_id: int, user_id: int, stat_name: str, amount: int, now: str) -> None:
        await db.execute('INSERT INTO user_statistics (guild_id,user_id,stat_name,value,updated_at)\n               VALUES (?,?,?,?,?)\n               ON CONFLICT(guild_id,user_id,stat_name) DO UPDATE SET\n                   value=value+excluded.value, updated_at=excluded.updated_at', (guild_id, user_id, stat_name, int(amount), now))

    async def qualifications(self, guild_id: int, user_id: int) -> list[Qualification]:
        await self.characters.require(guild_id, user_id)
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute('SELECT guild_id,user_id,qualification_key,course_key,acquired_at\n                   FROM character_qualifications\n                   WHERE guild_id=? AND user_id=?\n                   ORDER BY acquired_at, qualification_key', (guild_id, user_id))
            rows = await cursor.fetchall()
        return [self._qualification_from_row(row) for row in rows]

    async def session_for_course(self, guild_id: int, user_id: int, course_key: str) -> TrainingSession | None:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute('SELECT guild_id,user_id,course_key,status,stage_index,started_at,updated_at,completed_at\n                   FROM training_sessions WHERE guild_id=? AND user_id=? AND course_key=?', (guild_id, user_id, str(course_key)))
            row = await cursor.fetchone()
        return self._session_from_row(row) if row is not None else None

    async def choose(self, guild_id: int, user_id: int, *, course_key: str, expected_stage: int, choice_key: str) -> StageResult:
        await self.characters.require(guild_id, user_id)
        course = cfg.course(course_key)
        if expected_stage < 0 or expected_stage >= len(course.stages):
            raise ValueError('A képzés szakasza nem található. Nyisd meg újra a Képzési Központot.')
        stage = course.stages[expected_stage]
        choice = next((item for item in stage.choices if item.key == str(choice_key)), None)
        if choice is None:
            raise ValueError('Ez a választás már nem érvényes. Nyisd meg újra a képzést.')
        now = _iso()
        passed = False
        failed = False
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            try:
                cursor = await db.execute('SELECT guild_id,user_id,course_key,status,stage_index,started_at,updated_at,completed_at\n                       FROM training_sessions\n                       WHERE guild_id=? AND user_id=? AND course_key=?', (guild_id, user_id, course.key))
                row = await cursor.fetchone()
                if row is None or str(row[3]) != 'active':
                    raise ValueError('Ez a képzés már nem aktív. Nyisd meg újra a Képzési Központot.')
                current_stage = int(row[4])
                if current_stage != int(expected_stage):
                    raise ValueError('A képzésed közben továbblépett. Nyisd meg újra a panelt.')
                score_cur = await db.execute('SELECT value FROM user_statistics WHERE guild_id=? AND user_id=? AND stat_name=?', (guild_id, user_id, _score_stat(course.key)))
                score_row = await score_cur.fetchone()
                current_score = int(score_row[0]) if score_row is not None else current_stage * 2
                new_score = current_score + int(choice.score_delta)
                await self._set_stat(db, guild_id, user_id, _score_stat(course.key), new_score, now)
                next_stage = current_stage + 1
                finished = next_stage >= len(course.stages)
                if finished:
                    passed = new_score >= int(course.pass_score)
                    failed = not passed
                    final_status = 'completed' if passed else 'failed'
                    await db.execute('UPDATE training_sessions\n                           SET status=?,stage_index=?,updated_at=?,completed_at=?\n                           WHERE guild_id=? AND user_id=? AND course_key=?', (final_status, len(course.stages), now, now, guild_id, user_id, course.key))
                    if passed:
                        await db.execute('INSERT OR IGNORE INTO character_qualifications\n                               (guild_id,user_id,qualification_key,course_key,acquired_at)\n                               VALUES (?,?,?,?,?)', (guild_id, user_id, course.key, course.key, now))
                        await self._increment_stat(db, guild_id, user_id, _success_stat(course.key), 1, now)
                        event_key = f'qualification_{course.key}'
                        history_cur = await db.execute('SELECT 1 FROM character_history WHERE guild_id=? AND user_id=? AND event_key=? LIMIT 1', (guild_id, user_id, event_key))
                        if await history_cur.fetchone() is None:
                            await db.execute('INSERT INTO character_history\n                                   (guild_id,user_id,event_key,title,description,metadata_json,created_at)\n                                   VALUES (?,?,?,?,?,?,?)', (guild_id, user_id, event_key, f'{course.qualification_name} megszerezve', course.history_text, json.dumps({'course': course.key, 'qualification': course.key}, ensure_ascii=False, separators=(',', ':')), now))
                    else:
                        await self._increment_stat(db, guild_id, user_id, _failure_stat(course.key), 1, now)
                else:
                    await db.execute('UPDATE training_sessions SET stage_index=?,updated_at=?\n                           WHERE guild_id=? AND user_id=? AND course_key=?', (next_stage, now, guild_id, user_id, course.key))
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        session = await self.session_for_course(guild_id, user_id, course.key)
        if session is None:
            raise RuntimeError('A képzés állapotát nem sikerült visszaolvasni.')
        qualification: Qualification | None = None
        if passed:
            quals = await self.qualifications(guild_id, user_id)
            qualification = next((q for q in quals if q.qualification_key == course.key), None)
            if self.memory_adapters is not None:
                try:
                    await self.memory_adapters.training_completed(guild_id, user_id, course_key=course.key, completed_at=now)
                except Exception:
                    logger.exception('Training consequence memory failed guild=%s user=%s course=%s', guild_id, user_id, course.key)
        return StageResult(session=session, message=choice.outcome, advanced=True, completed=passed, failed=failed, qualification=qualification)
