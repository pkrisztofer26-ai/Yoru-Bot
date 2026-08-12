from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

# The release test runner in this workspace intentionally does not install the
# project's third-party requirements. Provide a tiny sqlite3-backed aiosqlite
# compatibility shim only for these isolated DB tests when the real package is
# unavailable. Production still uses requirements.txt -> aiosqlite.
import importlib.util
import sqlite3
import sys
import types

if importlib.util.find_spec("aiosqlite") is None:
    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.rowcount = cursor.rowcount
            self.lastrowid = cursor.lastrowid
        async def fetchone(self):
            return self._cursor.fetchone()
        async def fetchall(self):
            return self._cursor.fetchall()

    class _Connection:
        def __init__(self, path):
            self._path = path
            self._conn = None
            self._row_factory = None
        @property
        def row_factory(self):
            return self._row_factory
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
        async def execute(self, sql, params=()):
            return _Cursor(self._conn.execute(sql, params))
        async def executemany(self, sql, seq):
            return _Cursor(self._conn.executemany(sql, seq))
        async def commit(self):
            self._conn.commit()
        async def rollback(self):
            self._conn.rollback()

    _module = types.ModuleType("aiosqlite")
    _module.Connection = _Connection
    _module.Row = sqlite3.Row
    _module.connect = lambda path: _Connection(path)
    sys.modules["aiosqlite"] = _module

from app import activity_config as cfg
from app.database import Database
from app.services.activity import ActivityService

ROOT = Path(__file__).resolve().parents[1]


class ActivityMathTests(unittest.TestCase):
    def test_curve_keeps_agreed_pacing_anchor(self) -> None:
        self.assertEqual(cfg.xp_for_level(40), 85_800)
        self.assertEqual(cfg.xp_for_level(100), 514_500)
        self.assertEqual(cfg.level_for_xp(85_799), 39)
        self.assertEqual(cfg.level_for_xp(85_800), 40)

    def test_milestone_levels_are_stable(self) -> None:
        self.assertEqual(cfg.ACTIVITY_MILESTONE_LEVELS, (5, 10, 15, 20, 30, 40, 50, 60, 75, 90, 110, 130, 150, 175, 200))


class ActivityDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "yoru.db"), 1000)
        await self.db.initialize()
        self.service = ActivityService(self.db)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_chat_antifarm_and_xp_cooldown(self) -> None:
        await self.service.set_chat_tuning(1, xp_min=16, xp_max=16, cooldown=60, min_interval=8)
        start = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)

        first = await self.service.record_message(1, 10, "Ez egy normalis uzenet", now=start)
        self.assertIsNotNone(first)
        self.assertTrue(first.counted)
        self.assertEqual(first.xp_awarded, 16)
        self.assertEqual(first.profile.message_count, 1)

        too_fast = await self.service.record_message(1, 10, "Masik normalis uzenet", now=start + timedelta(seconds=5))
        self.assertIsNotNone(too_fast)
        self.assertFalse(too_fast.counted)
        self.assertEqual(too_fast.profile.message_count, 1)

        duplicate = await self.service.record_message(1, 10, "Ez egy normalis uzenet", now=start + timedelta(seconds=10))
        self.assertIsNotNone(duplicate)
        self.assertFalse(duplicate.counted)
        self.assertEqual(duplicate.profile.message_count, 1)

        cooldown_message = await self.service.record_message(1, 10, "Teljesen mas szoveg", now=start + timedelta(seconds=20))
        self.assertTrue(cooldown_message.counted)
        self.assertEqual(cooldown_message.xp_awarded, 0)
        self.assertEqual(cooldown_message.profile.message_count, 2)

        second_xp = await self.service.record_message(1, 10, "Eltelt mar a cooldown rendesen", now=start + timedelta(seconds=61))
        self.assertTrue(second_xp.counted)
        self.assertEqual(second_xp.xp_awarded, 16)
        self.assertEqual(second_xp.profile.total_xp, 32)
        self.assertEqual(second_xp.profile.chat_xp, 32)
        self.assertEqual(second_xp.profile.message_count, 3)

    async def test_non_adjacent_duplicate_is_blocked(self) -> None:
        await self.service.set_chat_tuning(1, xp_min=10, xp_max=10, cooldown=10, min_interval=2)
        start = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)

        first = await self.service.record_message(1, 15, "Ugyanaz a tartalom", now=start)
        middle = await self.service.record_message(1, 15, "Teljesen mas tartalom", now=start + timedelta(seconds=10))
        duplicate = await self.service.record_message(1, 15, "Ugyanaz a tartalom", now=start + timedelta(seconds=20))

        self.assertTrue(first.counted)
        self.assertTrue(middle.counted)
        self.assertFalse(duplicate.counted)
        self.assertEqual(duplicate.profile.message_count, 2)

    async def test_prefix_commands_do_not_farm_activity(self) -> None:
        result = await self.service.record_message(1, 20, "!work")
        self.assertIsNone(result)
        profile = await self.service.profile(1, 20)
        self.assertEqual(profile.total_xp, 0)
        self.assertEqual(profile.message_count, 0)

    async def test_voice_xp_and_time_are_persistent(self) -> None:
        await self.service.set_voice_tuning(1, xp_per_minute=3)
        one = await self.service.record_voice_minute(1, 30)
        two = await self.service.record_voice_minute(1, 30)
        self.assertEqual(one.xp_awarded, 3)
        self.assertEqual(two.profile.total_xp, 6)
        self.assertEqual(two.profile.voice_xp, 6)
        self.assertEqual(two.profile.voice_seconds, 120)
        self.assertEqual(self.service.voice_time_text(3660), "1 óra 1 perc")

    async def test_activity_leaderboards_use_separate_table(self) -> None:
        await self.service.set_chat_tuning(1, xp_min=20, xp_max=20, cooldown=60, min_interval=8)
        base = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
        await self.service.record_message(1, 100, "Elso user activity message", now=base)
        await self.service.record_message(1, 200, "Masodik user activity message", now=base)
        await self.service.record_voice_minute(1, 200)
        rows = await self.db.leaderboard(1, "activity_xp", 10)
        self.assertEqual(rows[0][0], 200)
        self.assertGreater(rows[0][3], rows[1][3])
        voice = await self.db.leaderboard(1, "voice", 10)
        self.assertEqual(voice[0][0], 200)
        self.assertEqual(voice[0][3], 60)

    async def test_milestone_configuration_roundtrip(self) -> None:
        row = await self.service.set_milestone(1, 20, role_id=123456, role_name="Veteran", hourly_income=250_000)
        self.assertEqual(row["role_id"], 123456)
        rows = await self.service.get_milestones(1)
        selected = next(item for item in rows if item["level"] == 20)
        self.assertEqual(selected["role_name"], "Veteran")
        self.assertEqual(selected["hourly_income"], 250_000)

    async def test_default_hungarian_activity_ladder_is_persisted(self) -> None:
        rows = await self.service.get_milestones(77)
        self.assertEqual([row["role_name"] for row in rows], [
            "Csöves", "Pórnép", "Közmunkás", "Minimálbéres", "Melós",
            "Szakmunkás", "Maszekos", "Kft.-tulaj", "Vállalkozó",
            "Nagyvállalkozó", "Újgazdag", "Stróman", "Oligarcha",
            "Felső tízezer", "NER-elit",
        ])
        second_service = ActivityService(self.db)
        layout = await second_service.get_milestone_layout(77)
        self.assertEqual([int(row["level"]) for row in layout], list(cfg.ACTIVITY_MILESTONE_LEVELS))

    async def test_old_manual_role_mapping_migrates_by_name(self) -> None:
        await self.service.settings.set_list(88, cfg.ACTIVITY_MILESTONES_KEY, [
            {"level": 100, "role_id": 999001, "role_name": "Oligarcha", "hourly_income": 123_000},
        ])
        rows = await self.service.get_milestones(88)
        oligarcha = next(row for row in rows if row["role_name"] == "Oligarcha")
        self.assertEqual(oligarcha["level"], 150)
        self.assertEqual(oligarcha["role_id"], 999001)
        self.assertEqual(oligarcha["hourly_income"], 123_000)


class ActivitySourceRegressionTests(unittest.TestCase):
    def test_activity_adds_no_top_level_slash_command(self) -> None:
        source = (ROOT / "app" / "cogs" / "activity.py").read_text(encoding="utf-8")
        self.assertNotIn("@app_commands.command", source)
        self.assertNotIn("GroupCog", source)

    def test_activity_service_does_not_shadow_discord_client_activity(self) -> None:
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        profile = (ROOT / "app" / "profile_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("self.activity = ActivityService", main)
        self.assertIn("self.activity_service = ActivityService", main)
        self.assertIn("ActivityCog(self, self.database, self.activity_service)", main)
        self.assertNotIn("bot.activity.", profile)
        self.assertIn("bot.activity_service.", profile)

    def test_message_tracking_runs_after_automod_gate(self) -> None:
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        automod = source.index("if await automod.check_message(message):")
        activity = source.index('activity_cog = self.get_cog("ActivityCog")')
        process = source.index("await self.process_commands(message)")
        self.assertLess(automod, activity)
        self.assertLess(activity, process)

    def test_role_upgrade_is_add_before_remove(self) -> None:
        source = (ROOT / "app" / "cogs" / "activity.py").read_text(encoding="utf-8")
        self.assertLess(source.index("await member.add_roles"), source.index("await member.remove_roles"))
        self.assertIn("can_manage_role", source)

    def test_settings_and_profile_integration_exist(self) -> None:
        settings = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        profile = (ROOT / "app" / "profile_ui.py").read_text(encoding="utf-8")
        self.assertIn('label="Activity"', settings)
        self.assertIn('self.bot.get_cog("ActivityCog")', settings)
        self.assertIn("build_activity_embed", profile)
        self.assertIn("yoru_profile_activity", profile)

    def test_voice_loop_requires_consecutive_qualifying_ticks(self) -> None:
        source = (ROOT / "app" / "cogs" / "activity.py").read_text(encoding="utf-8")
        self.assertIn("self._voice_primed", source)
        self.assertIn("if key not in self._voice_primed", source)
        self.assertIn("on_voice_state_update", source)
        prime_check = source.index("if key not in self._voice_primed")
        award = source.index("await self.service.record_voice_minute", prime_check)
        self.assertLess(prime_check, award)

    def test_top_choice_budget_remains_under_discord_limit(self) -> None:
        source = (ROOT / "app" / "cogs" / "economy.py").read_text(encoding="utf-8")
        start = source.index("@app_commands.choices")
        end = source.index("async def top", start)
        choice_block = source[start:end]
        self.assertLessEqual(choice_block.count("app_commands.Choice("), 25)

    def test_release_files(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 12, 1))
        self.assertTrue((ROOT / "CHANGELOG_3.12.0.txt").exists())
        self.assertTrue((ROOT / "CHANGELOG_3.12.1.txt").exists())
        if (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "3.12.2":
            self.assertTrue((ROOT / "CHANGELOG_3.12.2.txt").exists())
        self.assertIn("Activity System", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
