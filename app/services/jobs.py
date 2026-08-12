from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

from app import jobs_config as cfg
from app.services.server_settings import ServerSettingsService
from app.job_framework import GridGame, PerformanceRating, RiskCashout, SequenceGame, clamp_score


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobBusyError(ValueError):
    pass


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
    # Calibrated so a random 7-pick run averages ~250k before mastery/prestige.
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
    "safe": {"label": "Rövid / biztos", "base": (52_000, 72_000), "score": (5, 11), "risk": 0.08},
    "long": {"label": "Hosszabb / jobb fizu", "base": (72_000, 105_000), "score": (1, 9), "risk": 0.18},
    "risky": {"label": "Problémás / magas reward", "base": (92_000, 138_000), "score": (-7, 10), "risk": 0.33},
}

GOOD_EVENTS = (
    "Borravalót kaptál", "Zöld hullám", "Extra fuvar beesett", "A címzett már várt", "Rövidebb út nyílt",
)
BAD_EVENTS = (
    "Dugó", "Útlezárás", "Rossz cím", "Problémás utas", "Késés", "Sérült csomag gyanú",
)


class JobsService:
    def __init__(self, db, economy, statistics) -> None:
        self.db = db
        self.economy = economy
        self.stats = statistics
        self.settings = ServerSettingsService(db)

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
        data = dict(row); data["data"] = json.loads(data.pop("data_json") or "{}")
        return data

    async def _insert_session(self, guild_id: int, user_id: int, job: str, data: dict) -> dict:
        if not await self.is_enabled(guild_id):
            raise ValueError("Az Interactive Jobs rendszer ezen a szerveren ki van kapcsolva.")
        if not await self.job_enabled(guild_id, job):
            raise ValueError("Ez a munka jelenleg ki van kapcsolva ezen a szerveren.")
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
        data = dict(row); data["data"] = json.loads(data.pop("data_json") or "{}")
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
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE job_sessions SET status='cancelled',finished_at=?,updated_at=? WHERE session_id=? AND status='active'",
                (_now(), _now(), session_id),
            )
            await conn.commit()
            return int(cur.rowcount or 0) > 0

    @staticmethod
    def _warehouse_round(rng: random.Random) -> tuple[list[str], list[list[str]], int]:
        game_round = SequenceGame.build_round(WAREHOUSE_TOKENS, length=4, candidate_count=4, rng=rng)
        return list(game_round.sequence), [list(item) for item in game_round.candidates], game_round.answer_index

    async def start_warehouse(self, guild_id: int, user_id: int) -> dict:
        rng = random.SystemRandom(); seq, candidates, answer = self._warehouse_round(rng)
        return await self._insert_session(guild_id, user_id, "warehouse", {
            "round": 1, "correct": 0, "combo": 0, "best_combo": 0,
            "sequence": seq, "candidates": candidates, "answer": answer,
        })

    async def warehouse_answer(self, session_id: str, choice: int) -> tuple[dict, bool, bool]:
        row = await self.get_session(session_id); data = dict(row["data"])
        if row["job"] != "warehouse": raise ValueError("Hibás műszak típus.")
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
        population=[]
        for emoji, value, weight in BORSOD_LOOT:
            population.extend([(emoji,value)]*weight)
        rng=random.SystemRandom(); cells=[]
        for _ in range(25):
            emoji,value=rng.choice(population)
            cells.append({"emoji":emoji,"value":value,"hazard":False})
        for idx in rng.sample(range(25), 3):
            cells[idx]={"emoji":"🚓","value":0,"hazard":True}
        return cells

    async def start_borsod(self, guild_id: int, user_id: int) -> dict:
        return await self._insert_session(guild_id,user_id,"borsod",{
            "attempts_left":7,"revealed":[],"cells":self._make_borsod_cells(),"event":"Keress lootot",
        })

    async def borsod_pick(self, session_id: str, index: int) -> tuple[dict, dict, bool]:
        row=await self.get_session(session_id); data=dict(row["data"])
        if row["job"]!="borsod": raise ValueError("Hibás műszak típus.")
        idx = GridGame.validate_pick(index, cell_count=25, revealed=data["revealed"])
        cell=data["cells"][idx]; data["revealed"].append(idx); data["attempts_left"]-=1
        reward=int(row["reward"]); score=int(row["score"])
        done=False
        if cell["hazard"]:
            # Early game safe: keep 70% of the current run, but shift ends.
            reward=RiskCashout(at_risk=reward).fail(keep_fraction=0.70).banked; score=clamp_score(score-18); data["event"]="Járőr! A loot 30%-át hátrahagytad"; done=True
        else:
            reward += int(cell["value"]); score=min(100,score+4); data["event"]=f"Találtál: {cell['emoji']}"
            done=data["attempts_left"]<=0
        updated=await self._update(session_id,score=score,reward=reward,data=data)
        return updated,cell,done

    async def start_transport(self, guild_id: int, user_id: int, job: str) -> dict:
        if job not in {"courier","taxi"}: raise ValueError("Ismeretlen transport munka.")
        pool=COURIER_ASSIGNMENTS if job=="courier" else TAXI_PASSENGERS
        return await self._insert_session(guild_id,user_id,job,{
            "total":4,"current":random.SystemRandom().choice(pool),"events":[],"tips":0,
        })

    async def transport_choose(self, session_id: str, route: str) -> tuple[dict, dict, bool]:
        row=await self.get_session(session_id); data=dict(row["data"])
        if row["job"] not in {"courier","taxi"}: raise ValueError("Hibás műszak típus.")
        if route not in ROUTES: raise ValueError("Ismeretlen útvonal.")
        cfg_route=ROUTES[route]; rng=random.SystemRandom()
        base=rng.randint(*cfg_route["base"]); score_delta=rng.randint(*cfg_route["score"])
        bad=rng.random()<cfg_route["risk"]
        if bad:
            event=rng.choice(BAD_EVENTS); base=int(base*rng.uniform(0.58,0.82)); score_delta-=rng.randint(5,12); tip=0
        else:
            event=rng.choice(GOOD_EVENTS); tip=rng.randint(6_000,28_000) if rng.random()<0.55 else 0; base+=tip; score_delta+=rng.randint(1,5)
        reward=int(row["reward"])+base; score=clamp_score(int(row["score"])+score_delta); data["tips"]+=tip
        data["events"].append({"route":route,"event":event,"reward":base,"bad":bad})
        done=int(row["stage"])>=int(data["total"])
        if not done:
            pool=COURIER_ASSIGNMENTS if row["job"]=="courier" else TAXI_PASSENGERS
            data["current"]=rng.choice(pool)
        updated=await self._update(session_id,stage=int(row["stage"])+(0 if done else 1),score=score,reward=reward,data=data)
        return updated,{"event":event,"reward":base,"bad":bad,"tip":tip,"route":route},done

    async def finish(self, session_id: str) -> JobResult:
        row=await self.get_session(session_id)
        if row["status"] != "active":
            raise ValueError("Ez a műszak már lezárult.")
        mastery=await self.get_mastery(int(row["guild_id"]),int(row["user_id"]),str(row["job"]))
        level=int(mastery["level"]); base=max(0,int(row["reward"]))
        if row["job"]=="warehouse":
            data=row["data"]; base=145_000 + int(data.get("correct",0))*42_000 + int(data.get("best_combo",0))*8_000
        multiplier=await self.reward_multiplier(int(row["guild_id"]))
        mastery_mult=1.0+cfg.mastery_bonus(level)
        pre_bonus=max(0,round(base*multiplier*mastery_mult))
        reward=await self.economy.apply_prestige_bonus(int(row["guild_id"]),int(row["user_id"]),pre_bonus,f"job:{row['job']}")
        score=clamp_score(int(row["score"])); rating=PerformanceRating.from_score(score).grade
        mastery_xp=cfg.JOB_BY_KEY[str(row["job"])].base_mastery_xp + score//6
        now=_now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT status FROM job_sessions WHERE session_id=?",(session_id,)); live=await cur.fetchone()
            if not live or str(live[0])!="active":
                await conn.rollback(); raise ValueError("Ez a műszak már lezárult.")
            await conn.execute(
                "INSERT OR IGNORE INTO users(guild_id,user_id,wallet,bank,created_at,last_daily,last_work) VALUES(?,?,?,?,?,?,?)",
                (row["guild_id"],row["user_id"],self.db.starting_balance,0,now,None,None),
            )
            await conn.execute("UPDATE users SET wallet=wallet+?, money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(reward,reward,row["guild_id"],row["user_id"]))
            await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(row["guild_id"],row["user_id"],reward,f"job:{row['job']}",now))
            cur=await conn.execute("SELECT xp,shifts,best_rating,total_earned FROM job_mastery WHERE guild_id=? AND user_id=? AND job=?",(row["guild_id"],row["user_id"],row["job"])); old=await cur.fetchone()
            old_xp=int(old[0]) if old else 0; shifts=int(old[1]) if old else 0; old_rating=str(old[2]) if old else "D"; earned=int(old[3]) if old else 0
            new_xp=old_xp+mastery_xp; new_level=cfg.mastery_level_for_xp(new_xp)
            best=rating if cfg.RATING_ORDER.index(rating)>cfg.RATING_ORDER.index(old_rating) else old_rating
            await conn.execute(
                "INSERT INTO job_mastery(guild_id,user_id,job,xp,level,shifts,best_rating,total_earned,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(guild_id,user_id,job) DO UPDATE SET xp=excluded.xp,level=excluded.level,shifts=excluded.shifts,best_rating=excluded.best_rating,total_earned=excluded.total_earned,updated_at=excluded.updated_at",
                (row["guild_id"],row["user_id"],row["job"],new_xp,new_level,shifts+1,best,earned+reward,now),
            )
            await conn.execute("UPDATE job_sessions SET status='finished',reward=?,finished_at=?,updated_at=? WHERE session_id=?",(reward,now,now,session_id))
            await conn.execute("INSERT INTO job_history(guild_id,user_id,job,score,rating,reward,mastery_xp,created_at) VALUES(?,?,?,?,?,?,?,?)",(row["guild_id"],row["user_id"],row["job"],score,rating,reward,mastery_xp,now))
            cur=await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",(row["guild_id"],row["user_id"])); wallet=int((await cur.fetchone())[0])
            await conn.commit()
        # Best-effort integrations after the atomic payout.
        await self.stats.increment(int(row["guild_id"]),int(row["user_id"]),"jobs.shifts")
        await self.stats.increment(int(row["guild_id"]),int(row["user_id"]),f"jobs.{row['job']}.shifts")
        await self.stats.add(int(row["guild_id"]),int(row["user_id"]),"jobs.earned",reward)
        await self.stats.add(int(row["guild_id"]),int(row["user_id"]),f"jobs.{row['job']}.earned",reward)
        await self.stats.set_max(int(row["guild_id"]),int(row["user_id"]),f"jobs.{row['job']}.best_score",score)
        await self.db.add_progression_xp(int(row["guild_id"]),int(row["user_id"]),20+score//4,f"job:{row['job']}")
        return JobResult(session_id,str(row["job"]),base,reward,score,rating,mastery_xp,new_level,wallet)

    async def history(self, guild_id: int, user_id: int, limit: int=10) -> list[dict]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            cur=await conn.execute("SELECT * FROM job_history WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",(guild_id,user_id,max(1,min(25,int(limit)))))
            return [dict(r) for r in await cur.fetchall()]
