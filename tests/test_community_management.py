from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMUNITY = (ROOT / "app" / "cogs" / "community.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
DATABASE = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class CommunityManagementRegressionTests(unittest.TestCase):
    def test_community_slash_commands_are_grouped(self) -> None:
        self.assertIn('class CommunityCog(commands.GroupCog, group_name="community"', COMMUNITY)
        for command in ["suggest", "poll", "giveaway", "reroll", "afk", "sticky", "stickyoff"]:
            self.assertIn(f'@app_commands.command(name="{command}"', COMMUNITY)

    def test_persistent_runtime_survives_restart(self) -> None:
        self.assertIn("await self._restore_community_runtime()", COMMUNITY)
        self.assertIn("self.bot.add_view(SuggestionView", COMMUNITY)
        self.assertIn("self.bot.add_view(PollView", COMMUNITY)
        self.assertIn("GiveawayView(self", COMMUNITY)
        self.assertGreaterEqual(COMMUNITY.count("await self.bot.wait_until_ready()"), 2)

    def test_interaction_rows_are_guild_scoped(self) -> None:
        # Component IDs may outlive a restart. DB-backed callbacks must still reject
        # a row from another guild instead of trusting only the custom_id.
        self.assertGreaterEqual(COMMUNITY.count('interaction.guild_id != row["guild_id"]'), 4)
        self.assertIn('row is None or row["guild_id"] != guild_id', COMMUNITY)

    def test_community_settings_are_interactive_and_paged(self) -> None:
        self.assertIn("class CommunitySettingsView(OwnedView):", SETTINGS)
        self.assertIn("class CommunitySuggestionChannelSelect(PagedGuildChannelSelect):", SETTINGS)
        self.assertIn("class CommunityStarboardChannelSelect(PagedGuildChannelSelect):", SETTINGS)
        self.assertIn('label="Community"', SETTINGS)

    def test_persistent_database_tables_exist(self) -> None:
        for table in [
            "community_suggestions",
            "community_suggestion_votes",
            "community_polls",
            "community_poll_votes",
            "community_giveaways",
            "community_giveaway_entries",
            "community_afk",
            "community_starboard_posts",
            "community_stickies",
        ]:
            with self.subTest(table=table):
                self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", DATABASE)

    def test_staff_prefix_commands_stay_hidden(self) -> None:
        for command in ["giveaway", "gw", "giveawayreroll", "sticky", "stickyoff", "unsticky"]:
            with self.subTest(command=command):
                self.assertIn(f'"{command}"', MAIN)


if __name__ == "__main__":
    unittest.main()
