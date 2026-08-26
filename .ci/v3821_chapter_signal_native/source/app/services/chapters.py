from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from app import db_backend as aiosqlite
from app import chapter_config as cfg


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ChapterRunSnapshot:
    chapter_run_id: int
    guild_id: int
    chapter_key: str
    status: str
    current_stage_key: str
    started_at: str
    stage_started_at: str
    deadline_at: str
    updated_at: str
    resolved_at: str | None
    ending_key: str | None
    resolution_snapshot: dict[str, object]

    @property
    def definition(self) -> cfg.ChapterDefinition:
        return cfg.CHAPTER_BY_KEY[self.chapter_key]

    @property
    def stage(self) -> cfg.ChapterStageDefinition:
        return self.definition.stage(self.current_stage_key) or self.definition.stages[0]

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def awaiting_resolution(self) -> bool:
        return self.status == "awaiting_resolution"


@dataclass(frozen=True, slots=True)
class ChapterContextSnapshot:
    run: ChapterRunSnapshot
    world_cycle_id: str
    national_title: str
    world_story_title: str | None
    community_project_title: str | None
    community_project_progress_band: str | None
    causality_bands: tuple[str, ...]
    ending_pressures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChapterEndingWeightSnapshot:
    """Read-only, replay-stable projection over canonical committed history."""

    chapter_run_id: int
    weights: tuple[tuple[str, int], ...]
    source_counts: tuple[tuple[str, int], ...]
    narratives: tuple[str, ...]


class ChapterService:
    """Phase 11 server-level chapter orchestration state.

    W21.1 owns only the multi-week chapter lifecycle shell. It deliberately does
    not own Scenario outcomes, Opportunity execution, Contract settlement,
    Community Project contributions, Business/Crime/Social rewards, Memory facts,
    World Story branches or Asset/Collectible ownership.

    Those existing systems remain canonical. Later chapter ending weights must be
    derived from their committed histories, not from a second chapter XP/score.
    """

    def __init__(self, database, world) -> None:
        self.db = database
        self.world = world

    _ENDING_ORDER = ("shared_recovery", "fractured_balance", "shadow_network")

    @classmethod
    def _normalize_weights(cls, additions: dict[str, int]) -> tuple[tuple[str, int], ...]:
        raw = {
            "shared_recovery": 34 + max(0, int(additions.get("shared_recovery", 0))),
            "fractured_balance": 33 + max(0, int(additions.get("fractured_balance", 0))),
            "shadow_network": 33 + max(0, int(additions.get("shadow_network", 0))),
        }
        total = max(1, sum(raw.values()))
        weights = {key: (raw[key] * 100) // total for key in cls._ENDING_ORDER}
        remainder = 100 - sum(weights.values())
        for key in sorted(cls._ENDING_ORDER, key=lambda item: (-raw[item], cls._ENDING_ORDER.index(item))):
            if remainder <= 0:
                break
            weights[key] += 1
            remainder -= 1
        strongest = max(cls._ENDING_ORDER, key=lambda item: (weights[item], -cls._ENDING_ORDER.index(item)))
        if weights[strongest] > 65:
            overflow = weights[strongest] - 65
            weights[strongest] = 65
            others = [item for item in cls._ENDING_ORDER if item != strongest]
            for index in range(overflow):
                weights[others[index % len(others)]] += 1
        return tuple((key, weights[key]) for key in cls._ENDING_ORDER)

    @classmethod
    def _narratives(cls, weights: tuple[tuple[str, int], ...]) -> tuple[str, ...]:
        values = dict(weights)
        ranked = sorted(cls._ENDING_ORDER, key=lambda key: (-values[key], cls._ENDING_ORDER.index(key)))
        if values[ranked[0]] - values[ranked[1]] < 8:
            return ("⚖️ Több lehetséges irány továbbra is közel marad egymáshoz.",)
        labels = {
            "shared_recovery": "🤝 A közös és rendezett válaszok iránya erősödik.",
            "fractured_balance": "⚖️ A kompromisszumos, törékeny egyensúly iránya erősödik.",
            "shadow_network": "🌑 A zárt és illegális utak történeti nyomása erősödik.",
        }
        return (labels[ranked[0]],)

    @staticmethod
    async def _safe_rows(conn, sql: str, params: tuple[object, ...]) -> list:
        try:
            cur = await conn.execute(sql, params)
            return list(await cur.fetchall())
        except Exception:
            # Some history repositories initialize after the World loop. Missing
            # optional projections contribute zero; they never block a Chapter.
            return []

    async def ending_weights(self, guild_id: int, *, ensure: bool = True) -> ChapterEndingWeightSnapshot | None:
        """Aggregate committed histories without creating Chapter XP or settlement state."""
        run = await (self.ensure_active(guild_id) if ensure else self.current(guild_id))
        if run is None:
            return None
        additions = {key: 0 for key in self._ENDING_ORDER}
        counts: dict[str, int] = {}
        since = run.started_at
        async with aiosqlite.connect(self.db.path) as conn:
            causality = await self._safe_rows(
                conn,
                """SELECT domain,COUNT(*),COALESCE(SUM(units),0) FROM rp_world_causality_signals
                   WHERE guild_id=? AND occurred_at>=? GROUP BY domain""",
                (int(guild_id), since),
            )
            counts["causality"] = sum(int(row[1]) for row in causality)
            for domain, row_count, units in causality:
                domain_key = str(domain).lower()
                target = "shadow_network" if domain_key in {"crime", "heist", "illegal"} else (
                    "shared_recovery" if domain_key in {"community", "career", "business", "social"} else "fractured_balance"
                )
                additions[target] += min(12, int(row_count) + max(0, int(units)) // 10)

            scenarios = await self._safe_rows(
                conn,
                """SELECT domain,COUNT(*) FROM player_scenario_history
                   WHERE guild_id=? AND completed_at IS NOT NULL AND completed_at>=? GROUP BY domain""",
                (int(guild_id), since),
            )
            counts["scenario"] = sum(int(row[1]) for row in scenarios)
            for domain, row_count in scenarios:
                target = "shadow_network" if str(domain).lower() in {"crime", "heist", "illegal"} else (
                    "shared_recovery" if str(domain).lower() in {"business", "career", "social", "community"} else "fractured_balance"
                )
                additions[target] += min(8, int(row_count))

            projects = await self._safe_rows(
                conn,
                """SELECT result_status,branch_key,career_units,business_units FROM rp_world_community_project_outcomes
                   WHERE guild_id=? AND recorded_at>=?""",
                (int(guild_id), since),
            )
            counts["community_project"] = len(projects)
            for status, branch, career_units, business_units in projects:
                if str(status).lower() in {"completed", "success"}:
                    additions["shared_recovery"] += min(10, 4 + (int(career_units) + int(business_units)) // 10)
                elif str(status).lower() in {"expired", "failed"}:
                    additions["fractured_balance"] += 5
                if any(token in str(branch).lower() for token in ("crime", "shadow", "black")):
                    additions["shadow_network"] += 4

            contracts = await self._safe_rows(
                conn,
                """SELECT o.objective_type,COUNT(*) FROM contracts c
                   JOIN contract_objectives o ON o.contract_id=c.contract_id AND o.guild_id=c.guild_id
                   WHERE c.guild_id=? AND c.status='settled' AND c.resolved_at>=? AND o.status='completed'
                   GROUP BY o.objective_type""",
                (int(guild_id), since),
            )
            counts["contract"] = sum(int(row[1]) for row in contracts)
            for objective_type, row_count in contracts:
                token = str(objective_type).lower()
                target = "shadow_network" if any(item in token for item in ("crime", "heist", "illegal")) else (
                    "shared_recovery" if any(item in token for item in ("business", "career", "delivery", "community", "social")) else "fractured_balance"
                )
                additions[target] += min(8, int(row_count))

            memories = await self._safe_rows(
                conn,
                """SELECT category,COUNT(*) FROM character_memory_state
                   WHERE guild_id=? AND active=1 AND occurred_at>=? GROUP BY category""",
                (int(guild_id), since),
            )
            counts["memory"] = sum(int(row[1]) for row in memories)
            for category, row_count in memories:
                token = str(category).lower()
                target = "shadow_network" if token in {"crime", "heist", "illegal", "rival"} else (
                    "shared_recovery" if token in {"career", "business", "social", "favor", "community"} else "fractured_balance"
                )
                additions[target] += min(6, int(row_count))

        weights = self._normalize_weights(additions)
        return ChapterEndingWeightSnapshot(
            chapter_run_id=run.chapter_run_id,
            weights=weights,
            source_counts=tuple((key, counts.get(key, 0)) for key in ("causality", "scenario", "community_project", "contract", "memory")),
            narratives=self._narratives(weights),
        )

    @staticmethod
    def _from_row(row) -> ChapterRunSnapshot:
        try:
            resolution = json.loads(str(row[11] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            resolution = {}
        if not isinstance(resolution, dict):
            resolution = {}
        return ChapterRunSnapshot(
            chapter_run_id=int(row[0]), guild_id=int(row[1]), chapter_key=str(row[2]),
            status=str(row[3]), current_stage_key=str(row[4]), started_at=str(row[5]),
            stage_started_at=str(row[6]), deadline_at=str(row[7]), updated_at=str(row[8]),
            resolved_at=None if row[9] is None else str(row[9]),
            ending_key=None if row[10] is None else str(row[10]),
            resolution_snapshot=resolution,
        )

    @staticmethod
    def _select_sql(where: str) -> str:
        return f"""SELECT chapter_run_id,guild_id,chapter_key,status,current_stage_key,
                          started_at,stage_started_at,deadline_at,updated_at,resolved_at,
                          ending_key,resolution_snapshot_json
                   FROM rp_world_chapters WHERE {where}"""

    @staticmethod
    def _stage_for(definition: cfg.ChapterDefinition, started_at: str, at: datetime) -> cfg.ChapterStageDefinition:
        started = _parse(started_at) or at
        elapsed_days = max(0, int((at - started).total_seconds() // 86400))
        selected = definition.stages[0]
        for stage in definition.stages:
            if elapsed_days >= int(stage.start_day):
                selected = stage
        return selected

    async def current(self, guild_id: int) -> ChapterRunSnapshot | None:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                self._select_sql("guild_id=? AND status IN ('active','awaiting_resolution') ORDER BY chapter_run_id DESC LIMIT 1"),
                (int(guild_id),),
            )
            row = await cur.fetchone()
        return None if row is None else self._from_row(row)

    async def history(self, guild_id: int, *, limit: int = 10) -> list[ChapterRunSnapshot]:
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                self._select_sql("guild_id=? ORDER BY chapter_run_id DESC LIMIT ?"),
                (int(guild_id), max(1, min(50, int(limit)))),
            )
            rows = await cur.fetchall()
        return [self._from_row(row) for row in rows]

    async def start(self, guild_id: int, chapter_key: str = cfg.PILOT_CHAPTER_KEY, *, at: datetime | None = None) -> ChapterRunSnapshot:
        definition = cfg.CHAPTER_BY_KEY.get(str(chapter_key))
        if definition is None:
            raise ValueError("Ismeretlen Yoru Chapter.")
        existing = await self.current(guild_id)
        if existing is not None:
            return existing
        now_dt = at or _utcnow()
        now = _iso(now_dt)
        deadline = _iso(now_dt + timedelta(days=max(14, min(28, int(definition.duration_days)))))
        stage = definition.stages[0]
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await conn.execute(
                    "SELECT chapter_run_id FROM rp_world_chapters WHERE guild_id=? AND status IN ('active','awaiting_resolution') LIMIT 1",
                    (int(guild_id),),
                )
                row = await cur.fetchone()
                if row is not None:
                    chapter_run_id = int(row[0])
                    await conn.rollback()
                else:
                    cur = await conn.execute(
                        """INSERT INTO rp_world_chapters(
                               guild_id,chapter_key,status,active_slot,current_stage_key,started_at,stage_started_at,
                               deadline_at,updated_at,resolved_at,ending_key,resolution_snapshot_json
                           ) VALUES(?,?,'active',1,?,?,?,?,?,NULL,NULL,'{}')""",
                        (int(guild_id), definition.key, stage.key, now, now, deadline, now),
                    )
                    chapter_run_id = int(cur.lastrowid or 0)
                    await conn.commit()
            except Exception:
                await conn.rollback()
                raced = await self.current(guild_id)
                if raced is not None:
                    return raced
                raise
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(self._select_sql("chapter_run_id=?"), (chapter_run_id,))
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("A Yoru Chapter indítás után nem olvasható vissza.")
        return self._from_row(row)

    async def refresh(self, guild_id: int, *, at: datetime | None = None) -> ChapterRunSnapshot | None:
        current = await self.current(guild_id)
        if current is None or current.status not in {"active", "awaiting_resolution"}:
            return current
        if current.awaiting_resolution:
            return current
        now_dt = at or _utcnow()
        deadline = _parse(current.deadline_at)
        if deadline is not None and now_dt >= deadline:
            async with aiosqlite.connect(self.db.path) as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    final_stage = current.definition.stages[-1]
                    await conn.execute(
                        """UPDATE rp_world_chapters
                           SET status='awaiting_resolution',current_stage_key=?,stage_started_at=?,updated_at=?
                           WHERE chapter_run_id=? AND status='active'""",
                        (final_stage.key, _iso(now_dt), _iso(now_dt), int(current.chapter_run_id)),
                    )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
            return await self.current(guild_id)

        definition = current.definition
        next_stage = self._stage_for(definition, current.started_at, now_dt)
        if next_stage.key == current.current_stage_key:
            return current
        now = _iso(now_dt)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await conn.execute(
                    """UPDATE rp_world_chapters
                       SET current_stage_key=?,stage_started_at=?,updated_at=?
                       WHERE chapter_run_id=? AND status='active'""",
                    (next_stage.key, now, now, int(current.chapter_run_id)),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        return await self.current(guild_id)

    async def ensure_active(self, guild_id: int) -> ChapterRunSnapshot:
        current = await self.current(guild_id)
        if current is None:
            current = await self.start(guild_id)
        refreshed = await self.refresh(guild_id)
        return refreshed or current

    async def context(self, guild_id: int, *, ensure: bool = True) -> ChapterContextSnapshot | None:
        run = await (self.ensure_active(guild_id) if ensure else self.current(guild_id))
        if run is None:
            return None
        world_snapshot = await self.world.ensure_current(guild_id)
        project = await self.world.current_community_project(guild_id)
        causality = await self.world.causality_snapshot(guild_id)
        story = world_snapshot.story
        project_title = project.definition.name if project is not None else None
        project_progress_band = project.progress_band if project is not None else None
        bands = tuple(sorted({item.pressure_band for item in causality.signals if item.pressure_band != "quiet"}))
        ending_projection = await self.ending_weights(guild_id, ensure=False)
        return ChapterContextSnapshot(
            run=run,
            world_cycle_id=world_snapshot.cycle_id,
            national_title=world_snapshot.national.title,
            world_story_title=story.title if story is not None else None,
            community_project_title=project_title,
            community_project_progress_band=project_progress_band,
            causality_bands=bands,
            ending_pressures=ending_projection.narratives if ending_projection is not None else (),
        )
