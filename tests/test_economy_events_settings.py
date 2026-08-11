from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EconomyEventsSettingsTests(unittest.TestCase):
    def test_settings_buttons_are_enabled_and_wired(self) -> None:
        text = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('label="Economy"', text)
        self.assertIn('label="Events"', text)
        self.assertIn('get_cog("EconomyEventsSettingsCog")', text)
        self.assertNotIn('label="Economy", emoji="💰", style=discord.ButtonStyle.secondary, disabled=True', text)
        self.assertNotIn('label="Events", emoji="🎁", style=discord.ButtonStyle.secondary, disabled=True', text)

    def test_main_loads_settings_cog(self) -> None:
        text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("await self.add_cog(EconomyEventsSettingsCog(self, self.database))", text)

    def test_backend_uses_existing_guild_state_no_schema_migration(self) -> None:
        text = (ROOT / "app" / "services" / "economy_events_settings.py").read_text(encoding="utf-8")
        self.assertIn("ServerSettingsService", text)
        self.assertIn("get_guild_state", text)
        self.assertIn("set_guild_state", text)
        self.assertNotIn("CREATE TABLE", text.upper())
        self.assertIn('"economy_enabled"', text)
        self.assertIn('"events_auto_enabled"', text)

    def test_blank_bool_state_falls_back_to_existing_defaults(self) -> None:
        text = (ROOT / "app" / "services" / "server_settings.py").read_text(encoding="utf-8")
        self.assertIn("if raw is None or not raw.strip():", text)

    def test_economy_guards_cover_slash_and_prefix(self) -> None:
        slash = (ROOT / "app" / "cogs" / "economy.py").read_text(encoding="utf-8")
        prefix = (ROOT / "app" / "cogs" / "prefix.py").read_text(encoding="utf-8")
        extras_prefix = (ROOT / "app" / "cogs" / "extras_prefix.py").read_text(encoding="utf-8")
        gambling = (ROOT / "app" / "cogs" / "gambling.py").read_text(encoding="utf-8")
        self.assertIn("require_access", slash)
        self.assertIn("cog_before_invoke", prefix)
        self.assertIn("_ECONOMY_GUARDS", prefix)
        self.assertIn("cog_before_invoke", extras_prefix)
        self.assertIn("require_channel", gambling)

    def test_event_runtime_is_per_guild_and_reschedulable(self) -> None:
        text = (ROOT / "app" / "cogs" / "events.py").read_text(encoding="utf-8")
        self.assertIn("get_runtime_config", text)
        self.assertIn("_next_auto_event_at", text)
        self.assertIn("reschedule_auto_event", text)
        self.assertIn("for guild in list(self.bot.guilds)", text)
        self.assertIn("config.safe_enabled", text)
        self.assertIn("config.bomb_enabled", text)
        self.assertIn("config.manual_enabled", text)

    def test_manual_events_are_manage_server_staff_commands(self) -> None:
        event_text = (ROOT / "app" / "cogs" / "events.py").read_text(encoding="utf-8")
        main_text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        prefix_text = (ROOT / "app" / "cogs" / "prefix.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(event_text.count("@app_commands.checks.has_permissions(manage_guild=True)"), 2)
        self.assertIn('"kincseslada": "manage_guild"', main_text)
        self.assertIn('"hirtelenhalal": "manage_guild"', main_text)
        self.assertGreaterEqual(prefix_text.count("@commands.has_permissions(manage_guild=True)"), 2)

    def test_selectors_use_existing_23_item_pagination(self) -> None:
        text = (ROOT / "app" / "cogs" / "economy_events_settings.py").read_text(encoding="utf-8")
        self.assertIn("PagedGuildChannelSelect", text)
        settings = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        self.assertIn("CHANNEL_SELECT_PAGE_SIZE = 23", settings)

    def test_no_new_slash_commands_in_settings_extension(self) -> None:
        path = ROOT / "app" / "cogs" / "economy_events_settings.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        decorators = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators.extend(ast.unparse(d) for d in node.decorator_list)
        self.assertFalse(any("app_commands.command" in d for d in decorators))

    def test_custom_currency_context_used_by_money_formatter(self) -> None:
        ui = (ROOT / "app" / "ui.py").read_text(encoding="utf-8")
        service = (ROOT / "app" / "services" / "economy_events_settings.py").read_text(encoding="utf-8")
        self.assertIn("ContextVar", ui)
        self.assertIn("set_currency_symbol", service)
        self.assertIn("prepare_currency", service)


if __name__ == "__main__":
    unittest.main()
