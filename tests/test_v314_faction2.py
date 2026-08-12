from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from app.database import Database
from app.services.statistics import StatisticsService
from app.services.crew import CrewService
from app.services.faction import FactionService


class Faction2BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db", 100_000_000)
        await self.db.initialize()
        self.stats = StatisticsService(self.db)
        self.crew = CrewService(self.db, self.stats)
        self.factions = FactionService(self.db, self.stats, self.crew)
        await self.db.ensure_user(1, 10)
        await self.db.ensure_user(1, 20)
        self.alpha = await self.crew.create(1, 10, "Alpha")
        self.beta = await self.crew.create(1, 20, "Beta")

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_stat_listener_awards_faction_xp(self) -> None:
        before = await self.factions.progress(1, self.alpha.crew.crew_id)
        await self.stats.increment(1, 10, "work.count")
        after = await self.factions.progress(1, self.alpha.crew.crew_id)
        self.assertGreater(after.xp, before.xp)
        member = await self.factions.member_progress(1, self.alpha.crew.crew_id, 10)
        self.assertGreater(member["contribution_xp"], 0)

    async def test_shared_daily_weekly_objectives_and_reward(self) -> None:
        daily, weekly = await self.factions.objectives(1, self.alpha.crew.crew_id)
        self.assertEqual(len(daily), 3)
        self.assertEqual(len(weekly), 3)
        target = daily[0]
        crew_before = await self.crew.get_crew(1, self.alpha.crew.crew_id)
        await self.factions.record_event(
            1, 10, target["stat"], target["target"],
            membership=await self.crew.get_membership(1, 10),
        )
        daily_after, _ = await self.factions.objectives(1, self.alpha.crew.crew_id)
        completed = next(row for row in daily_after if row["slot"] == target["slot"])
        self.assertTrue(completed["completed"])
        crew_after = await self.crew.get_crew(1, self.alpha.crew.crew_id)
        self.assertGreater(crew_after.bank, crew_before.bank)

    async def test_perk_tree_and_treasury_bonus(self) -> None:
        await self.factions._apply_xp(1, self.alpha.crew.crew_id, 10, 100_000)
        progress = await self.factions.progress(1, self.alpha.crew.crew_id)
        self.assertGreater(progress.perk_points_available, 0)
        rank = await self.factions.buy_perk(1, 10, "treasury")
        self.assertEqual(rank, 1)
        self.assertAlmostEqual(await self.factions.income_bonus(1, self.alpha.crew.crew_id), 0.005)

    async def test_custom_internal_rank_grants_real_permission(self) -> None:
        await self.db.ensure_user(1, 30)
        await self.crew.invite(1, 10, 30)
        await self.crew.accept(1, 30)
        rank = await self.factions.create_custom_rank(1, 10, "Pénztáros", ["bank_withdraw", "invite"])
        await self.factions.assign_custom_rank(1, 10, 30, rank["rank_id"])
        self.assertTrue(await self.factions.has_permission(1, 30, "bank_withdraw"))
        await self.crew.deposit(1, 10, 1_000_000)
        wallet, bank, _ = await self.crew.withdraw(1, 30, 100_000)
        self.assertGreater(wallet, 0)
        self.assertGreaterEqual(bank, 0)

    async def test_objective_based_faction_war_resolves(self) -> None:
        war = await self.factions.create_war(1, 10, self.beta.crew.crew_id)
        self.assertEqual(war["status"], "pending")
        war = await self.factions.accept_war(1, 20)
        self.assertEqual(war["status"], "active")
        await self.factions.record_event(
            1, 10, str(war["stat"]), int(war["target"]),
            membership=await self.crew.get_membership(1, 10),
        )
        resolved = await self.factions.get_war(1, int(war["war_id"]))
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(int(resolved["winner_crew_id"]), self.alpha.crew.crew_id)


class Faction2SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ui = (ROOT / "app" / "crew_ui.py").read_text(encoding="utf-8")
        cls.settings = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        cls.service = (ROOT / "app" / "services" / "faction.py").read_text(encoding="utf-8")
        cls.stats = (ROOT / "app" / "services" / "statistics.py").read_text(encoding="utf-8")

    def test_player_ui_is_interaction_first(self) -> None:
        for token in (
            "class CrewView", "FactionCreateModal", "FactionDepositModal", "FactionRanksView",
            '"Célok"', '"Perkek"', '"Tagok"', '"Wars"', "discord.ui.UserSelect",
        ):
            self.assertIn(token, self.ui)

    def test_settings_has_faction_admin_panel(self) -> None:
        self.assertIn('label="Frakció"', self.settings)
        self.assertIn('self.cog.bot.get_cog("CrewCog")', self.settings)
        for token in ("FactionSettingsView", "FactionSettingsModal", "XP tuning", "Célok ON/OFF", "Wars ON/OFF"):
            self.assertIn(token, self.ui)

    def test_shared_objectives_perks_ranks_and_wars_exist(self) -> None:
        for token in (
            "ensure_objectives", "buy_perk", "create_custom_rank", "assign_custom_rank",
            "create_war", "accept_war", "_record_war_event", "crew_wars",
        ):
            self.assertIn(token, self.service if token != "crew_wars" else (ROOT / "app" / "database.py").read_text(encoding="utf-8"))

    def test_statistics_listener_is_centralized(self) -> None:
        self.assertIn("register_listener", self.stats)
        self.assertIn("_notify_listeners", self.stats)
        self.assertIn("self.stats.register_listener(self.on_stat_change)", self.service)

    def test_native_invite_select_uses_real_subclass_callback(self) -> None:
        self.assertIn("class FactionInviteUserSelect(discord.ui.UserSelect)", self.ui)
        self.assertIn("self.add_item(FactionInviteUserSelect(self))", self.ui)
        self.assertNotIn("select.callback = native_invite", self.ui)

    def test_core_faction_messages_use_frakcio_name(self) -> None:
        crew_cog = (ROOT / "app" / "cogs" / "crew.py").read_text(encoding="utf-8")
        crew_service = (ROOT / "app" / "services" / "crew.py").read_text(encoding="utf-8")
        for old in ("Crew Bank", "Crew Officer", "Crew Member", "A Crew neve", "Nem vagy Crew tagja"):
            self.assertNotIn(old, crew_cog + crew_service)

    def test_version_is_at_least_3140(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 14, 0))


if __name__ == "__main__":
    unittest.main()
