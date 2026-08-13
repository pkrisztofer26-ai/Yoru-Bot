from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app import live_world_config as cfg
from app.database import Database
from app.services.server_settings import ServerSettingsService


def now_utc()->datetime:return datetime.now(timezone.utc)
def iso(dt:datetime)->str:return dt.astimezone(timezone.utc).isoformat()
def parse_dt(value:str)->datetime:return datetime.fromisoformat(value).astimezone(timezone.utc)


MAV_TICK_SECONDS = 0.62
MAV_UI_REFRESH_SECONDS = 1.0


def mav_multiplier_for_elapsed(elapsed_seconds: float) -> float:
    """Deterministic MÁV multiplier derived from elapsed time.

    The game clock must never depend on Discord message edits or rate limits.
    This preserves the v3.24.0 step curve while making settlement independent
    from UI/network timing.
    """
    ticks=max(0,int(float(elapsed_seconds)//MAV_TICK_SECONDS))
    mult=1.0
    for _ in range(min(ticks,1000)):
        mult=round(mult+(0.03 if mult<1.5 else 0.05 if mult<3 else 0.10 if mult<10 else 0.25),2)
        if mult>=100.0:return 100.0
    return mult


def mav_seconds_to_multiplier(target: float) -> float:
    """Return the first tick time where the multiplier reaches target."""
    target=max(1.0,float(target)); mult=1.0; ticks=0
    while mult<target and ticks<10000:
        mult=round(mult+(0.03 if mult<1.5 else 0.05 if mult<3 else 0.10 if mult<10 else 0.25),2)
        ticks+=1
    return ticks*MAV_TICK_SECONDS


def mav_crash_deadline(data: dict[str, Any]) -> datetime:
    """Exact backend deadline when the stored crash multiplier is reached."""
    started=parse_dt(str(data["started_at"]))
    crash_at=float(data.get("crash_at",1.0))
    return started+timedelta(seconds=mav_seconds_to_multiplier(crash_at))


@dataclass(frozen=True,slots=True)
class LiveResult:
    session_id:str
    game:str
    reward:int
    wallet:int
    outcome:str


class LiveWorldService:
    def __init__(self,db:Database,economy=None,statistics=None)->None:
        self.db=db; self.economy=economy; self.statistics=statistics; self.settings=ServerSettingsService(db)

    async def enabled(self,guild_id:int)->bool:return await self.settings.get_bool(guild_id,cfg.LIVE_ENABLED_KEY,True)
    async def game_enabled(self,guild_id:int,game:str)->bool:
        key={"shoprob":cfg.SHOPROB_ENABLED_KEY,"bankrob":cfg.BANKROB_ENABLED_KEY,"mav":cfg.MAV_ENABLED_KEY,"poker":cfg.POKER_ENABLED_KEY}[game]
        return await self.settings.get_bool(guild_id,key,True)
    async def max_payout(self,guild_id:int)->int:
        v=await self.settings.get_int(guild_id,cfg.LIVE_MAX_PAYOUT_KEY); return max(1_000_000,int(v if v is not None else cfg.DEFAULT_MAX_PAYOUT))
    async def mav_min_bet(self,guild_id:int)->int:
        v=await self.settings.get_int(guild_id,cfg.MAV_MIN_BET_KEY); return max(1_000,int(v if v is not None else cfg.DEFAULT_MAV_MIN_BET))
    async def poker_min_buyin(self,guild_id:int)->int:
        v=await self.settings.get_int(guild_id,cfg.POKER_MIN_BUYIN_KEY); return max(10_000,int(v if v is not None else cfg.DEFAULT_POKER_MIN_BUYIN))
    async def robbery_cooldown(self,guild_id:int,game:str)->timedelta:
        key=cfg.SHOPROB_COOLDOWN_KEY if game=="shoprob" else cfg.BANKROB_COOLDOWN_KEY
        default=cfg.DEFAULT_SHOPROB_COOLDOWN_MINUTES if game=="shoprob" else cfg.DEFAULT_BANKROB_COOLDOWN_MINUTES
        v=await self.settings.get_int(guild_id,key); return timedelta(minutes=max(1,min(1440,int(v if v is not None else default))))

    async def _reserve_funds(self,conn:aiosqlite.Connection,guild_id:int,user_id:int,amount:int,reason:str)->None:
        """Reserve a player-game stake strictly from wallet. Bank is protected storage."""
        starting=await self.db.get_starting_balance(guild_id,conn); now=iso(now_utc())
        await conn.execute("INSERT OR IGNORE INTO users(guild_id,user_id,wallet,bank,created_at,last_daily,last_work) VALUES(?,?,?,?,?,?,?)",(guild_id,user_id,starting,0,now,None,None))
        cur=await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",(guild_id,user_id)); row=await cur.fetchone(); wallet=max(0,int(row[0]))
        if wallet<amount:raise ValueError("Nincs elég pénzed a walletedben. A banki pénzt Yoru nem használja játék-tétként.")
        await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?",(amount,amount,guild_id,user_id))
        await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(guild_id,user_id,-amount,reason,now))

    async def _reserve_wallet_funds(self,conn:aiosqlite.Connection,guild_id:int,user_id:int,amount:int,reason:str)->None:
        """Reserve gameplay stake strictly from wallet; bank is never touched."""
        starting=await self.db.get_starting_balance(guild_id,conn); now=iso(now_utc())
        await conn.execute("INSERT OR IGNORE INTO users(guild_id,user_id,wallet,bank,created_at,last_daily,last_work) VALUES(?,?,?,?,?,?,?)",(guild_id,user_id,starting,0,now,None,None))
        cur=await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",(guild_id,user_id)); row=await cur.fetchone(); wallet=max(0,int(row[0]))
        if wallet<amount:raise ValueError("Nincs elég pénzed a walletedben. A MÁV Crash nem használ banki pénzt.")
        await conn.execute("UPDATE users SET wallet=wallet-?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?",(amount,amount,guild_id,user_id))
        await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(guild_id,user_id,-amount,reason,now))

    async def active_session(self,guild_id:int,user_id:int)->dict[str,Any]|None:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; cur=await conn.execute("SELECT * FROM live_game_sessions WHERE guild_id=? AND user_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",(guild_id,user_id)); row=await cur.fetchone()
        if row is None:return None
        data=dict(row); data["data"]=json.loads(data.pop("data_json") or "{}"); return data

    async def _check_robbery_cooldown(self,guild_id:int,user_id:int,game:str)->None:
        async with aiosqlite.connect(self.db.path) as conn:
            cur=await conn.execute("SELECT finished_at FROM live_game_sessions WHERE guild_id=? AND user_id=? AND game=? AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1",(guild_id,user_id,game)); row=await cur.fetchone()
        if row and row[0]:
            ready=parse_dt(str(row[0]))+await self.robbery_cooldown(guild_id,game)
            if now_utc()<ready:raise ValueError(f"Ez a játék még cooldownon van. Újra: <t:{int(ready.timestamp())}:R>.")

    async def start_robbery(self,guild_id:int,user_id:int,game:str)->dict[str,Any]:
        if game not in cfg.ROBBERY_DEFS:raise ValueError("Ismeretlen rablás.")
        if not await self.enabled(guild_id) or not await self.game_enabled(guild_id,game):raise ValueError("Ez a Live World játék ki van kapcsolva.")
        await self._check_robbery_cooldown(guild_id,user_id,game)
        sid=uuid.uuid4().hex[:20]; data={"loot":0,"heat":0,"failed":False,"event":"A terv kész. Válassz tempót.","steps":[]}; now=iso(now_utc())
        try:
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("INSERT INTO live_game_sessions(session_id,guild_id,user_id,game,status,stage,stake,reward,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,guild_id,user_id,game,"active",1,0,0,json.dumps(data,ensure_ascii=False),now,now)); await conn.commit()
        except sqlite3.IntegrityError as exc:raise ValueError("Már fut egy Live World játékod ezen a szerveren.") from exc
        return await self.get_session(sid)

    async def get_session(self,session_id:str)->dict[str,Any]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; cur=await conn.execute("SELECT * FROM live_game_sessions WHERE session_id=?",(session_id,)); row=await cur.fetchone()
        if row is None:raise ValueError("A session már nem létezik.")
        d=dict(row); d["data"]=json.loads(d.pop("data_json") or "{}"); return d

    async def robbery_step(self,session_id:str,choice:str,*,expected_stage:int|None=None)->tuple[dict[str,Any],bool]:
        """Apply exactly one robbery decision atomically.

        ``expected_stage`` makes Discord buttons one-shot per rendered stage:
        double/spam clicks from an old View cannot advance multiple stages.
        """
        rng=random.SystemRandom(); now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT * FROM live_game_sessions WHERE session_id=?",(session_id,))
            row=await cur.fetchone()
            if row is None or str(row["status"])!="active" or str(row["game"]) not in cfg.ROBBERY_DEFS:
                await conn.rollback(); raise ValueError("Ez a rablás már lezárult.")
            stage=int(row["stage"])
            if expected_stage is not None and stage!=int(expected_stage):
                await conn.rollback(); raise ValueError("Ez a döntési gomb már elavult. Használd az aktuális panelt.")
            definition=cfg.ROBBERY_DEFS[str(row["game"])]
            if choice not in definition["choices"]:
                await conn.rollback(); raise ValueError("Ismeretlen döntés.")
            opt=definition["choices"][choice]
            data=json.loads(str(row["data_json"] or "{}")); heat=int(data.get("heat",0))
            risk=min(.82,float(opt["risk"])+heat/450.0); failed=rng.random()<risk
            if failed:
                kept=round(int(data.get("loot",0))*float(definition["fail_keep"])); data["failed"]=True; data["loot"]=kept
                data["event"]=rng.choice(("Megszólalt a riasztó.","Rendőr érkezett a közelbe.","A kamera kiszúrt.","A kijáratnál lebuktál.")); done=True
            else:
                low,high=definition["base_loot"]; gain=round(rng.randint(int(low),int(high))*float(opt["loot"]))
                data["loot"]=int(data.get("loot",0))+gain; data["heat"]=min(100,heat+int(opt["heat"])); data["event"]=rng.choice((f"+{gain:,} loot.","Tiszta szakasz, mehetsz tovább.","Találtál egy extra kasszát.","A terv eddig működik."))
                data.setdefault("steps",[]).append({"choice":choice,"gain":gain,"heat":data["heat"]}); done=stage>=int(definition["stages"])
            new_stage=stage+1
            upd=await conn.execute(
                "UPDATE live_game_sessions SET stage=?,reward=?,data_json=?,updated_at=? WHERE session_id=? AND status='active' AND stage=?",
                (new_stage,int(data["loot"]),json.dumps(data,ensure_ascii=False),now,session_id,stage),
            )
            if int(upd.rowcount or 0)!=1:
                await conn.rollback(); raise ValueError("A rablás állapota közben megváltozott. Próbáld az aktuális panelről.")
            await conn.commit()
        return await self.get_session(session_id),done

    async def cancel_active_robbery(self,session_id:str,reason:str="cancelled")->bool:
        now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            upd=await conn.execute(
                "UPDATE live_game_sessions SET status='cancelled',finished_at=?,updated_at=? WHERE session_id=? AND game IN ('shoprob','bankrob') AND status='active'",
                (now,now,session_id),
            )
            await conn.commit()
            return int(upd.rowcount or 0)==1

    async def robbery_cashout(self,session_id:str)->LiveResult:
        return await self.finish_robbery(session_id,"cashout")

    async def finish_robbery(self,session_id:str,outcome:str="complete")->LiveResult:
        row=await self.get_session(session_id)
        if row["status"]!="active":raise ValueError("Ez a session már lezárult.")
        reward=max(0,int(row["reward"])); guild_id=int(row["guild_id"]); user_id=int(row["user_id"])
        if self.economy and reward:reward=await self.economy.apply_prestige_bonus(guild_id,user_id,reward,f"live:{row['game']}")
        reward=min(await self.max_payout(guild_id),reward); now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            upd=await conn.execute("UPDATE live_game_sessions SET status='finished',reward=?,finished_at=?,updated_at=? WHERE session_id=? AND status='active'",(reward,now,now,session_id))
            if int(upd.rowcount or 0)!=1:await conn.rollback();raise ValueError("Ez a session már lezárult.")
            starting=await self.db.get_starting_balance(guild_id,conn); await conn.execute("INSERT OR IGNORE INTO users(guild_id,user_id,wallet,bank,created_at,last_daily,last_work) VALUES(?,?,?,?,?,?,?)",(guild_id,user_id,starting,0,now,None,None))
            if reward:
                await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(reward,reward,guild_id,user_id)); await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(guild_id,user_id,reward,f"live:{row['game']}:{outcome}",now))
            cur=await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",(guild_id,user_id)); wallet=int((await cur.fetchone())[0]); await conn.commit()
        if self.statistics:
            await self.statistics.increment(guild_id,user_id,f"live.{row['game']}.runs"); await self.statistics.add(guild_id,user_id,f"live.{row['game']}.earned",reward)
        return LiveResult(session_id,str(row["game"]),reward,wallet,outcome)

    async def start_mav(self,guild_id:int,user_id:int,stake:int)->dict[str,Any]:
        if not await self.enabled(guild_id) or not await self.game_enabled(guild_id,"mav"):raise ValueError("A MÁV Crash ki van kapcsolva.")
        stake=int(stake)
        if stake<await self.mav_min_bet(guild_id):raise ValueError(f"A minimum tét {await self.mav_min_bet(guild_id):,}.")
        sid=uuid.uuid4().hex[:20]; rng=random.SystemRandom(); u=rng.random(); crash_at=1.0 if u<0.03 else min(100.0,max(1.01,math_floor_2(0.97/max(0.001,1-u))))
        started=now_utc(); data={"crash_at":crash_at,"current":1.0,"started_at":iso(started)}; now=iso(started)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                # Unique active-user index protects against double sessions.
                await conn.execute("INSERT INTO live_game_sessions(session_id,guild_id,user_id,game,status,stake,reward,stage,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,guild_id,user_id,"mav","active",stake,0,0,json.dumps(data),now,now)); await self._reserve_wallet_funds(conn,guild_id,user_id,stake,f"mav_stake:{sid}"); await conn.commit()
            except sqlite3.IntegrityError as exc:await conn.rollback();raise ValueError("Már fut egy Live World játékod.") from exc
            except Exception:await conn.rollback();raise
        return await self.get_session(sid)

    def mav_current_from_data(self,data:dict[str,Any],*,at:datetime|None=None)->float:
        stored=float(data.get("current",1.0))
        started_raw=data.get("started_at")
        if not started_raw:return stored
        try:started=parse_dt(str(started_raw))
        except (ValueError,TypeError):return stored
        elapsed=max(0.0,((at or now_utc())-started).total_seconds())
        # Once a start timestamp exists, elapsed time is the single source of
        # truth. A stale DB/UI "current" value must never move settlement.
        return min(100.0,max(1.0,mav_multiplier_for_elapsed(elapsed)))

    async def mav_snapshot(self,session_id:str)->dict[str,Any]:
        row=await self.get_session(session_id)
        data=dict(row["data"]); data["current"]=self.mav_current_from_data(data)
        row["data"]=data
        return row

    async def update_mav_current(self,session_id:str,current:float)->dict[str,Any]:
        row=await self.get_session(session_id)
        if row["status"]!="active" or row["game"]!="mav":return row
        data=dict(row["data"]); data["current"]=round(float(current),2)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("UPDATE live_game_sessions SET data_json=?,updated_at=? WHERE session_id=? AND status='active'",(json.dumps(data),iso(now_utc()),session_id)); await conn.commit()
        return await self.get_session(session_id)

    async def settle_mav(
        self,
        session_id:str,
        *,
        cashout_at:datetime|None=None,
        cashout_multiplier:float|None=None,
    )->LiveResult:
        """Atomically settle a MÁV round.

        Backend state is authoritative and commits independently from Discord
        message edits. A cashout is judged by the immutable Discord interaction
        creation timestamp, not by callback/DB latency.

        A crash may be committed before Discord delivers a click callback. If
        that callback carries a trustworthy click timestamp from *before* the
        crash deadline, an already-finished zero-payout crash can be corrected
        exactly once into the valid cashout. This removes the old global grace
        sleep without penalising a player for Discord/event-loop lag.
        """
        now_dt=now_utc(); now=iso(now_dt)
        stats_round=False; stats_payout=0
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row
            await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT * FROM live_game_sessions WHERE session_id=?",(session_id,))
            row=await cur.fetchone()
            if row is None or str(row["game"])!="mav":
                await conn.rollback(); raise ValueError("A MÁV kör nem található.")

            status=str(row["status"]); data=json.loads(str(row["data_json"] or "{}"))
            crash_at=float(data.get("crash_at",1.0)); stake=int(row["stake"]); crash_deadline=mav_crash_deadline(data)

            clicked:datetime|None=None; cashout=1.0; valid_click=False
            if cashout_at is not None:
                clicked=cashout_at if cashout_at.tzinfo is not None else cashout_at.replace(tzinfo=timezone.utc)
                clicked=clicked.astimezone(timezone.utc)
                cashout=self.mav_current_from_data(data,at=clicked)
                valid_click=clicked < crash_deadline and cashout < crash_at
            elif cashout_multiplier is not None:
                current=self.mav_current_from_data(data,at=now_dt)
                cashout=max(1.0,min(float(cashout_multiplier),current))
                valid_click=cashout < crash_at and current < crash_at

            # Normal active-session settlement. Crash settlement happens as soon
            # as the backend deadline is reached; Discord I/O is not involved.
            if status=="active":
                if cashout_at is None and cashout_multiplier is None:
                    reward=0; outcome="crash"; settled_mult=crash_at
                elif valid_click:
                    settled_mult=round(float(cashout),2); reward=round(stake*settled_mult); outcome=f"cashout_{settled_mult:.2f}x"
                else:
                    reward=0; outcome="crash"; settled_mult=crash_at

                data["settled_outcome"]=outcome
                data["settled_multiplier"]=round(float(settled_mult),2)
                data["crash_deadline"]=iso(crash_deadline)
                data["settled_at"]=now
                upd=await conn.execute(
                    "UPDATE live_game_sessions SET status='finished',reward=?,data_json=?,finished_at=?,updated_at=? WHERE session_id=? AND status='active'",
                    (reward,json.dumps(data),now,now,session_id),
                )
                if int(upd.rowcount or 0)!=1:
                    await conn.rollback(); raise ValueError("A MÁV kör állapota közben megváltozott.")
                if reward:
                    await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(reward,reward,int(row["guild_id"]),int(row["user_id"])))
                    await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(int(row["guild_id"]),int(row["user_id"]),reward,f"mav_payout:{session_id}",now))
                stats_round=True; stats_payout=reward

            # Idempotent/late callback handling. A callback delivered after the
            # runner has already committed the crash is still honoured only if
            # its Discord creation timestamp proves the click happened earlier.
            elif status=="finished":
                existing_outcome=str(data.get("settled_outcome") or ("crash" if int(row["reward"] or 0)==0 else "finished"))
                existing_reward=int(row["reward"] or 0)
                if existing_outcome.startswith("cashout_"):
                    reward=existing_reward; outcome=existing_outcome
                elif existing_outcome=="crash" and cashout_at is not None and valid_click and existing_reward==0:
                    settled_mult=round(float(cashout),2); reward=round(stake*settled_mult); outcome=f"cashout_{settled_mult:.2f}x"
                    data["settled_outcome"]=outcome
                    data["settled_multiplier"]=settled_mult
                    data["late_cashout_corrected_at"]=now
                    upd=await conn.execute(
                        "UPDATE live_game_sessions SET reward=?,data_json=?,updated_at=? WHERE session_id=? AND status='finished' AND reward=0",
                        (reward,json.dumps(data),now,session_id),
                    )
                    if int(upd.rowcount or 0)==1:
                        await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(reward,reward,int(row["guild_id"]),int(row["user_id"])))
                        await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(int(row["guild_id"]),int(row["user_id"]),reward,f"mav_late_cashout:{session_id}",now))
                        stats_payout=reward
                    else:
                        # Defensive re-read if another delayed callback corrected
                        # the same crash first. Never pay twice.
                        cur=await conn.execute("SELECT reward,data_json FROM live_game_sessions WHERE session_id=?",(session_id,))
                        latest=await cur.fetchone(); reward=int(latest["reward"] or 0); latest_data=json.loads(str(latest["data_json"] or "{}")); outcome=str(latest_data.get("settled_outcome") or "crash")
                else:
                    reward=existing_reward; outcome="crash"
            else:
                await conn.rollback(); raise ValueError("A MÁV kör már lezárult.")

            cur=await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",(int(row["guild_id"]),int(row["user_id"])))
            wallet=int((await cur.fetchone())[0]); await conn.commit()

        if self.statistics:
            if stats_round:await self.statistics.increment(int(row["guild_id"]),int(row["user_id"]),"live.mav.rounds")
            if stats_payout:await self.statistics.add(int(row["guild_id"]),int(row["user_id"]),"live.mav.payout",stats_payout)
        return LiveResult(session_id,"mav",reward,wallet,outcome)

    async def refund_active_mav(self,session_id:str,reason:str="runtime_failure")->LiveResult|None:
        """Fail-safe: refund an active MÁV stake exactly once.

        Any runner cancellation/unexpected exception must end in either a
        normal settlement or this atomic refund; an active stake may never be
        left hostage because a background task died.
        """
        now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT * FROM live_game_sessions WHERE session_id=?",(session_id,)); row=await cur.fetchone()
            if row is None or str(row["game"])!="mav" or str(row["status"])!="active":
                await conn.rollback(); return None
            stake=max(0,int(row["stake"])); data=json.loads(str(row["data_json"] or "{}")); data["settled_outcome"]=f"refund_{reason}"
            upd=await conn.execute(
                "UPDATE live_game_sessions SET status='cancelled',reward=?,data_json=?,finished_at=?,updated_at=? WHERE session_id=? AND status='active'",
                (stake,json.dumps(data),now,now,session_id),
            )
            if int(upd.rowcount or 0)!=1:
                await conn.rollback(); return None
            if stake:
                await conn.execute(
                    "UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?",
                    (stake,stake,int(row["guild_id"]),int(row["user_id"])),
                )
                await conn.execute(
                    "INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",
                    (int(row["guild_id"]),int(row["user_id"]),stake,f"mav_runtime_refund:{reason}:{session_id}",now),
                )
            cur=await conn.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",(int(row["guild_id"]),int(row["user_id"])))
            wallet=int((await cur.fetchone())[0]); await conn.commit()
        if self.statistics:
            await self.statistics.increment(int(row["guild_id"]),int(row["user_id"]),"live.mav.runtime_refunds")
        return LiveResult(session_id,"mav",stake,wallet,f"refund_{reason}")

    async def recover_after_restart(self)->dict[str,int]:
        refunded=0; cancelled=0; poker_refunded=0; now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; await conn.execute("BEGIN IMMEDIATE")
            cur=await conn.execute("SELECT * FROM live_game_sessions WHERE status='active'")
            for row in await cur.fetchall():
                stake=int(row["stake"])
                if stake>0:
                    await conn.execute("UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?",(stake,stake,int(row["guild_id"]),int(row["user_id"]))); await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(int(row["guild_id"]),int(row["user_id"]),stake,f"live_restart_refund:{row['session_id']}",now)); refunded+=stake
                await conn.execute("UPDATE live_game_sessions SET status='cancelled',finished_at=?,updated_at=? WHERE session_id=?",(now,now,str(row["session_id"]))); cancelled+=1
            cur=await conn.execute("SELECT table_id,guild_id FROM poker_tables WHERE status='active'")
            for table in await cur.fetchall():
                pcur=await conn.execute("SELECT user_id,reserved FROM poker_players WHERE table_id=? AND reserved>0",(str(table["table_id"]),))
                for p in await pcur.fetchall():
                    amount=int(p["reserved"]); await conn.execute("UPDATE users SET wallet=wallet+?,money_lost=MAX(0,money_lost-?) WHERE guild_id=? AND user_id=?",(amount,amount,int(table["guild_id"]),int(p["user_id"]))); await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(int(table["guild_id"]),int(p["user_id"]),amount,f"poker_restart_refund:{table['table_id']}",now)); poker_refunded+=amount
                await conn.execute("UPDATE poker_tables SET status='cancelled',finished_at=?,updated_at=? WHERE table_id=?",(now,now,str(table["table_id"])))
            await conn.execute("UPDATE poker_tables SET status='cancelled',finished_at=?,updated_at=? WHERE status='lobby'",(now,now))
            await conn.commit()
        return {"sessions":cancelled,"refunded":refunded,"poker_refunded":poker_refunded}

    async def create_poker_table(self,guild_id:int,channel_id:int,owner_id:int,buy_in:int)->str:
        if not await self.enabled(guild_id) or not await self.game_enabled(guild_id,"poker"):raise ValueError("A Poker ki van kapcsolva.")
        if buy_in<await self.poker_min_buyin(guild_id):raise ValueError(f"A minimum buy-in {await self.poker_min_buyin(guild_id):,}.")
        table_id=uuid.uuid4().hex[:12]; now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("INSERT INTO poker_tables(table_id,guild_id,channel_id,owner_id,buy_in,status,created_at,updated_at) VALUES(?,?,?,?,?,'lobby',?,?)",(table_id,guild_id,channel_id,owner_id,buy_in,now,now)); await conn.execute("INSERT INTO poker_players(table_id,user_id,seat) VALUES(?,?,0)",(table_id,owner_id)); await conn.commit()
        return table_id

    async def set_poker_message(self,table_id:str,message_id:int)->None:
        async with aiosqlite.connect(self.db.path) as conn:await conn.execute("UPDATE poker_tables SET message_id=?,updated_at=? WHERE table_id=?",(message_id,iso(now_utc()),table_id)); await conn.commit()

    async def add_poker_player(self,table_id:str,user_id:int)->int:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE"); cur=await conn.execute("SELECT status FROM poker_tables WHERE table_id=?",(table_id,)); row=await cur.fetchone()
            if not row or row[0]!="lobby":await conn.rollback();raise ValueError("A lobby már lezárult.")
            cur=await conn.execute("SELECT COUNT(*) FROM poker_players WHERE table_id=?",(table_id,)); count=int((await cur.fetchone())[0])
            if count>=6:await conn.rollback();raise ValueError("Az asztal megtelt.")
            await conn.execute("INSERT OR IGNORE INTO poker_players(table_id,user_id,seat) VALUES(?,?,?)",(table_id,user_id,count)); await conn.commit(); return count

    async def remove_poker_player(self,table_id:str,user_id:int)->None:
        async with aiosqlite.connect(self.db.path) as conn:await conn.execute("DELETE FROM poker_players WHERE table_id=? AND user_id=? AND reserved=0",(table_id,user_id)); await conn.commit()

    async def poker_lobby(self,table_id:str)->tuple[dict[str,Any],list[int]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; cur=await conn.execute("SELECT * FROM poker_tables WHERE table_id=?",(table_id,)); row=await cur.fetchone()
            if row is None:raise ValueError("Asztal nem található.")
            cur=await conn.execute("SELECT user_id FROM poker_players WHERE table_id=? ORDER BY seat",(table_id,)); players=[int(r[0]) for r in await cur.fetchall()]
        return dict(row),players

    async def reserve_poker_buyins(self,table_id:str)->tuple[dict[str,Any],list[int]]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; await conn.execute("BEGIN IMMEDIATE"); cur=await conn.execute("SELECT * FROM poker_tables WHERE table_id=?",(table_id,)); table=await cur.fetchone()
            if table is None or table["status"]!="lobby":await conn.rollback();raise ValueError("A lobby már lezárult.")
            cur=await conn.execute("SELECT user_id FROM poker_players WHERE table_id=? ORDER BY seat",(table_id,)); users=[int(r[0]) for r in await cur.fetchall()]
            if not 2<=len(users)<=6:await conn.rollback();raise ValueError("Pokerhez 2–6 játékos kell.")
            buy_in=int(table["buy_in"])
            try:
                for uid in users:await self._reserve_funds(conn,int(table["guild_id"]),uid,buy_in,f"poker_buyin:{table_id}")
            except Exception:await conn.rollback();raise
            await conn.execute("UPDATE poker_players SET reserved=? WHERE table_id=?",(buy_in,table_id)); await conn.execute("UPDATE poker_tables SET status='active',updated_at=? WHERE table_id=?",(iso(now_utc()),table_id)); await conn.commit(); return dict(table),users

    async def settle_poker(self,table_id:str,payouts:dict[int,int])->None:
        now=iso(now_utc())
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory=aiosqlite.Row; await conn.execute("BEGIN IMMEDIATE"); cur=await conn.execute("SELECT * FROM poker_tables WHERE table_id=?",(table_id,)); table=await cur.fetchone()
            if table is None or table["status"]!='active':await conn.rollback();raise ValueError("A poker asztal már lezárult.")
            upd=await conn.execute("UPDATE poker_tables SET status='finished',finished_at=?,updated_at=? WHERE table_id=? AND status='active'",(now,now,table_id))
            if int(upd.rowcount or 0)!=1:await conn.rollback();raise ValueError("A poker asztal már lezárult.")
            for uid,payout in payouts.items():
                payout=max(0,int(payout)); await conn.execute("UPDATE poker_players SET payout=?,status='finished' WHERE table_id=? AND user_id=?",(payout,table_id,uid))
                if payout:
                    await conn.execute("UPDATE users SET wallet=wallet+?,money_earned=money_earned+? WHERE guild_id=? AND user_id=?",(payout,payout,int(table["guild_id"]),uid)); await conn.execute("INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)",(int(table["guild_id"]),uid,payout,f"poker_settlement:{table_id}",now))
            await conn.commit()


def math_floor_2(value:float)->float:
    return int(float(value)*100)/100.0
