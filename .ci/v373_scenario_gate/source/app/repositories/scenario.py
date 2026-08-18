from __future__ import annotations

"""Persistence boundary for Scenario Engine V2.

Only scenario-selection/run bookkeeping lives here.  Economy, inventory, XP,
police/world and all other authoritative gameplay mutations remain in their
existing domain services/repositories.
"""

import json
from datetime import datetime, timezone
from typing import Any

from app import db_backend as aiosqlite
from app.scenarios.models import ScenarioRunState, ScenarioRunStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class ScenarioRepository:
    def __init__(self, path: str) -> None:
        self.path = path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await aiosqlite.execute_backend_ddl(
                db,
                sqlite_sql="""CREATE TABLE IF NOT EXISTS player_scenario_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    family TEXT NOT NULL,
                    scenario_key TEXT NOT NULL,
                    topic_hash TEXT NOT NULL,
                    outcome TEXT,
                    shown_at TEXT NOT NULL,
                    completed_at TEXT,
                    context_digest TEXT,
                    run_id TEXT
                )""",
                mysql_sql="""CREATE TABLE IF NOT EXISTS player_scenario_history (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    domain VARCHAR(64) NOT NULL,
                    family VARCHAR(128) NOT NULL,
                    scenario_key VARCHAR(191) NOT NULL,
                    topic_hash VARCHAR(191) NOT NULL,
                    outcome VARCHAR(64) NULL,
                    shown_at VARCHAR(64) NOT NULL,
                    completed_at VARCHAR(64) NULL,
                    context_digest VARCHAR(191) NULL,
                    run_id VARCHAR(64) NULL,
                    PRIMARY KEY(id),
                    KEY idx_scenario_history_recent(guild_id,user_id,family,id),
                    KEY idx_scenario_history_run(run_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
            )
            if not aiosqlite.using_mysql():
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scenario_history_recent ON player_scenario_history(guild_id,user_id,family,id DESC)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scenario_history_run ON player_scenario_history(run_id)"
                )

            await aiosqlite.execute_backend_ddl(
                db,
                sqlite_sql="""CREATE TABLE IF NOT EXISTS scenario_runs (
                    run_id TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    family TEXT NOT NULL,
                    scenario_key TEXT NOT NULL,
                    current_node TEXT NOT NULL,
                    run_state_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'deterministic',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )""",
                mysql_sql="""CREATE TABLE IF NOT EXISTS scenario_runs (
                    run_id VARCHAR(64) NOT NULL,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    domain VARCHAR(64) NOT NULL,
                    family VARCHAR(128) NOT NULL,
                    scenario_key VARCHAR(191) NOT NULL,
                    current_node VARCHAR(191) NOT NULL,
                    run_state_json LONGTEXT NOT NULL,
                    source VARCHAR(32) NOT NULL DEFAULT 'deterministic',
                    status VARCHAR(32) NOT NULL DEFAULT 'active',
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    expires_at VARCHAR(64) NULL,
                    PRIMARY KEY(run_id),
                    KEY idx_scenario_runs_active(guild_id,user_id,status,updated_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
            )
            if not aiosqlite.using_mysql():
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scenario_runs_active ON scenario_runs(guild_id,user_id,status,updated_at DESC)"
                )

            await aiosqlite.execute_backend_ddl(
                db,
                sqlite_sql="""CREATE TABLE IF NOT EXISTS scenario_shuffle_bags (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    family TEXT NOT NULL,
                    bag_json TEXT NOT NULL DEFAULT '[]',
                    catalog_digest TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(guild_id,user_id,family)
                )""",
                mysql_sql="""CREATE TABLE IF NOT EXISTS scenario_shuffle_bags (
                    guild_id BIGINT UNSIGNED NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    family VARCHAR(128) NOT NULL,
                    bag_json LONGTEXT NOT NULL,
                    catalog_digest VARCHAR(128) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(guild_id,user_id,family)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
            )
            await db.commit()

    async def recent_history(self, guild_id: int, user_id: int, family: str, *, limit: int = 12) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id,scenario_key,topic_hash,outcome,shown_at,completed_at,context_digest,run_id "
                "FROM player_scenario_history WHERE guild_id=? AND user_id=? AND family=? "
                "ORDER BY id DESC LIMIT ?",
                (int(guild_id), int(user_id), str(family), max(1, min(100, int(limit)))),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def record_shown(
        self,
        *,
        guild_id: int,
        user_id: int,
        domain: str,
        family: str,
        scenario_key: str,
        topic_hash: str,
        context_digest: str | None,
        run_id: str | None = None,
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO player_scenario_history(guild_id,user_id,domain,family,scenario_key,topic_hash,shown_at,context_digest,run_id) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    int(guild_id), int(user_id), str(domain), str(family), str(scenario_key),
                    str(topic_hash), _now(), context_digest, run_id,
                ),
            )
            await db.commit()
            return int(cur.lastrowid or 0)

    async def complete_history(self, *, run_id: str, outcome: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE player_scenario_history SET outcome=?,completed_at=? "
                "WHERE run_id=? AND completed_at IS NULL",
                (str(outcome), _now(), str(run_id)),
            )
            await db.commit()

    async def get_bag(self, guild_id: int, user_id: int, family: str) -> tuple[list[str], str | None]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT bag_json,catalog_digest FROM scenario_shuffle_bags WHERE guild_id=? AND user_id=? AND family=?",
                (int(guild_id), int(user_id), str(family)),
            )
            row = await cur.fetchone()
        if not row:
            return [], None
        try:
            value = json.loads(str(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
        bag = [str(item) for item in value if str(item)] if isinstance(value, list) else []
        return bag, str(row[1])

    async def save_bag(self, guild_id: int, user_id: int, family: str, bag: list[str], catalog_digest: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO scenario_shuffle_bags(guild_id,user_id,family,bag_json,catalog_digest,updated_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(guild_id,user_id,family) DO UPDATE SET
                     bag_json=excluded.bag_json,
                     catalog_digest=excluded.catalog_digest,
                     updated_at=excluded.updated_at""",
                (int(guild_id), int(user_id), str(family), _dump(list(bag)), str(catalog_digest), _now()),
            )
            await db.commit()

    async def create_run(
        self,
        *,
        run_id: str,
        guild_id: int,
        user_id: int,
        domain: str,
        family: str,
        scenario_key: str,
        current_node: str,
        state: dict[str, Any],
        source: str,
        expires_at: str | None,
    ) -> ScenarioRunState:
        now = _now()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO scenario_runs(run_id,guild_id,user_id,domain,family,scenario_key,current_node,run_state_json,source,status,created_at,updated_at,expires_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,?)",
                (
                    str(run_id), int(guild_id), int(user_id), str(domain), str(family), str(scenario_key),
                    str(current_node), _dump(state), str(source), now, now, expires_at,
                ),
            )
            await db.commit()
        return ScenarioRunState(
            run_id=str(run_id), guild_id=int(guild_id), user_id=int(user_id), domain=str(domain), family=str(family),
            scenario_key=str(scenario_key), current_node=str(current_node), source=str(source),
            status=ScenarioRunStatus.ACTIVE, state=dict(state), created_at=now, updated_at=now, expires_at=expires_at,
        )

    async def get_run(self, run_id: str) -> ScenarioRunState | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM scenario_runs WHERE run_id=?", (str(run_id),))
            row = await cur.fetchone()
        if not row:
            return None
        raw = dict(row)
        try:
            state = json.loads(str(raw.get("run_state_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            state = {}
        try:
            status = ScenarioRunStatus(str(raw["status"]))
        except ValueError:
            status = ScenarioRunStatus.CANCELLED
        return ScenarioRunState(
            run_id=str(raw["run_id"]), guild_id=int(raw["guild_id"]), user_id=int(raw["user_id"]),
            domain=str(raw["domain"]), family=str(raw["family"]), scenario_key=str(raw["scenario_key"]),
            current_node=str(raw["current_node"]), source=str(raw["source"]), status=status,
            state=state if isinstance(state, dict) else {}, created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]), expires_at=(str(raw["expires_at"]) if raw.get("expires_at") else None),
        )

    async def update_run(
        self,
        run_id: str,
        *,
        status: ScenarioRunStatus | str | None = None,
        scenario_key: str | None = None,
        current_node: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        fields = ["updated_at=?"]
        params: list[Any] = [_now()]
        if status is not None:
            fields.append("status=?")
            params.append(status.value if isinstance(status, ScenarioRunStatus) else str(status))
        if scenario_key is not None:
            fields.append("scenario_key=?")
            params.append(str(scenario_key))
        if current_node is not None:
            fields.append("current_node=?")
            params.append(str(current_node))
        if state is not None:
            fields.append("run_state_json=?")
            params.append(_dump(state))
        params.append(str(run_id))
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE scenario_runs SET {','.join(fields)} WHERE run_id=?", tuple(params))
            await db.commit()

    async def expire_stale_runs(self, *, now_iso: str | None = None) -> int:
        now_value = str(now_iso or _now())
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE scenario_runs SET status='expired',updated_at=? "
                "WHERE status='active' AND expires_at IS NOT NULL AND expires_at<=?",
                (now_value, now_value),
            )
            await db.commit()
            return max(0, int(cur.rowcount or 0))

    async def active_runs(self, *, guild_id: int | None = None, user_id: int | None = None) -> list[ScenarioRunState]:
        clauses = ["status='active'"]
        params: list[Any] = []
        if guild_id is not None:
            clauses.append("guild_id=?")
            params.append(int(guild_id))
        if user_id is not None:
            clauses.append("user_id=?")
            params.append(int(user_id))
        sql = "SELECT run_id FROM scenario_runs WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC"
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(sql, tuple(params))
            rows = await cur.fetchall()
        result: list[ScenarioRunState] = []
        for row in rows:
            item = await self.get_run(str(row[0]))
            if item is not None:
                result.append(item)
        return result
