from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
PREFIX = (ROOT / "app" / "cogs" / "prefix.py").read_text(encoding="utf-8")
EXTRAS = (ROOT / "app" / "cogs" / "extras_prefix.py").read_text(encoding="utf-8")
COMMUNITY = (ROOT / "app" / "cogs" / "community.py").read_text(encoding="utf-8")
ACCESS = (ROOT / "app" / "cogs" / "access_utils.py").read_text(encoding="utf-8")


class UnifiedWrongChannelContractTests(unittest.TestCase):
    def test_core_economy_uses_private_cleanup(self) -> None:
        self.assertIn("handle_wrong_economy_channel(ctx, self.economy)", PREFIX)
        self.assertIn('await self.economy.guild_settings.require_feature(ctx.guild.id, feature)', PREFIX)
        self.assertIn("await self.economy.guild_settings.require_channel(", PREFIX)

    def test_extras_economy_uses_private_cleanup(self) -> None:
        self.assertIn("handle_wrong_economy_channel(ctx, self.economy)", EXTRAS)
        self.assertIn('await self.economy.guild_settings.require_feature(ctx.guild.id, feature)', EXTRAS)

    def test_blackmarket_prefix_uses_private_cleanup(self) -> None:
        self.assertGreaterEqual(COMMUNITY.count("handle_wrong_economy_channel(ctx, self.economy)"), 2)

    def test_top_remains_public(self) -> None:
        self.assertIn("if self._is_public_top(ctx):", PREFIX)
        self.assertIn('ctx.command.name == "top"', PREFIX)

    def test_generic_helper_supports_both_economy_and_gambling(self) -> None:
        self.assertIn("async def handle_wrong_economy_channel", ACCESS)
        self.assertIn('kind: str = "economy"', ACCESS)
        self.assertIn('kind="gambling"', ACCESS)
        self.assertIn("await ctx.message.delete()", ACCESS)
        self.assertIn("await ctx.author.send", ACCESS)

    def test_release_version(self) -> None:
        version = tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")))
        self.assertGreaterEqual(version, (3, 12, 4))


class EconomyCleanupBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_work_style_cleanup_deletes_and_dms(self) -> None:
        import importlib.util
        import sys
        from types import ModuleType

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
            spec = importlib.util.spec_from_file_location("access_utils_v3124_runtime", ROOT / "app" / "cogs" / "access_utils.py")
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)

            guild = SimpleNamespace(id=123)
            guild.get_channel = lambda _id: None
            message = SimpleNamespace(delete=AsyncMock())
            author = SimpleNamespace(send=AsyncMock(), mention="<@42>")
            ctx = SimpleNamespace(guild=guild, message=message, author=author, send=AsyncMock())
            settings = SimpleNamespace(
                get_economy_channel_ids=AsyncMock(return_value=[111]),
                get_economy_category_ids=AsyncMock(return_value=[222]),
            )
            economy = SimpleNamespace(guild_settings=settings)

            await module.handle_wrong_economy_channel(ctx, economy)

            message.delete.assert_awaited_once()
            author.send.assert_awaited_once()
            ctx.send.assert_not_awaited()
            sent_embed = author.send.await_args.kwargs["embed"]
            self.assertIn("economy parancsokat", sent_embed["message"])
        finally:
            for name, old in old_modules.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old


if __name__ == "__main__":
    unittest.main()
