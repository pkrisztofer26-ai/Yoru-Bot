from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVENTS = (ROOT / "app" / "cogs" / "events.py").read_text(encoding="utf-8")
MODERATION = (ROOT / "app" / "cogs" / "moderation.py").read_text(encoding="utf-8")


class PriorRegressionTests(unittest.TestCase):
    def test_treasure_chest_accepts_negative_wallet_users(self) -> None:
        self.assertIn('"safe_event", allow_negative=True', EVENTS)
        safe_section = EVENTS[EVENTS.index("async def _finish_safe"):EVENTS.index("async def _preview_bomb_entries")]
        self.assertNotIn("wallet >=", safe_section)
        self.assertNotIn("wallet <", safe_section)

    def test_deleted_attachments_still_cached_and_reuploaded(self) -> None:
        self.assertIn('"deleted_attachments"', MODERATION)
        self.assertIn("attachment.read()", MODERATION)
        self.assertIn("discord.File(io.BytesIO(attachment.data)", MODERATION)

    def test_external_discord_timeouts_are_still_logged(self) -> None:
        self.assertIn("async def on_member_update", MODERATION)
        self.assertIn("discord.AuditLogAction.member_update", MODERATION)
        self.assertIn("Némítás (Discord)", MODERATION)


if __name__ == "__main__":
    unittest.main()
