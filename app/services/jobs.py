from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite

from app import jobs_config as cfg
from app.job_framework import (
    DecisionScenario,
    GridGame,
    PerformanceRating,
    RiskCashout,
    ScenarioChoice,
    SequenceGame,
    clamp_score,
)
from app.services.server_settings import ServerSettingsService
from app.services.gameplay_settings import GameplaySettingsService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _utcnow().isoformat()


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} óra")
    if minutes:
        parts.append(f"{minutes} perc")
    if not parts:
        parts.append(f"{max(1, secs)} mp")
    return " ".join(parts)


class JobBusyError(ValueError):
    pass


class JobCooldownError(ValueError):
    def __init__(self, job: str, remaining_seconds: float, *, abandoned: bool = False) -> None:
        self.job = job
        self.remaining_seconds = max(0.0, float(remaining_seconds))
        self.available_at = _utcnow() + timedelta(seconds=self.remaining_seconds)
        self.abandoned = bool(abandoned)
        if abandoned:
            message = f"Az előző műszak félbemaradt. Új Jobs műszak: {_format_duration(self.remaining_seconds)} múlva."
        else:
            message = f"A Jobs közös cooldownja még aktív. Új műszak: {_format_duration(self.remaining_seconds)} múlva."
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class JobResult:
    session_id: str
    job: str
    base_reward: int
    reward: int
    score: int
    rating: str
    mastery_xp: int
    mastery_level: int
    wallet: int


WAREHOUSE_TOKENS = ("A12", "C04", "B17", "A08", "D03", "F11", "C19", "B02", "E07", "A21", "D14", "F05")
BORSOD_LOOT = (
    # Kept at the v3.22.0 calibration. v3.22.1 changes interaction/pacing, not the target economy band.
    ("🔩", 42_000, 20), ("🔌", 93_000, 15), ("📺", 117_000, 10), ("🚲", 158_000, 6),
    ("💵", 138_000, 9), ("📦", 248_000, 3), ("🗑️", 6_000, 25), ("🧯", 27_000, 12),
)
COURIER_ASSIGNMENTS = (
    "Csomag a vasútállomásra", "Sürgős gyógyszercsomag", "Utánvétes műszaki cucc", "Két cím egy utcában",
    "Elírt házszámos csomag", "Törékeny küldemény", "Utolsó perces expressz", "Nagy csomag a negyedikre",
)
TAXI_PASSENGERS = (
    "Pista bácsi → Vasútállomás", "Éjszakás melós → Ipari park", "Késésben lévő utas → Buszpályaudvar",
    "Két bőrönd → Belváros", "Morgós utas → Kórház", "Turista → Vár", "Sietős diák → Egyetem",
)

ROUTES = {
    "safe": {"label": "Rövid / biztos", "base": (52_000, 72_000), "score": (5, 11), "risk_penalty": 0.00},
    "long": {"label": "Hosszabb / jobb fizu", "base": (72_000, 105_000), "score": (1, 9), "risk_penalty": 0.05},
    "risky": {"label": "Problémás / magas reward", "base": (92_000, 138_000), "score": (-7, 10), "risk_penalty": 0.12},
}


def _choice(
    key: str,
    label: str,
    emoji: str,
    *,
    description: str = "",
    chance: float = 1.0,
    reward_success: float = 1.0,
    reward_fail: float = 0.65,
    score_success: int = 0,
    score_fail: int = -8,
    continue_success: bool = True,
    continue_fail: bool = True,
    default: bool = False,
) -> ScenarioChoice:
    return ScenarioChoice(
        key=key,
        label=label,
        emoji=emoji,
        description=description,
        success_chance=chance,
        reward_success=reward_success,
        reward_fail=reward_fail,
        score_success=score_success,
        score_fail=score_fail,
        continue_on_success=continue_success,
        continue_on_fail=continue_fail,
        default=default,
    )


TRANSPORT_SCENARIOS: dict[str, tuple[DecisionScenario, ...]] = {
    "courier": (
        DecisionScenario(
            "police_check",
            "Rendőri ellenőrzés",
            "Leintenek az út szélén. Mit csinálsz a sürgős csomaggal?",
            (
                _choice("papers", "Felmutatod az iratokat", "🪪", chance=1.0, reward_success=0.92, score_success=6, default=True),
                _choice("detour", "Még előtte kerülőre mész", "↪️", chance=0.78, reward_success=1.05, reward_fail=0.72, score_success=3, score_fail=-7),
                _choice("drive", "Elhajtasz", "💨", chance=0.48, reward_success=1.18, reward_fail=0.38, score_success=8, score_fail=-22, continue_fail=False),
            ),
        ),
        DecisionScenario(
            "damaged_package",
            "Sérült csomag",
            "Megcsúszott a doboz, a sarka csúnyán benyomódott.",
            (
                _choice("report", "Jelented és dokumentálod", "📷", chance=1.0, reward_success=0.90, score_success=8, default=True),
                _choice("repack", "Gyorsan újracsomagolod", "📦", chance=0.82, reward_success=1.08, reward_fail=0.72, score_success=5, score_fail=-9),
                _choice("ignore", "Úgy adod át, mintha semmi", "😶", chance=0.55, reward_success=1.15, reward_fail=0.45, score_success=1, score_fail=-18),
            ),
        ),
        DecisionScenario(
            "bad_address",
            "Rossz cím",
            "A házszám nem létezik, a címzett pedig sehol.",
            (
                _choice("call", "Felhívod a címzettet", "📞", chance=1.0, reward_success=0.96, score_success=6, default=True),
                _choice("ask", "Rákérdezel a környéken", "🗣️", chance=0.84, reward_success=1.06, reward_fail=0.76, score_success=4, score_fail=-5),
                _choice("door", "Leteszed a legközelebbi ajtóhoz", "🚪", chance=0.50, reward_success=1.16, reward_fail=0.40, score_success=2, score_fail=-20),
            ),
        ),
        DecisionScenario(
            "roadblock",
            "Útlezárás",
            "A megszokott út lezárva. Az idő viszont ketyeg.",
            (
                _choice("wait", "Kivárod a terelést", "⏳", chance=1.0, reward_success=0.91, score_success=5, default=True),
                _choice("detour", "Navigációs kerülő", "🗺️", chance=0.86, reward_success=1.06, reward_fail=0.78, score_success=4, score_fail=-5),
                _choice("shortcut", "Bevállalsz egy rövidítést", "⚡", chance=0.62, reward_success=1.18, reward_fail=0.52, score_success=7, score_fail=-14),
            ),
        ),
    ),
    "taxi": (
        DecisionScenario(
            "police_check",
            "Rendőri ellenőrzés",
            "Leintenek, az utas közben azt mondja, hogy nagyon siet.",
            (
                _choice("papers", "Megállsz és felmutatod az iratokat", "🪪", chance=1.0, reward_success=0.93, score_success=7, default=True),
                _choice("detour", "Még előtte másik utcára fordulsz", "↪️", chance=0.78, reward_success=1.06, reward_fail=0.72, score_success=3, score_fail=-7),
                _choice("drive", "Elhajtasz", "💨", chance=0.46, reward_success=1.20, reward_fail=0.35, score_success=9, score_fail=-24, continue_fail=False),
            ),
        ),
        DecisionScenario(
            "speeding_request",
            "„Nyomjad neki!”",
            "Az utas extra borravalót ígér, ha behozod a késést.",
            (
                _choice("legal", "Szabályosan mész tovább", "🟢", chance=1.0, reward_success=0.96, score_success=6, default=True),
                _choice("fast_route", "Gyorsabb útvonalat keresel", "🗺️", chance=0.86, reward_success=1.10, reward_fail=0.80, score_success=5, score_fail=-5),
                _choice("floor_it", "Bevállalod a tempót", "🔥", chance=0.60, reward_success=1.24, reward_fail=0.50, score_success=8, score_fail=-16),
            ),
        ),
        DecisionScenario(
            "sick_passenger",
            "Rosszul lett az utas",
            "Az utas elsápad és azt mondja, nincs jól.",
            (
                _choice("hospital", "A kórház felé indulsz", "🏥", chance=1.0, reward_success=0.88, score_success=12, default=True),
                _choice("ambulance", "Félreállsz és segítséget hívsz", "🚑", chance=1.0, reward_success=0.82, score_success=14),
                _choice("destination", "Megkérdezed, bírja-e a célig", "➡️", chance=0.68, reward_success=1.10, reward_fail=0.55, score_success=2, score_fail=-17),
            ),
        ),
        DecisionScenario(
            "payment_issue",
            "Fizetési gond",
            "A célhoz érve kiderül, hogy az utasnál nincs elég készpénz.",
            (
                _choice("transfer", "Kérsz átutalást", "📲", chance=1.0, reward_success=0.95, score_success=6, default=True),
                _choice("later", "Megbízol benne, később fizet", "🤝", chance=0.72, reward_success=1.16, reward_fail=0.48, score_success=7, score_fail=-12),
                _choice("argue", "Belemész a vitába", "💢", chance=0.58, reward_success=1.20, reward_fail=0.42, score_success=2, score_fail=-18),
            ),
        ),
        DecisionScenario(
            "drunk_passenger",
            "Problémás utas",
            "Az utas egyre hangosabb és zavarja a vezetést.",
            (
                _choice("stop", "Biztonságosan félreállsz", "🛑", chance=1.0, reward_success=0.88, score_success=9, default=True),
                _choice("calm", "Megpróbálod lenyugtatni", "🗣️", chance=0.80, reward_success=1.08, reward_fail=0.68, score_success=7, score_fail=-9),
                _choice("ignore", "Ignorálod és befejezed a fuvart", "😐", chance=0.60, reward_success=1.16, reward_fail=0.50, score_success=2, score_fail=-15),
            ),
        ),
    ),
}

BORSOD_PATROL = DecisionScenario(
    "patrol",
    "Járőr a közelben",
    "Felvillan a kék fény. Döntened kell, mielőtt tovább kutatsz.",
    (
        _choice("calm", "Nyugodtan maradsz / igazoltatás", "🪪", chance=0.82, reward_success=0.90, reward_fail=0.62, score_success=5, score_fail=-12, continue_fail=False, default=True),
        _choice("drop", "Otthagysz egy zsákot és lelépsz", "🎒", chance=1.0, reward_success=0.78, score_success=0, continue_success=False),
        _choice("run", "Futásnak eredsz", "🏃", chance=0.48, reward_success=1.00, reward_fail=0.35, score_success=9, score_fail=-23, continue_fail=False),
        _choice("drive", "Elhajtasz", "💨", chance=0.42, reward_success=1.05, reward_fail=0.28, score_success=10, score_fail=-25, continue_fail=False),
    ),
)


class JobsService:
    def __init__(self, db, economy, statistics) -> None:
        self.db = db
        self.economy = economy
        self.stats = statistics
        self.settings = ServerSettingsService(db)
        self.gameplay = GameplaySettingsService(db)

    async def recover_after_restart(self) -> int:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE job_sessions SET status='cancelled', finished_at=?, updated_at=? WHERE status='active'",
                (_now(), _now()),
            )
            await conn.commit()
            return max(0, int(cur.rowcount or 0))

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.JOBS_ENABLED_KEY, True)

    async def job_enabled(self, guild_id: int, job: str) -> bool:
        if job not in cfg.JOB_BY_KEY:
            return False
        return await self.settings.get_bool(guild_id, f"{cfg.JOB_ENABLED_PREFIX}{job}", True)

    async def reward_multiplier(self, guild_id: int) -> float:
        bp = await self.settings.get_int(guild_id, cfg.JOB_REWARD_MULTIPLIER_KEY)
        bp = cfg.DEFAULT_REWARD_MULTIPLIER_BP if bp is None else max(5000, min(20000, int(bp)))
        return bp / 10_000.0

    @staticmethod
    def _remaining_from_iso(timestamp: str | None, cooldown_seconds: float) -> float:
        if not timestamp:
            return 0.0
        try:
            finished = datetime.fromisoformat(str(timestamp))
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
        except ValueError:
            return 0.0
        return max(0.0, float(cooldown_seconds) - (_utcnow() - finished).total_seconds())

    async def cooldown_state(self, guild_id: int, user_id: int) -> dict[str, float | str | bool]:
        """Return the single shared Jobs cooldown, including anti-reroll abandonment lock."""
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT created_at FROM job_history WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                (guild_id, user_id),
            )
            completed = await cur.fetchone()
            cur = await conn.execute(
                "SELECT finished_at FROM job_sessions WHERE guild_id=? AND user_id=? AND status='abandoned' ORDER BY finished_at DESC LIMIT 1",
                (guild_id, user_id),
            )
            abandoned = await cur.fetchone()
        runtime = await self.gameplay.jobs(guild_id)
        completed_remaining = self._remaining_from_iso(completed[0] if completed else None, runtime.cooldown_seconds)
        abandon_remaining = self._remaining_from_iso(abandoned[0] if abandoned else None, runtime.abandon_cooldown_seconds)
        if abandon_remaining > completed_remaining:
            return {"remaining": abandon_remaining, "reason": "abandoned", "abandoned": True}
        if completed_remaining > 0:
            return {"remaining": completed_remaining, "reason": "completed", "abandoned": False}
        return {"remaining": 0.0, "reason": "ready", "abandoned": False}

    async def cooldown_remaining(self, guild_id: int, user_id: int, job: str | None = None) -> float:
        # job is retained for backwards compatibility; cooldown is shared across every Job.
        state = await self.cooldown_state(guild_id, user_id)
        return float(state["remaining"])

    async def cooldown_summary(self, guild_id: int, user_id: int) -> dict[str, float]:
        remaining = await self.cooldown_remaining(guild_id, user_id)
        return {job.key: remaining for job in cfg.JOBS}

    async def _require_ready(self, guild_id: int, user_id: int, job: str) -> None:
        state = await self.cooldown_state(guild_id, user_id)
        remaining = float(state["remaining"])
        if remaining > 0:
            raise JobCooldownError(job, remaining, abandoned=bool(state["abandoned"]))

    async def get_mastery(self, guild_id: int, user_id: int, job: str) -> dict:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM job_mastery WHERE guild_id=? AND user_id=? AND job=?",
                (guild_id, user_id, job),
            )
            row = await cur.fetchone()
        if row is None:
            return {"guild_id": guild_id, "user_id": user_id, "job": job, "xp": 0, "level": 1, "shifts": 0, "best_rating": "D", "total_earned": 0}
        return dict(row)

    async def mastery_summary(self, guild_id: int, user_id: int) -> list[dict]:
        return [await self.get_mastery(guild_id, user_id, job.key) for job in cfg.JOBS]

    async def active_session(self, guild_id: int, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM job_sessions WHERE guild_id=? AND user_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        data = dict(row)
        data["data"] = json.loads(data.pop("data_json") or "{}")
        return data

    async def _insert_session(self, guild_id: int, user_id: int, job: str, data: dict) -> dict:
        if not await self.is_enabled(guild_id):
            raise ValueError("Az Interactive Jobs rendszer ezen a szerveren ki van kapcsolva.")
        if not await self.job_enabled(guild_id, job):
            raise ValueError("Ez a munka jelenleg ki van kapcsolva ezen a szerveren.")
        await self._require_ready(guild_id, user_id, job)
        sid = uuid.uuid4().hex[:20]
        now = _now()
        try:
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute(
                    "INSERT INTO job_sessions(session_id,guild_id,user_id,job,status,stage,score,reward,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, guild_id, user_id, job, "active", 1, 50, 0, json.dumps(data, ensure_ascii=False), now, now),
                )
                await conn.commit()
        except sqlite3.IntegrityError as exc:
            raise JobBusyError("Már fut egy Interactive Job műszakod ezen a szerveren.") from exc
        return await self.get_session(sid)

    async def get_session(self, session_id: str) -> dict:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM job_sessions WHERE session_id=?", (session_id,))
            row = await cur.fetchone()
        if row is None:
            raise ValueError("A műszak már nem létezik.")
        data = dict(row)
        data["data"] = json.loads(data.pop("data_json") or "{}")
        return data

    async def _update(self, session_id: str, *, stage: int | None = None, score: int | None = None, reward: int | None = None, data: dict | None = None) -> dict:
        row = await self.get_session(session_id)
        if row["status"] != "active":
            raise ValueError("Ez a műszak már lezárult.")
        values = {
            "stage": row["stage"] if stage is None else int(stage),
            "score": row["score"] if score is None else clamp_score(score),
            "reward": row["reward"] if reward is None else max(0, int(reward)),
            "data": row["data"] if data is None else data,
        }
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "UPDATE job_sessions SET stage=?,score=?,reward=?,data_json=?,updated_at=? WHERE session_id=? AND status='active'",
                (values["stage"], values["score"], values["reward"], json.dumps(values["data"], ensure_ascii=False), _now(), session_id),
            )
            await conn.commit()
        return await self.get_session(session_id)

    async def cancel(self, session_id: str) -> bool:
        """Neutral cancellation used for restarts/internal cleanup; does not start a cooldown."""
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE job_sessions SET status='cancelled',finished_at=?,updated_at=? WHERE session_id=? AND status='active'",
                (_now(), _now(), session_id),
            )
            await conn.commit()
            return int(cur.rowcount or 0) > 0

    async def abandon(self, session_id: str) -> bool:
        """Player inactivity/abandonment. Starts the short shared anti-reroll cooldown."""
        now = _now()
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE job_sessions SET status='abandoned',finished_at=?,updated_at=? WHERE session_id=? AND status='active'",
                (now, now, session_id),
            )
            await conn.commit()
            return int(cur.rowcount or 0) > 0

    @staticmethod
    def _warehouse_round(rng: random.Random) -> tuple[list[str], list[list[str]], int]:
        game_round = SequenceGame.build_round(WAREHOUSE_TOKENS, length=4, candidate_count=4, rng=rng)
        return list(game_round.sequence), [list(item) for item in game_round.candidates], game_round.answer_index

    async def _timing_snapshot(self, guild_id: int) -> dict:
        runtime = await self.gameplay.jobs(guild_id)
        return {
            "session_timeout_seconds": runtime.session_timeout_seconds,
            "warehouse_memorize_seconds": runtime.warehouse_memorize_seconds,
            "warehouse_decision_timeout_seconds": runtime.warehouse_decision_timeout_seconds,
            "scenario_decision_timeout_seconds": runtime.scenario_decision_timeout_seconds,
        }

    async def start_warehouse(self, guild_id: int, user_id: int) -> dict:
        rng = random.SystemRandom()
        seq, candidates, answer = self._warehouse_round(rng)
        return await self._insert_session(guild_id, user_id, "warehouse", {
            "round": 1,
            "correct": 0,
            "combo": 0,
            "best_combo": 0,
            "sequence": seq,
            "candidates": candidates,
            "answer": answer,
            "timing": await self._timing_snapshot(guild_id),
        })

    async def warehouse_answer(self, session_id: str, choice: int) -> tuple[dict, bool, bool]:
        row = await self.get_session(session_id)
        data = dict(row["data"])
        if row["job"] != "warehouse":
            raise ValueError("Hibás műszak típus.")
        correct = int(choice) == int(data["answer"])
        data["correct"] = int(data["correct"]) + (1 if correct else 0)
        data["combo"] = int(data["combo"]) + 1 if correct else 0
        data["best_combo"] = max(int(data["best_combo"]), int(data["combo"]))
        score = clamp_score(int(row["score"]) + (10 if correct else -13))
        done = int(data["round"]) >= 5
        if done:
            updated = await self._update(session_id, score=score, data=data)
            return updated, correct, True
        data["round"] = int(data["round"]) + 1
        seq, candidates, answer = self._warehouse_round(random.SystemRandom())
        data.update(sequence=seq, candidates=candidates, answer=answer)
        updated = await self._update(session_id, stage=int(data["round"]), score=score, data=data)
        return updated, correct, False

    @staticmethod
    def _make_borsod_cells() -> list[dict]:
        population: list[tuple[str, int]] = []
        for emoji, value, weight in BORSOD_LOOT:
            population.extend([(emoji, value)] * weight)
        rng = random.SystemRandom()
        cells: list[dict] = []
        for _ in range(25):
            emoji, value = rng.choice(population)
            cells.append({"emoji": emoji, "value": value, "hazard": False})
        for idx in rng.sample(range(25), 3):
            cells[idx] = {"emoji": "🚓", "value": 0, "hazard": True}
        return cells

    async def start_borsod(self, guild_id: int, user_id: int) -> dict:
        return await self._insert_session(guild_id, user_id, "borsod", {
            "attempts_left": 7,
            "revealed": [],
            "cells": self._make_borsod_cells(),
            "event": "Keress lootot",
            "pending_scenario": None,
            "scenario_count": 0,
            "timing": await self._timing_snapshot(guild_id),
        })

    @staticmethod
    def _scenario_payload(scenario: DecisionScenario) -> dict:
        return {
            "key": scenario.key,
            "title": scenario.title,
            "prompt": scenario.prompt,
            "choices": [
                {
                    "key": c.key,
                    "label": c.label,
                    "emoji": c.emoji,
                    "description": c.description,
                    "default": c.default,
                }
                for c in scenario.choices
            ],
        }

    async def borsod_pick(self, session_id: str, index: int) -> tuple[dict, dict, bool]:
        row = await self.get_session(session_id)
        data = dict(row["data"])
        if row["job"] != "borsod":
            raise ValueError("Hibás műszak típus.")
        if data.get("pending_scenario"):
            raise ValueError("Előbb dönts a jelenlegi helyzetben.")
        idx = GridGame.validate_pick(index, cell_count=25, revealed=data["revealed"])
        cell = dict(data["cells"][idx])
        data["revealed"].append(idx)
        data["attempts_left"] = max(0, int(data["attempts_left"]) - 1)
        reward = int(row["reward"])
        score = int(row["score"])
        done = False
        if cell["hazard"]:
            data["pending_scenario"] = {"kind": "borsod", "key": BORSOD_PATROL.key}
            data["scenario_count"] = int(data.get("scenario_count", 0)) + 1
            data["event"] = BORSOD_PATROL.title
            score = clamp_score(score - 3)
            cell["scenario"] = self._scenario_payload(BORSOD_PATROL)
        else:
            reward += int(cell["value"])
            score = min(100, score + 4)
            data["event"] = f"Találtál: {cell['emoji']}"
            done = int(data["attempts_left"]) <= 0
        updated = await self._update(session_id, score=score, reward=reward, data=data)
        return updated, cell, done

    async def resolve_borsod_scenario(self, session_id: str, choice_key: str | None = None, *, timeout: bool = False) -> tuple[dict, dict, bool]:
        row = await self.get_session(session_id)
        data = dict(row["data"])
        if row["job"] != "borsod":
            raise ValueError("Hibás műszak típus.")
        pending = data.get("pending_scenario") or {}
        if pending.get("key") != BORSOD_PATROL.key:
            raise ValueError("Nincs aktív Borsod scenario.")
        choice = BORSOD_PATROL.default_choice() if timeout or choice_key is None else BORSOD_PATROL.choice(choice_key)
        rng = random.SystemRandom()
        success = rng.random() < choice.normalized_chance()
        old_reward = max(0, int(row["reward"]))
        multiplier = choice.reward_success if success else choice.reward_fail
        reward = RiskCashout(at_risk=old_reward).fail(keep_fraction=max(0.0, min(1.0, multiplier))).banked
        # Small >1.0 success multipliers are implemented as a situational bonus rather than RiskCashout keep_fraction.
        if success and multiplier > 1.0:
            reward = round(old_reward * multiplier)
        score = clamp_score(int(row["score"]) + (choice.score_success if success else choice.score_fail))
        continue_run = choice.continue_on_success if success else choice.continue_on_fail
        if timeout:
            prefix = "Idő lejárt — Yoru a biztonságos döntést választotta. "
        else:
            prefix = ""
        outcome_text = (
            f"{prefix}{choice.label}: sikerült, mehetsz tovább." if success and continue_run else
            f"{prefix}{choice.label}: sikerült, de itt kiszállsz." if success else
            f"{prefix}{choice.label}: rosszul sült el."
        )
        data["pending_scenario"] = None
        data["event"] = outcome_text
        done = (not continue_run) or int(data["attempts_left"]) <= 0
        updated = await self._update(session_id, score=score, reward=reward, data=data)
        return updated, {
            "scenario": BORSOD_PATROL.title,
            "choice": choice.label,
            "success": success,
            "event": outcome_text,
            "reward": reward,
            "reward_delta": reward - old_reward,
            "timeout": timeout,
        }, done

    async def start_transport(self, guild_id: int, user_id: int, job: str) -> dict:
        if job not in {"courier", "taxi"}:
            raise ValueError("Ismeretlen transport munka.")
        pool = COURIER_ASSIGNMENTS if job == "courier" else TAXI_PASSENGERS
        return await self._insert_session(guild_id, user_id, job, {
            "total": 4,
            "current": random.SystemRandom().choice(pool),
            "events": [],
            "tips": 0,
            "pending_scenario": None,
            "timing": await self._timing_snapshot(guild_id),
        })

    async def prepare_transport_scenario(self, session_id: str, route: str) -> tuple[dict, dict]:
        row = await self.get_session(session_id)
        data = dict(row["data"])
        job = str(row["job"])
        if job not in {"courier", "taxi"}:
            raise ValueError("Hibás műszak típus.")
        if route not in ROUTES:
            raise ValueError("Ismeretlen útvonal.")
        if data.get("pending_scenario"):
            raise ValueError("Előbb dönts a jelenlegi helyzetben.")
        route_cfg = ROUTES[route]
        rng = random.SystemRandom()
        base = rng.randint(*route_cfg["base"])
        route_score = rng.randint(*route_cfg["score"])
        scenario = rng.choice(TRANSPORT_SCENARIOS[job])
        data["pending_scenario"] = {
            "kind": "transport",
            "key": scenario.key,
            "route": route,
            "base": base,
            "route_score": route_score,
        }
        data["event"] = scenario.title
        updated = await self._update(session_id, data=data)
        payload = self._scenario_payload(scenario)
        payload["route"] = route
        payload["route_label"] = route_cfg["label"]
        payload["base"] = base
        return updated, payload

    async def resolve_transport_scenario(self, session_id: str, choice_key: str | None = None, *, timeout: bool = False) -> tuple[dict, dict, bool]:
        row = await self.get_session(session_id)
        data = dict(row["data"])
        job = str(row["job"])
        if job not in {"courier", "taxi"}:
            raise ValueError("Hibás műszak típus.")
        pending = data.get("pending_scenario") or {}
        scenario_key = str(pending.get("key", ""))
        scenario = next((s for s in TRANSPORT_SCENARIOS[job] if s.key == scenario_key), None)
        if scenario is None:
            raise ValueError("Nincs aktív transport scenario.")
        choice = scenario.default_choice() if timeout or choice_key is None else scenario.choice(choice_key)
        route = str(pending["route"])
        route_cfg = ROUTES[route]
        chance = choice.normalized_chance()
        if 0.0 < chance < 1.0:
            chance = max(0.08, chance - float(route_cfg.get("risk_penalty", 0.0)))
        rng = random.SystemRandom()
        success = rng.random() < chance
        base = max(0, int(pending["base"]))
        multiplier = choice.reward_success if success else choice.reward_fail
        earned = max(0, round(base * max(0.0, multiplier)))
        tip = 0
        if success and rng.random() < (0.48 if job == "taxi" else 0.38):
            tip = rng.randint(6_000, 28_000)
            earned += tip
        score_delta = int(pending.get("route_score", 0)) + (choice.score_success if success else choice.score_fail)
        reward = int(row["reward"]) + earned
        score = clamp_score(int(row["score"]) + score_delta)
        continue_shift = choice.continue_on_success if success else choice.continue_on_fail
        if timeout:
            prefix = "Idő lejárt — Yoru a biztonságos döntést választotta. "
        else:
            prefix = ""
        event = (
            f"{prefix}{scenario.title}: {choice.label} — rendben megoldottad." if success else
            f"{prefix}{scenario.title}: {choice.label} — rosszul sült el."
        )
        data["tips"] = int(data.get("tips", 0)) + tip
        data["events"].append({
            "route": route,
            "scenario": scenario.key,
            "choice": choice.key,
            "success": success,
            "reward": earned,
            "tip": tip,
            "timeout": timeout,
        })
        data["pending_scenario"] = None
        data["event"] = event
        done = int(row["stage"]) >= int(data["total"]) or not continue_shift
        next_stage = int(row["stage"])
        if not done:
            next_stage += 1
            pool = COURIER_ASSIGNMENTS if job == "courier" else TAXI_PASSENGERS
            data["current"] = rng.choice(pool)
        updated = await self._update(session_id, stage=next_stage, score=score, reward=reward, data=data)
        return updated, {
            "scenario": scenario.title,
            "choice": choice.label,
            "success": success,
            "event": event,
            "reward": earned,
            "tip": tip,
            "route": route,
            "timeout": timeout,
            "continue": continue_shift,
        }, done

    async def transport_choose(self, session_id: str, route: str) -> tuple[dict, dict, bool]:
        """Compatibility helper for non-UI callers/tests.

        v3.22.1 UI uses prepare_transport_scenario -> player choice -> resolve_transport_scenario.
        Legacy/internal callers still get a complete leg using the scenario's default safe choice.
        """
        prepared, scenario = await self.prepare_transport_scenario(session_id, route)
        default = next((c for c in scenario["choices"] if c.get("default")), scenario["choices"][0])
        session, outcome, done = await self.resolve_transport_scenario(session_id, str(default["key"]))
        return session, outcome, done

    async def finish(self, session_id: str) -> JobResult:
        row = await self.get_session(session_id)
        if row["status"] != "active":
            raise ValueError("Ez a műszak már lezárult.")
        if row["data"].get("pending_scenario"):
            raise ValueError("A műszakban még van lezáratlan döntési helyzet.")
        mastery = await self.get_mastery(int(row["guild_id"]), int(row["user_id"]), str(row["job"]))
        level = int(mastery["level"])
        base = max(0, int(row["reward"]))
        if row["job"] == "warehouse":
            data = row["data"]
            base = 145_000 + int(data.get("correct", 0)) * 42_000 + int(data.get("best_combo", 0)) * 8_000
        multiplier = await self.reward_multiplier(int(row["guild_id"]))
        mastery_mult = 1.0 + cfg.mastery_bonus(level)
        pre_bonus = max(0, round(base * multiplier * mastery_mult))
        reward = await self.economy.apply_prestige_bonus(int(row["guild_id"]), int(row["user_id"]), pre_bonus, f"job:{row['job']}")
        score = clamp_score(int(row["score"]))
        rating = PerformanceRating.from_score(score).grade
        mastery_xp = cfg.JOB_BY_KEY[str(row["job"])].base_mastery_xp + score // 6
        now = _now()
        starting_balance = await self.db.get_starting_balance(int(row["guild_id"]))
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT status FROM job_sessions WHERE session_id=?", (session_id,))
            live = await cur.fetchone()
            if not live or str(live[0]) != "active":
                await conn.rollback()
                raise ValueError("Ez a műszak már lezárult.")
            await conn.execute(
                "INSERT OR IGNORE INTO users(guild_id,user_id,wallet,bank,created_at,last_daily,last_work) VALUES(?,?,?,?,?,?,?)",
                (row["guild_id"], row["user_id"], starting_balance, 0, now, None, None),
            )
            await conn.execute(
                "UPDATE users SET wallet=wallet+?, money_earned=money_earned+? WHERE guild_id=? AND user_id=?",
                (reward, reward, row["guild_id"], row["user_id"]),
            )
            await conn.execute(
                "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
                (row["guild_id"], row["user_id"], reward, f"job:{row['job']}", now),
            )
            cur = await conn.execute(
                "SELECT xp,shifts,best_rating,total_earned FROM job_mastery WHERE guild_id=? AND user_id=? AND job=?",
                (row["guild_id"], row["user_id"], row["job"]),
            )
            old = await cur.fetchone()
            old_xp = int(old[0]) if old else 0
            shifts = int(old[1]) if old else 0
            old_rating = str(old[2]) if old else "D"
            earned = int(old[3]) if old else 0
            new_xp = old_xp + mastery_xp
            new_level = cfg.mastery_level_for_xp(new_xp)
            best = rating if cfg.RATING_ORDER.index(rating) > cfg.RATING_ORDER.index(old_rating) else old_rating
            await conn.execute(
                "INSERT INTO job_mastery(guild_id,user_id,job,xp,level,shifts,best_rating,total_earned,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(guild_id,user_id,job) DO UPDATE SET xp=excluded.xp,level=excluded.level,shifts=excluded.shifts,best_rating=excluded.best_rating,total_earned=excluded.total_earned,updated_at=excluded.updated_at",
                (row["guild_id"], row["user_id"], row["job"], new_xp, new_level, shifts + 1, best, earned + reward, now),
            )
            await conn.execute(
                "UPDATE job_sessions SET status='finished',reward=?,finished_at=?,updated_at=? WHERE session_id=?",
                (reward, now, now, session_id),
            )
            # job_history.created_at is the authoritative per-job cooldown start.
            await conn.execute(
                "INSERT INTO job_history(guild_id,user_id,job,score,rating,reward,mastery_xp,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (row["guild_id"], row["user_id"], row["job"], score, rating, reward, mastery_xp, now),
            )
            cur = await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?", (row["guild_id"], row["user_id"]))
            wallet = int((await cur.fetchone())[0])
            await conn.commit()
        # Best-effort integrations after the atomic payout.
        await self.stats.increment(int(row["guild_id"]), int(row["user_id"]), "jobs.shifts")
        await self.stats.increment(int(row["guild_id"]), int(row["user_id"]), f"jobs.{row['job']}.shifts")
        await self.stats.add(int(row["guild_id"]), int(row["user_id"]), "jobs.earned", reward)
        await self.stats.add(int(row["guild_id"]), int(row["user_id"]), f"jobs.{row['job']}.earned", reward)
        await self.stats.set_max(int(row["guild_id"]), int(row["user_id"]), f"jobs.{row['job']}.best_score", score)
        await self.db.add_progression_xp(int(row["guild_id"]), int(row["user_id"]), 20 + score // 4, f"job:{row['job']}")
        return JobResult(session_id, str(row["job"]), base, reward, score, rating, mastery_xp, new_level, wallet)

    async def history(self, guild_id: int, user_id: int, limit: int = 10) -> list[dict]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM job_history WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, max(1, min(25, int(limit)))),
            )
            return [dict(r) for r in await cur.fetchall()]
