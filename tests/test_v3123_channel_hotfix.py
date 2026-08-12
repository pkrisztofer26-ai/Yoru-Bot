from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
PREFIX = (ROOT / "app" / "cogs" / "prefix.py").read_text(encoding="utf-8")
ECONOMY = (ROOT / "app" / "cogs" / "economy.py").read_text(encoding="utf-8")
ACCESS = (ROOT / "app" / "cogs" / "access_utils.py").read_text(encoding="utf-8")


class PublicLeaderboardTests(unittest.TestCase):
    def test_every_prefix_top_variant_bypasses_location_guard(self) -> None:
        self.assertIn("def _is_public_top", PREFIX)
        self.assertIn('ctx.command.name == "top"', PREFIX)
        self.assertIn("if self._is_public_top(ctx):", PREFIX)
        self.assertNotIn("_PUBLIC_ACTIVITY_TOP_INPUTS", PREFIX)
        self.assertNotIn("_is_public_activity_top", PREFIX)

    def test_slash_top_has_no_economy_location_guard(self) -> None:
        start = ECONOMY.index("async def _send_top")
        end = ECONOMY.index('@app_commands.command(name="top"', start)
        body = ECONOMY[start:end]
        self.assertNotIn("await self._guard(interaction)", body)
        self.assertNotIn("public_activity_categories", body)

    def test_release_version(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 12, 3))


class GamblingCleanupContractTests(unittest.TestCase):
    def test_cleanup_helper_keeps_delete_dm_and_short_fallback(self) -> None:
        self.assertIn("await ctx.message.delete()", ACCESS)
        self.assertIn("await ctx.author.send", ACCESS)
        self.assertIn("delete_after=8", ACCESS)
        self.assertIn("handle_wrong_gambling_channel", ACCESS)
        self.assertIn('kind="gambling"', ACCESS)


class GamblingCleanupBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_and_dm_are_actually_invoked(self) -> None:
        import importlib.util
        import sys
        from types import ModuleType

        # Load the real helper with tiny Discord/UI stubs so this regression test
        # stays runnable even in the packaging QA environment without discord.py.
        discord = ModuleType("discord")
        discord.Forbidden = type("Forbidden", (Exception,), {})
        discord.NotFound = type("NotFound", (Exception,), {})
        discord.HTTPException = type("HTTPException", (Exception,), {})
        discord.CategoryChannel = type("CategoryChannel", (), {})
        discord.abc = SimpleNamespace(GuildChannel=type("GuildChannel", (), {}))
        discord.AllowedMentions = lambda **kwargs: kwargs

        commands = ModuleType("discord.ext.commands")
        commands.Context = object
        ext = ModuleType("discord.ext")
        ext.commands = commands
        discord.ext = ext

        fake_ui = ModuleType("app.ui")
        fake_ui.error_embed = lambda author, message, title=None: {"author": author, "message": message, "title": title}

        old_modules = {name: sys.modules.get(name) for name in ["discord", "discord.ext", "discord.ext.commands", "app.ui"]}
        try:
            sys.modules["discord"] = discord
            sys.modules["discord.ext"] = ext
            sys.modules["discord.ext.commands"] = commands
            sys.modules["app.ui"] = fake_ui
            spec = importlib.util.spec_from_file_location("access_utils_test_runtime", ROOT / "app" / "cogs" / "access_utils.py")
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)

            guild = SimpleNamespace(id=123)
            guild.get_channel = lambda _id: None
            message = SimpleNamespace(delete=AsyncMock())
            author = SimpleNamespace(send=AsyncMock())
            ctx = SimpleNamespace(guild=guild, message=message, author=author, send=AsyncMock())
            settings = SimpleNamespace(
                get_economy_channel_ids=AsyncMock(return_value=[111]),
                get_economy_category_ids=AsyncMock(return_value=[222]),
            )
            economy = SimpleNamespace(guild_settings=settings)

            await module.handle_wrong_gambling_channel(ctx, economy)

            message.delete.assert_awaited_once()
            author.send.assert_awaited_once()
            ctx.send.assert_not_awaited()
        finally:
            for name, old in old_modules.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old


if __name__ == "__main__":
    unittest.main()
