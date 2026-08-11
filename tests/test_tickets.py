from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TICKETS = (ROOT / "app" / "cogs" / "tickets.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class TicketRegressionTests(unittest.TestCase):
    def test_ticket_cog_is_loaded(self) -> None:
        self.assertIn("from app.cogs.tickets import TicketCog", MAIN)
        self.assertIn("await self.add_cog(TicketCog(self, self.database))", MAIN)

    def test_settings_ticket_button_is_enabled(self) -> None:
        self.assertIn('@discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.secondary, row=1)', SETTINGS)
        self.assertIn('self.cog.bot.get_cog("TicketCog")', SETTINGS)
        self.assertNotIn('label="Tickets", emoji="🎫", style=discord.ButtonStyle.secondary, disabled=True', SETTINGS)

    def test_ticket_schema_is_self_migrating(self) -> None:
        for table in ["ticket_panels", "ticket_panel_types", "tickets", "ticket_members"]:
            with self.subTest(table=table):
                self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", TICKETS)

    def test_public_and_control_views_are_restart_safe(self) -> None:
        self.assertIn("timeout=None", TICKETS)
        self.assertIn("self.bot.add_view(OpenTicketControlsView(self))", TICKETS)
        self.assertIn("self.bot.add_view(ClosedTicketControlsView(self))", TICKETS)
        self.assertIn("self.bot.add_view(TicketPanelView(self, panel), message_id=int(panel[\"message_id\"]))", TICKETS)
        for custom_id in [
            "yoru:ticket:create:",
            "yoru:ticket:claim",
            "yoru:ticket:add-user",
            "yoru:ticket:remove-user",
            "yoru:ticket:rename",
            "yoru:ticket:close",
            "yoru:ticket:reopen",
            "yoru:ticket:delete",
        ]:
            self.assertIn(custom_id, TICKETS)

    def test_ticket_category_allows_invites_and_links(self) -> None:
        self.assertIn('add_exemption(guild_id, "invite", "category", category_id)', TICKETS)
        self.assertIn('add_exemption(guild_id, "links", "category", category_id)', TICKETS)

    def test_private_channel_and_transcript_features_exist(self) -> None:
        self.assertIn("interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)", TICKETS)
        self.assertIn("channel.history(limit=None, oldest_first=True)", TICKETS)
        self.assertIn("TICKET_DM_TRANSCRIPT_KEY", TICKETS)
        self.assertIn("ClosedTicketControlsView", TICKETS)

    def test_ticket_action_race_protection_exists(self) -> None:
        self.assertIn("self._ticket_action_locks", TICKETS)
        self.assertIn("if lock.locked():", TICKETS)
        self.assertGreaterEqual(TICKETS.count("async with lock:"), 4)

    def test_no_new_top_level_slash_commands(self) -> None:
        self.assertNotIn("@app_commands.command", TICKETS)
        self.assertNotIn("@self.bot.tree.command", TICKETS)


if __name__ == "__main__":
    unittest.main()
