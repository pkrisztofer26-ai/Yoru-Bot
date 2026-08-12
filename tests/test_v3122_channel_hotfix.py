from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PREFIX = (ROOT / "app" / "cogs" / "prefix.py").read_text(encoding="utf-8")
EXTRAS_PREFIX = (ROOT / "app" / "cogs" / "extras_prefix.py").read_text(encoding="utf-8")
ECONOMY = (ROOT / "app" / "cogs" / "economy.py").read_text(encoding="utf-8")
ACCESS = (ROOT / "app" / "cogs" / "access_utils.py").read_text(encoding="utf-8")


class ChannelHotfixTests(unittest.TestCase):
    def test_activity_top_prefix_is_public(self) -> None:
        # v3.12.3 broadened the v3.12.2 exception: every leaderboard is public.
        self.assertIn("def _is_public_top", PREFIX)
        self.assertIn("if self._is_public_top(ctx):", PREFIX)

    def test_activity_top_slash_skips_economy_location_guard(self) -> None:
        start = ECONOMY.index("async def _send_top")
        end = ECONOMY.index('@app_commands.command(name="top"', start)
        self.assertNotIn("await self._guard(interaction)", ECONOMY[start:end])

    def test_wrong_prefix_gambling_commands_are_deleted_and_dm_notified(self) -> None:
        self.assertIn("await ctx.message.delete()", ACCESS)
        self.assertIn("await ctx.author.send", ACCESS)
        self.assertIn("handle_wrong_gambling_channel", ACCESS)
        self.assertIn('kind="gambling"', ACCESS)
        self.assertIn("handle_wrong_gambling_channel(ctx, self.economy)", PREFIX)
        self.assertIn("handle_wrong_gambling_channel(ctx, self.economy)", EXTRAS_PREFIX)

    def test_feature_disabled_is_not_treated_as_wrong_channel(self) -> None:
        for source in [PREFIX, EXTRAS_PREFIX]:
            feature_check = source.index('require_feature(ctx.guild.id, "gambling")')
            channel_check = source.index("require_channel(", feature_check)
            private_cleanup = source.index("handle_wrong_gambling_channel", channel_check)
            self.assertLess(feature_check, channel_check)
            self.assertLess(channel_check, private_cleanup)

    def test_release_version(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (3, 12, 2))


if __name__ == "__main__":
    unittest.main()
