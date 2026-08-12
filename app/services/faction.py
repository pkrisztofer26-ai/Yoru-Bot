from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite

from app import faction_config as cfg
from app.services.server_settings import ServerSettingsService


@dataclass(frozen=True)
class FactionProgress:
    crew_id: int
    xp: int
    level: int
    lifetime_xp: int
    war_wins: int
    war_losses: int
    war_draws: int
    war_points: int
    perk_points_total: int
    perk_points_spent: int

    @property
    def perk_points_available(self) -> int:
        return max(0, self.perk_points_total - self.perk_points_spent)


class FactionService:
    """Frakció 2.0 layer over the backwards-compatible Crew identity tables."""

    def __init__(self, database, statistics, crew_service) -> None:
        self.db = database
        self.stats = statistics
        self.crew = crew_service
        self.settings = ServerSettingsService(database)
        self.stats.register_listener(self.on_stat_change)
        if hasattr(self.crew, "bind_faction"):
            self.crew.bind_faction(self)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _daily_key(now: datetime | None = None) -> str:
        now = now or FactionService._now()
        return now.date().isoformat()

    @staticmethod
    def _weekly_key(now: datetime | None = None) -> str:
        now = now or FactionService._now()
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"

    async def enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.FACTION_ENABLED_KEY, cfg.FACTION_DEFAULT_ENABLED)

    async def objectives_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.FACTION_OBJECTIVES_ENABLED_KEY, cfg.FACTION_DEFAULT_OBJECTIVES_ENABLED)

    async def wars_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.FACTION_WARS_ENABLED_KEY, cfg.FACTION_DEFAULT_WARS_ENABLED)

    async def xp_multiplier_percent(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, cfg.FACTION_XP_MULTIPLIER_KEY)
        value = cfg.FACTION_DEFAULT_XP_MULTIPLIER_PERCENT if value is None else int(value)
        return max(cfg.FACTION_XP_MULTIPLIER_MIN, min(cfg.FACTION_XP_MULTIPLIER_MAX, value))

    async def set_xp_multiplier_percent(self, guild_id: int, value: int) -> None:
        value = int(value)
        if not cfg.FACTION_XP_MULTIPLIER_MIN <= value <= cfg.FACTION_XP_MULTIPLIER_MAX:
            raise ValueError(f"Az XP szorzó {cfg.FACTION_XP_MULTIPLIER_MIN}–{cfg.FACTION_XP_MULTIPLIER_MAX}% között lehet.")
        await self.settings.set_int(guild_id, cfg.FACTION_XP_MULTIPLIER_KEY, value)

    async def progress(self, guild_id: int, crew_id: int) -> FactionProgress:
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO crew_faction_progress (guild_id,crew_id,xp,level,lifetime_xp,updated_at) VALUES (?,?,0,1,0,?)",
                (guild_id, crew_id, self._now().isoformat()),
            )
            cur = await conn.execute(
                "SELECT xp,level,lifetime_xp,war_wins,war_losses,war_draws,war_points FROM crew_faction_progress WHERE guild_id=? AND crew_id=?",
                (guild_id, crew_id),
            )
            row = await cur.fetchone()
            cur = await conn.execute(
                "SELECT COALESCE(SUM(rank),0) FROM crew_perks WHERE guild_id=? AND crew_id=?",
                (guild_id, crew_id),
            )
            spent = int((await cur.fetchone())[0])
            await conn.commit()
        xp, level, lifetime = int(row[0]), int(row[1]), int(row[2])
        war_wins, war_losses, war_draws, war_points = int(row[3]), int(row[4]), int(row[5]), int(row[6])
        true_level = cfg.level_for_xp(xp)
        if true_level != level:
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute(
                    "UPDATE crew_faction_progress SET level=?,updated_at=? WHERE guild_id=? AND crew_id=?",
                    (true_level, self._now().isoformat(), guild_id, crew_id),
                )
                await conn.commit()
            level = true_level
        return FactionProgress(crew_id, xp, level, lifetime, war_wins, war_losses, war_draws, war_points, cfg.total_perk_points(level), spent)

    async def member_progress(self, guild_id: int, crew_id: int, user_id: int) -> dict[str, int]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT contribution_xp,events FROM crew_member_faction WHERE guild_id=? AND crew_id=? AND user_id=?",
                (guild_id, crew_id, user_id),
            )
            row = await cur.fetchone()
        return {"contribution_xp": int(row[0]) if row else 0, "events": int(row[1]) if row else 0}

    async def perk_ranks(self, guild_id: int, crew_id: int) -> dict[str, int]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT perk_key,rank FROM crew_perks WHERE guild_id=? AND crew_id=?",
                (guild_id, crew_id),
            )
            rows = await cur.fetchall()
        return {str(key): int(rank) for key, rank in rows}

    async def perk_rank(self, guild_id: int, crew_id: int, key: str) -> int:
        return int((await self.perk_ranks(guild_id, crew_id)).get(key, 0))

    async def income_bonus(self, guild_id: int, crew_id: int) -> float:
        return 0.005 * await self.perk_rank(guild_id, crew_id, "treasury")

    async def _can(self, guild_id: int, user_id: int, permission: str) -> bool:
        membership = await self.crew.get_membership(guild_id, user_id)
        if membership is None:
            return False
        if membership.member.role == "leader":
            return True
        if membership.member.role == "officer" and permission in {"invite", "kick"}:
            return True
        rank = await self.custom_rank_for_member(guild_id, membership.crew.crew_id, user_id)
        return bool(rank and permission in rank["permissions"])

    async def has_permission(self, guild_id: int, user_id: int, permission: str) -> bool:
        return await self._can(guild_id, user_id, permission)

    async def _apply_xp(self, guild_id: int, crew_id: int, user_id: int | None, base_xp: int) -> int:
        if base_xp <= 0 or not await self.enabled(guild_id):
            return 0
        percent = await self.xp_multiplier_percent(guild_id)
        momentum = await self.perk_rank(guild_id, crew_id, "momentum")
        awarded = max(1, round(base_xp * percent / 100 * (1 + 0.10 * momentum)))
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                "INSERT OR IGNORE INTO crew_faction_progress (guild_id,crew_id,xp,level,lifetime_xp,updated_at) VALUES (?,?,0,1,0,?)",
                (guild_id, crew_id, now),
            )
            cur = await conn.execute(
                "SELECT xp FROM crew_faction_progress WHERE guild_id=? AND crew_id=?",
                (guild_id, crew_id),
            )
            old_xp = int((await cur.fetchone())[0])
            new_xp = old_xp + awarded
            new_level = cfg.level_for_xp(new_xp)
            await conn.execute(
                "UPDATE crew_faction_progress SET xp=?,level=?,lifetime_xp=lifetime_xp+?,updated_at=? WHERE guild_id=? AND crew_id=?",
                (new_xp, new_level, awarded, now, guild_id, crew_id),
            )
            if user_id is not None:
                await conn.execute(
                    """INSERT INTO crew_member_faction (guild_id,crew_id,user_id,contribution_xp,events,updated_at)
                       VALUES (?,?,?, ?,1,?)
                       ON CONFLICT(guild_id,crew_id,user_id) DO UPDATE SET
                       contribution_xp=contribution_xp+excluded.contribution_xp,events=events+1,updated_at=excluded.updated_at""",
                    (guild_id, crew_id, user_id, awarded, now),
                )
            await conn.commit()
        return awarded

    async def add_xp_for_member(self, guild_id: int, user_id: int, base_xp: int, source: str = "manual") -> int:
        membership = await self.crew.get_membership(guild_id, user_id)
        if membership is None:
            return 0
        return await self._apply_xp(guild_id, membership.crew.crew_id, user_id, base_xp)

    async def on_stat_change(self, guild_id: int, user_id: int, stat_name: str, amount: int) -> None:
        if amount <= 0 or not await self.enabled(guild_id):
            return
        membership = await self.crew.get_membership(guild_id, user_id)
        if membership is None:
            return
        base_xp = cfg.STAT_XP.get(stat_name, 0) * amount
        if stat_name == "crew.contributed":
            base_xp = min(cfg.DEPOSIT_XP_CAP_PER_EVENT, max(1, amount // cfg.DEPOSIT_XP_PER))
        if base_xp > 0:
            await self._apply_xp(guild_id, membership.crew.crew_id, user_id, base_xp)
        await self.record_event(guild_id, user_id, stat_name, amount, membership=membership)

    async def record_activity_xp(self, guild_id: int, user_id: int, activity_xp: int) -> None:
        if activity_xp <= 0:
            return
        membership = await self.crew.get_membership(guild_id, user_id)
        if membership is None:
            return
        base_xp = max(1, int(activity_xp) // cfg.ACTIVITY_XP_DIVISOR)
        await self._apply_xp(guild_id, membership.crew.crew_id, user_id, base_xp)
        await self.record_event(guild_id, user_id, "activity.xp", int(activity_xp), membership=membership)

    async def ensure_objectives(self, guild_id: int, crew_id: int, period: str) -> list[dict]:
        if period not in {"daily", "weekly"}:
            raise ValueError("Ismeretlen objective időszak.")
        key = self._daily_key() if period == "daily" else self._weekly_key()
        definitions = cfg.DAILY_OBJECTIVES if period == "daily" else cfg.WEEKLY_OBJECTIVES
        count = cfg.FACTION_OBJECTIVES_DAILY if period == "daily" else cfg.FACTION_OBJECTIVES_WEEKLY
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT slot,objective_id,progress,target,reward_xp,reward_bank,completed,completed_at FROM crew_objectives WHERE guild_id=? AND crew_id=? AND period=? AND period_key=? ORDER BY slot",
                (guild_id, crew_id, period, key),
            )
            rows = await cur.fetchall()
            if not rows:
                rng = random.Random(f"yoru:faction:{guild_id}:{crew_id}:{period}:{key}")
                chosen = rng.sample(list(definitions), k=min(count, len(definitions)))
                now = self._now().isoformat()
                for slot, definition in enumerate(chosen, 1):
                    await conn.execute(
                        """INSERT OR IGNORE INTO crew_objectives
                           (guild_id,crew_id,period,period_key,slot,objective_id,progress,target,reward_xp,reward_bank,completed,created_at)
                           VALUES (?,?,?,?,?,?,0,?,?,?,0,?)""",
                        (guild_id, crew_id, period, key, slot, definition.objective_id, definition.target, definition.reward_xp, definition.reward_bank, now),
                    )
                await conn.commit()
                cur = await conn.execute(
                    "SELECT slot,objective_id,progress,target,reward_xp,reward_bank,completed,completed_at FROM crew_objectives WHERE guild_id=? AND crew_id=? AND period=? AND period_key=? ORDER BY slot",
                    (guild_id, crew_id, period, key),
                )
                rows = await cur.fetchall()
        result: list[dict] = []
        for row in rows:
            definition = cfg.OBJECTIVE_BY_ID.get(str(row[1]))
            if definition is None:
                continue
            result.append({
                "slot": int(row[0]), "objective_id": str(row[1]), "label": definition.label,
                "emoji": definition.emoji, "stat": definition.stat, "progress": int(row[2]),
                "target": int(row[3]), "reward_xp": int(row[4]), "reward_bank": int(row[5]),
                "completed": bool(row[6]), "completed_at": row[7], "period": period, "period_key": key,
            })
        return result

    async def objectives(self, guild_id: int, crew_id: int) -> tuple[list[dict], list[dict]]:
        if not await self.objectives_enabled(guild_id):
            return [], []
        return await self.ensure_objectives(guild_id, crew_id, "daily"), await self.ensure_objectives(guild_id, crew_id, "weekly")

    async def _complete_objective_reward(self, guild_id: int, crew_id: int, user_id: int, reward_xp: int, reward_bank: int) -> None:
        rank = await self.perk_rank(guild_id, crew_id, "objectives")
        multiplier = 1 + 0.10 * rank
        xp = max(1, round(reward_xp * multiplier))
        bank = max(0, round(reward_bank * multiplier))
        if bank:
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("UPDATE crews SET bank=bank+? WHERE guild_id=? AND crew_id=?", (bank, guild_id, crew_id))
                await conn.commit()
        await self._apply_xp(guild_id, crew_id, user_id, xp)

    async def record_event(self, guild_id: int, user_id: int, stat_name: str, amount: int, *, membership=None) -> None:
        if amount <= 0:
            return
        membership = membership or await self.crew.get_membership(guild_id, user_id)
        if membership is None:
            return
        crew_id = membership.crew.crew_id
        if await self.objectives_enabled(guild_id):
            for period in ("daily", "weekly"):
                rows = await self.ensure_objectives(guild_id, crew_id, period)
                for objective in rows:
                    if objective["completed"] or objective["stat"] != stat_name:
                        continue
                    increment = int(amount)
                    async with aiosqlite.connect(self.db.path) as conn:
                        await conn.execute("BEGIN IMMEDIATE")
                        cur = await conn.execute(
                            "SELECT progress,target,completed FROM crew_objectives WHERE guild_id=? AND crew_id=? AND period=? AND period_key=? AND slot=?",
                            (guild_id, crew_id, period, objective["period_key"], objective["slot"]),
                        )
                        current = await cur.fetchone()
                        if current is None or int(current[2]):
                            await conn.rollback()
                            continue
                        new_progress = min(int(current[1]), int(current[0]) + increment)
                        newly_completed = new_progress >= int(current[1])
                        completed_at = self._now().isoformat() if newly_completed else None
                        await conn.execute(
                            "UPDATE crew_objectives SET progress=?,completed=?,completed_at=? WHERE guild_id=? AND crew_id=? AND period=? AND period_key=? AND slot=?",
                            (new_progress, 1 if newly_completed else 0, completed_at, guild_id, crew_id, period, objective["period_key"], objective["slot"]),
                        )
                        await conn.commit()
                    if newly_completed:
                        await self._complete_objective_reward(guild_id, crew_id, user_id, objective["reward_xp"], objective["reward_bank"])
        await self._record_war_event(guild_id, crew_id, user_id, stat_name, amount)

    async def buy_perk(self, guild_id: int, actor_id: int, perk_key: str) -> int:
        if perk_key not in cfg.PERK_BY_KEY:
            raise ValueError("Ismeretlen perk.")
        if not await self._can(guild_id, actor_id, "manage_perks"):
            raise ValueError("Nincs jogosultságod Frakció perkeket fejleszteni.")
        membership = await self.crew.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        progress = await self.progress(guild_id, membership.crew.crew_id)
        perk = cfg.PERK_BY_KEY[perk_key]
        ranks = await self.perk_ranks(guild_id, membership.crew.crew_id)
        current = int(ranks.get(perk_key, 0))
        if current >= perk.max_rank:
            raise ValueError("Ez a perk már max rangú.")
        if progress.perk_points_available <= 0:
            raise ValueError("Nincs elkölthető perk pontotok. Minden 5 Frakció szint ad 1 pontot.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                """INSERT INTO crew_perks (guild_id,crew_id,perk_key,rank) VALUES (?,?,?,1)
                   ON CONFLICT(guild_id,crew_id,perk_key) DO UPDATE SET rank=rank+1""",
                (guild_id, membership.crew.crew_id, perk_key),
            )
            await conn.commit()
        return current + 1

    async def custom_ranks(self, guild_id: int, crew_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT rank_id,name,position,permissions_json FROM crew_custom_ranks WHERE guild_id=? AND crew_id=? ORDER BY position DESC,rank_id ASC",
                (guild_id, crew_id),
            )
            rows = await cur.fetchall()
        result = []
        for rank_id, name, position, raw in rows:
            try:
                perms = [p for p in json.loads(raw or "[]") if p in cfg.CUSTOM_RANK_PERMISSIONS]
            except (TypeError, ValueError, json.JSONDecodeError):
                perms = []
            result.append({"rank_id": int(rank_id), "name": str(name), "position": int(position), "permissions": perms})
        return result

    async def custom_rank_for_member(self, guild_id: int, crew_id: int, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """SELECT r.rank_id,r.name,r.position,r.permissions_json FROM crew_member_custom_ranks m
                   JOIN crew_custom_ranks r ON r.rank_id=m.rank_id
                   WHERE m.guild_id=? AND m.crew_id=? AND m.user_id=?""",
                (guild_id, crew_id, user_id),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        try:
            perms = [p for p in json.loads(row[3] or "[]") if p in cfg.CUSTOM_RANK_PERMISSIONS]
        except (TypeError, ValueError, json.JSONDecodeError):
            perms = []
        return {"rank_id": int(row[0]), "name": str(row[1]), "position": int(row[2]), "permissions": perms}

    async def create_custom_rank(self, guild_id: int, actor_id: int, name: str, permissions: list[str]) -> dict:
        if not await self._can(guild_id, actor_id, "manage_ranks"):
            raise ValueError("Nincs jogosultságod belső rangot létrehozni.")
        membership = await self.crew.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        clean = " ".join(name.strip().split())
        if not 2 <= len(clean) <= 24:
            raise ValueError("A belső rang neve 2–24 karakter lehet.")
        valid = []
        for perm in permissions:
            perm = perm.strip().lower()
            if perm in cfg.CUSTOM_RANK_PERMISSIONS and perm not in valid:
                valid.append(perm)
        ranks = await self.custom_ranks(guild_id, membership.crew.crew_id)
        if len(ranks) >= cfg.FACTION_MAX_CUSTOM_RANKS:
            raise ValueError(f"Maximum {cfg.FACTION_MAX_CUSTOM_RANKS} egyedi belső rang lehet.")
        if any(rank["name"].casefold() == clean.casefold() for rank in ranks):
            raise ValueError("Már van ilyen nevű belső rang.")
        position = max([int(r["position"]) for r in ranks], default=0) + 1
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "INSERT INTO crew_custom_ranks (guild_id,crew_id,name,position,permissions_json,created_at) VALUES (?,?,?,?,?,?)",
                (guild_id, membership.crew.crew_id, clean, position, json.dumps(valid, separators=(",", ":")), self._now().isoformat()),
            )
            await conn.commit()
            rank_id = int(cur.lastrowid)
        return {"rank_id": rank_id, "name": clean, "position": position, "permissions": valid}

    async def delete_custom_rank(self, guild_id: int, actor_id: int, rank_id: int) -> None:
        if not await self._can(guild_id, actor_id, "manage_ranks"):
            raise ValueError("Nincs jogosultságod belső rangot törölni.")
        membership = await self.crew.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT 1 FROM crew_custom_ranks WHERE guild_id=? AND crew_id=? AND rank_id=?",
                (guild_id, membership.crew.crew_id, int(rank_id)),
            )
            if await cur.fetchone() is None:
                await conn.rollback()
                raise ValueError("Ez a belső rang nem található.")
            await conn.execute("DELETE FROM crew_member_custom_ranks WHERE guild_id=? AND crew_id=? AND rank_id=?", (guild_id, membership.crew.crew_id, int(rank_id)))
            await conn.execute("DELETE FROM crew_custom_ranks WHERE guild_id=? AND crew_id=? AND rank_id=?", (guild_id, membership.crew.crew_id, int(rank_id)))
            await conn.commit()

    async def assign_custom_rank(self, guild_id: int, actor_id: int, target_id: int, rank_id: int | None) -> None:
        if not await self._can(guild_id, actor_id, "manage_ranks"):
            raise ValueError("Nincs jogosultságod belső rangot kiosztani.")
        actor = await self.crew.get_membership(guild_id, actor_id)
        target = await self.crew.get_membership(guild_id, target_id)
        if actor is None or target is None or actor.crew.crew_id != target.crew.crew_id:
            raise ValueError("A célpont nem a Frakció tagja.")
        if target.member.role == "leader":
            raise ValueError("A Leader belső rangja nem módosítható.")
        async with aiosqlite.connect(self.db.path) as conn:
            if rank_id is None:
                await conn.execute("DELETE FROM crew_member_custom_ranks WHERE guild_id=? AND crew_id=? AND user_id=?", (guild_id, actor.crew.crew_id, target_id))
            else:
                cur = await conn.execute("SELECT 1 FROM crew_custom_ranks WHERE guild_id=? AND crew_id=? AND rank_id=?", (guild_id, actor.crew.crew_id, int(rank_id)))
                if await cur.fetchone() is None:
                    raise ValueError("A belső rang nem található.")
                await conn.execute(
                    """INSERT INTO crew_member_custom_ranks (guild_id,crew_id,user_id,rank_id) VALUES (?,?,?,?)
                       ON CONFLICT(guild_id,crew_id,user_id) DO UPDATE SET rank_id=excluded.rank_id""",
                    (guild_id, actor.crew.crew_id, target_id, int(rank_id)),
                )
            await conn.commit()

    async def create_war(self, guild_id: int, actor_id: int, opponent_crew_id: int) -> dict:
        if not await self.wars_enabled(guild_id):
            raise ValueError("A Frakció Wars ki van kapcsolva ezen a szerveren.")
        if not await self._can(guild_id, actor_id, "manage_wars"):
            raise ValueError("Nincs jogosultságod War-t indítani.")
        actor = await self.crew.get_membership(guild_id, actor_id)
        if actor is None:
            raise ValueError("Nem vagy Frakció tagja.")
        if actor.crew.crew_id == int(opponent_crew_id):
            raise ValueError("Saját Frakciót nem hívhatsz ki.")
        opponent = await self.crew.get_crew(guild_id, int(opponent_crew_id))
        if opponent is None:
            raise ValueError("A cél Frakció nem található.")
        existing = await self.war_for_crew(guild_id, actor.crew.crew_id)
        if existing and existing["status"] in {"pending", "active"}:
            raise ValueError("A Frakciótoknak már van aktív/pending War-ja.")
        if await self.war_for_crew(guild_id, int(opponent_crew_id)):
            raise ValueError("A cél Frakció jelenleg már másik War-ban van.")
        objective = random.Random(f"yoru:war:{guild_id}:{actor.crew.crew_id}:{opponent_crew_id}:{self._weekly_key()}").choice(cfg.WAR_OBJECTIVES)
        now = self._now()
        expires = now + timedelta(hours=cfg.FACTION_WAR_CHALLENGE_HOURS)
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                """INSERT INTO crew_wars
                   (guild_id,challenger_crew_id,target_crew_id,objective_id,stat,target,challenger_score,target_score,status,created_by,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,0,0,'pending',?,?,?)""",
                (guild_id, actor.crew.crew_id, int(opponent_crew_id), objective.objective_id, objective.stat, objective.target, actor_id, now.isoformat(), expires.isoformat()),
            )
            await conn.commit()
            war_id = int(cur.lastrowid)
        return await self.get_war(guild_id, war_id)

    async def get_war(self, guild_id: int, war_id: int) -> dict | None:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM crew_wars WHERE guild_id=? AND war_id=?", (guild_id, int(war_id)))
            row = await cur.fetchone()
        return dict(row) if row else None

    async def war_for_crew(self, guild_id: int, crew_id: int) -> dict | None:
        await self.reconcile_expired_wars(guild_id)
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT * FROM crew_wars WHERE guild_id=? AND status IN ('pending','active')
                   AND (challenger_crew_id=? OR target_crew_id=?) ORDER BY war_id DESC LIMIT 1""",
                (guild_id, crew_id, crew_id),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def accept_war(self, guild_id: int, actor_id: int) -> dict:
        if not await self._can(guild_id, actor_id, "manage_wars"):
            raise ValueError("Nincs jogosultságod War-t elfogadni.")
        membership = await self.crew.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        war = await self.war_for_crew(guild_id, membership.crew.crew_id)
        if not war or war["status"] != "pending" or int(war["target_crew_id"]) != membership.crew.crew_id:
            raise ValueError("Nincs elfogadható War kihívásotok.")
        now = self._now()
        ends = now + timedelta(hours=cfg.FACTION_WAR_HOURS)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute(
                "UPDATE crew_wars SET status='active',accepted_at=?,expires_at=? WHERE guild_id=? AND war_id=? AND status='pending'",
                (now.isoformat(), ends.isoformat(), guild_id, int(war["war_id"])),
            )
            await conn.commit()
        return await self.get_war(guild_id, int(war["war_id"]))

    async def decline_war(self, guild_id: int, actor_id: int) -> None:
        if not await self._can(guild_id, actor_id, "manage_wars"):
            raise ValueError("Nincs jogosultságod War-t elutasítani.")
        membership = await self.crew.get_membership(guild_id, actor_id)
        if membership is None:
            raise ValueError("Nem vagy Frakció tagja.")
        war = await self.war_for_crew(guild_id, membership.crew.crew_id)
        if not war or war["status"] != "pending" or int(war["target_crew_id"]) != membership.crew.crew_id:
            raise ValueError("Nincs elutasítható War kihívásotok.")
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("UPDATE crew_wars SET status='declined',resolved_at=? WHERE guild_id=? AND war_id=?", (self._now().isoformat(), guild_id, int(war["war_id"])))
            await conn.commit()

    async def _record_war_event(self, guild_id: int, crew_id: int, user_id: int, stat_name: str, amount: int) -> None:
        if not await self.wars_enabled(guild_id):
            return
        war = await self.war_for_crew(guild_id, crew_id)
        if not war or war["status"] != "active" or str(war["stat"]) != stat_name:
            return
        side = "challenger_score" if int(war["challenger_crew_id"]) == crew_id else "target_score"
        target = int(war["target"])
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(f"SELECT {side},status FROM crew_wars WHERE guild_id=? AND war_id=?", (guild_id, int(war["war_id"])))
            row = await cur.fetchone()
            if row is None or str(row[1]) != "active":
                await conn.rollback()
                return
            score = min(target, int(row[0]) + int(amount))
            await conn.execute(f"UPDATE crew_wars SET {side}=? WHERE guild_id=? AND war_id=?", (score, guild_id, int(war["war_id"])))
            await conn.commit()
        if score >= target:
            await self._resolve_war(guild_id, int(war["war_id"]), crew_id)

    async def _war_reward(self, guild_id: int, crew_id: int, *, winner: bool, draw: bool = False) -> None:
        rank = await self.perk_rank(guild_id, crew_id, "war")
        multiplier = 1 + 0.10 * rank
        if draw:
            bank = round(cfg.FACTION_WAR_DRAW_BANK * multiplier)
            xp = round(cfg.FACTION_WAR_DRAW_XP * multiplier)
        elif winner:
            bank = round(cfg.FACTION_WAR_WIN_BANK * multiplier)
            xp = round(cfg.FACTION_WAR_WIN_XP * multiplier)
        else:
            bank, xp = 0, 0
        if bank:
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("UPDATE crews SET bank=bank+? WHERE guild_id=? AND crew_id=?", (bank, guild_id, crew_id))
                await conn.commit()
        if xp:
            await self._apply_xp(guild_id, crew_id, None, xp)

    async def _resolve_war(self, guild_id: int, war_id: int, winner_crew_id: int | None) -> None:
        war = await self.get_war(guild_id, war_id)
        if not war or war["status"] != "active":
            return
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "UPDATE crew_wars SET status='resolved',winner_crew_id=?,resolved_at=? WHERE guild_id=? AND war_id=? AND status='active'",
                (winner_crew_id, self._now().isoformat(), guild_id, war_id),
            )
            await conn.commit()
            if not cur.rowcount:
                return
        challenger = int(war["challenger_crew_id"])
        target = int(war["target_crew_id"])
        now = self._now().isoformat()
        async with aiosqlite.connect(self.db.path) as conn:
            for crew_id in (challenger, target):
                await conn.execute(
                    "INSERT OR IGNORE INTO crew_faction_progress (guild_id,crew_id,xp,level,lifetime_xp,updated_at) VALUES (?,?,0,1,0,?)",
                    (guild_id, crew_id, now),
                )
            if winner_crew_id is None:
                await conn.execute("UPDATE crew_faction_progress SET war_draws=war_draws+1,war_points=war_points+1,updated_at=? WHERE guild_id=? AND crew_id IN (?,?)", (now, guild_id, challenger, target))
            else:
                winner = int(winner_crew_id)
                loser = target if winner == challenger else challenger
                await conn.execute("UPDATE crew_faction_progress SET war_wins=war_wins+1,war_points=war_points+3,updated_at=? WHERE guild_id=? AND crew_id=?", (now, guild_id, winner))
                await conn.execute("UPDATE crew_faction_progress SET war_losses=war_losses+1,updated_at=? WHERE guild_id=? AND crew_id=?", (now, guild_id, loser))
            await conn.commit()
        if winner_crew_id is None:
            await self._war_reward(guild_id, challenger, winner=False, draw=True)
            await self._war_reward(guild_id, target, winner=False, draw=True)
        else:
            await self._war_reward(guild_id, int(winner_crew_id), winner=True)

    async def reconcile_expired_wars(self, guild_id: int) -> int:
        now = self._now()
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM crew_wars WHERE guild_id=? AND status IN ('pending','active') AND expires_at<=?", (guild_id, now.isoformat()))
            rows = [dict(row) for row in await cur.fetchall()]
        resolved = 0
        for war in rows:
            if war["status"] == "pending":
                async with aiosqlite.connect(self.db.path) as conn:
                    await conn.execute("UPDATE crew_wars SET status='expired',resolved_at=? WHERE guild_id=? AND war_id=? AND status='pending'", (now.isoformat(), guild_id, int(war["war_id"])))
                    await conn.commit()
                resolved += 1
                continue
            left, right = int(war["challenger_score"]), int(war["target_score"])
            winner = int(war["challenger_crew_id"]) if left > right else int(war["target_crew_id"]) if right > left else None
            await self._resolve_war(guild_id, int(war["war_id"]), winner)
            resolved += 1
        return resolved

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict]:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                """SELECT c.crew_id,c.name,c.owner_id,c.bank,c.level AS infrastructure_level,c.total_contributed,
                          COUNT(m.user_id) AS member_count,COALESCE(p.xp,0) AS faction_xp,COALESCE(p.level,1) AS faction_level,
                          COALESCE(p.war_wins,0) AS war_wins,COALESCE(p.war_losses,0) AS war_losses,
                          COALESCE(p.war_draws,0) AS war_draws,COALESCE(p.war_points,0) AS war_points
                   FROM crews c
                   LEFT JOIN crew_members m ON m.guild_id=c.guild_id AND m.crew_id=c.crew_id
                   LEFT JOIN crew_faction_progress p ON p.guild_id=c.guild_id AND p.crew_id=c.crew_id
                   WHERE c.guild_id=? GROUP BY c.crew_id
                   ORDER BY faction_level DESC,faction_xp DESC,war_points DESC,c.total_contributed DESC,c.bank DESC LIMIT ?""",
                (guild_id, max(1, int(limit))),
            )
            return [dict(row) for row in await cur.fetchall()]
