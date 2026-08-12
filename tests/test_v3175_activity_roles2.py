from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import importlib.util
import sqlite3
import sys
import types

if "aiosqlite" not in sys.modules:
    try:
        _spec = importlib.util.find_spec("aiosqlite")
    except ValueError:
        _spec = None
    if _spec is None:
        class _Cursor:
            def __init__(self, cursor):
                self._cursor = cursor
                self.rowcount = cursor.rowcount
                self.lastrowid = cursor.lastrowid
            async def fetchone(self): return self._cursor.fetchone()
            async def fetchall(self): return self._cursor.fetchall()

        class _Connection:
            def __init__(self, path):
                self._path = path
                self._conn = None
                self._row_factory = None
            @property
            def row_factory(self): return self._row_factory
            @row_factory.setter
            def row_factory(self, value):
                self._row_factory = value
                if self._conn is not None:
                    self._conn.row_factory = value
            async def __aenter__(self):
                self._conn = sqlite3.connect(self._path)
                if self._row_factory is not None:
                    self._conn.row_factory = self._row_factory
                return self
            async def __aexit__(self, exc_type, exc, tb):
                if self._conn is not None:
                    self._conn.close()
            async def execute(self, sql, params=()): return _Cursor(self._conn.execute(sql, params))
            async def executemany(self, sql, seq): return _Cursor(self._conn.executemany(sql, seq))
            async def commit(self): self._conn.commit()
            async def rollback(self): self._conn.rollback()

        _module = types.ModuleType("aiosqlite")
        _module.Connection = _Connection
        _module.Row = sqlite3.Row
        _module.connect = lambda path: _Connection(path)
        sys.modules["aiosqlite"] = _module

from app import activity_config as cfg
from app.database import Database
from app.services.activity import ActivityService

ROOT = Path(__file__).resolve().parents[1]


class ActivityRoles2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "yoru.db"), 1000)
        await self.db.initialize()
        self.service = ActivityService(self.db)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_dynamic_add_edit_delete_survives_restart(self) -> None:
        await self.service.get_milestones(1)
        added = await self.service.add_milestone(1, 225, "Nagytőkés", hourly_income=2_500_000)
        self.assertEqual(added["level"], 225)
        self.assertEqual(added["role_name"], "Nagytőkés")

        edited = await self.service.update_milestone(
            1, 225, new_level=230, role_name="Tőkés", hourly_income=3_000_000,
        )
        self.assertEqual(edited["level"], 230)
        self.assertEqual(edited["role_name"], "Tőkés")

        second = ActivityService(self.db)
        rows = await second.get_milestones(1)
        self.assertTrue(any(int(row["level"]) == 230 and row["role_name"] == "Tőkés" for row in rows))
        self.assertFalse(any(int(row["level"]) == 225 for row in rows))

        await second.delete_milestone(1, 230)
        third = ActivityService(self.db)
        rows = await third.get_milestones(1)
        self.assertFalse(any(int(row["level"]) == 230 for row in rows))

    async def test_more_than_25_milestones_are_preserved(self) -> None:
        for row in list(await self.service.get_milestones(2)):
            await self.service.delete_milestone(2, int(row["level"]))
        for index in range(1, 31):
            await self.service.add_milestone(2, index, f"Rank {index}")
        rows = await ActivityService(self.db).get_milestones(2)
        self.assertEqual(len(rows), 30)
        self.assertEqual([int(row["level"]) for row in rows], list(range(1, 31)))

    async def test_intentionally_empty_dynamic_layout_stays_empty(self) -> None:
        for row in list(await self.service.get_milestones(3)):
            await self.service.delete_milestone(3, int(row["level"]))
        self.assertEqual(await self.service.get_milestones(3), [])
        self.assertEqual(await ActivityService(self.db).get_milestones(3), [])

    async def test_discord_snapshot_overwrites_db_appearance(self) -> None:
        await self.service.set_milestone(4, 50, role_id=555001, role_name="Maszekos")
        synced = await self.service.sync_role_snapshot(
            4,
            555001,
            role_name="Maszekos 💸",
            role_color=0x123456,
            role_hoist=True,
            role_mentionable=True,
        )
        self.assertIsNotNone(synced)
        self.assertEqual(synced["role_name"], "Maszekos 💸")
        self.assertEqual(synced["role_color"], 0x123456)
        self.assertTrue(synced["role_hoist"])
        self.assertTrue(synced["role_mentionable"])
        rows = await ActivityService(self.db).get_milestones(4)
        row = next(item for item in rows if int(item["level"]) == 50)
        self.assertEqual(row["role_name"], "Maszekos 💸")

    async def test_deleted_bound_role_keeps_snapshot_but_clears_id(self) -> None:
        await self.service.set_milestone(
            5, 75, role_id=777001, role_name="Vállalkozó",
            role_color=0xABCDEF, role_hoist=True, role_mentionable=False,
        )
        row = await self.service.mark_role_deleted(5, 777001)
        self.assertIsNotNone(row)
        self.assertIsNone(row["role_id"])
        self.assertEqual(row["role_color"], 0xABCDEF)
        self.assertEqual(row["role_name"], "Vállalkozó")


class ActivityRoles2SourceTests(unittest.TestCase):
    def test_dynamic_manager_and_discord_to_db_sync_exist(self) -> None:
        activity = (ROOT / "app" / "cogs" / "activity.py").read_text(encoding="utf-8")
        service = (ROOT / "app" / "services" / "activity.py").read_text(encoding="utf-8")
        for token in (
            'label="Új milestone"',
            'label="Szerkesztés"',
            'label="Milestone törlése"',
            "MILESTONE_LEVEL_PAGE_SIZE = 23",
            "on_guild_role_update",
            "on_guild_role_delete",
            "capture_role_snapshot",
        ):
            self.assertIn(token, activity)
        for token in ("add_milestone", "update_milestone", "delete_milestone", "sync_role_snapshot", "mark_role_deleted"):
            self.assertIn(token, service)
        self.assertNotIn("return layout[:25]", service)

    def test_existing_discord_role_is_not_force_renamed_by_reconcile(self) -> None:
        activity = (ROOT / "app" / "cogs" / "activity.py").read_text(encoding="utf-8")
        self.assertNotIn("role.edit(name=desired_name", activity)
        self.assertIn("Discord -> DB", (ROOT / "app" / "services" / "activity.py").read_text(encoding="utf-8"))

    def test_default_ladder_remains_first_install_template_only(self) -> None:
        cfg_source = (ROOT / "app" / "activity_config.py").read_text(encoding="utf-8")
        self.assertIn("ACTIVITY_MILESTONE_LAYOUT_VERSION = 3", cfg_source)
        self.assertIn("ACTIVITY_MAX_MILESTONES = 200", cfg_source)
        self.assertEqual(len(cfg.ACTIVITY_DEFAULT_MILESTONES), 15)

    def test_release_metadata(self) -> None:
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertGreaterEqual(version, (3, 17, 5))
        changelog = (ROOT / "CHANGELOG_3.17.5.txt").read_text(encoding="utf-8")
        self.assertIn("Activity Roles 2.0", changelog)
        self.assertIn("DISCORD ↔ DB", changelog)


if __name__ == "__main__":
    unittest.main()
