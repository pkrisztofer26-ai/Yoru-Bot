from __future__ import annotations

from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V3173TutorialOverhaulTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tutorial = (ROOT / "app" / "cogs" / "tutorial.py").read_text(encoding="utf-8")
        self.cfg = (ROOT / "app" / "tutorial_config.py").read_text(encoding="utf-8")

    def test_release_metadata(self) -> None:
        version = tuple(int(p) for p in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertGreaterEqual(version, (3, 17, 3))
        changelog = (ROOT / "CHANGELOG_3.17.3.txt").read_text(encoding="utf-8")
        self.assertIn("Tutorial 2.0", changelog)
        self.assertIn("!tutorial admin", changelog)

    def test_player_and_admin_content_are_separate(self) -> None:
        self.assertIn("PLAYER_SECTIONS", self.tutorial)
        self.assertIn("ADMIN_SECTIONS", self.tutorial)
        player_start = self.tutorial.index("PLAYER_SECTIONS")
        admin_start = self.tutorial.index("ADMIN_SECTIONS")
        player_block = self.tutorial[player_start:admin_start]
        self.assertIn('"start", "🌙", "Első lépések', player_block)
        self.assertIn('"finish", "🏁", "Merre tovább?', player_block)
        self.assertNotIn('"moderation"', player_block)
        self.assertNotIn('"admin"', player_block)
        self.assertGreaterEqual(player_block.count("TutorialSection("), 15)

    def test_admin_command_mode_and_private_forum_exist(self) -> None:
        self.assertIn('normalized in {"admin", "staff", "mod", "moderator"}', self.tutorial)
        self.assertIn("sync_admin_tutorial", self.tutorial)
        self.assertIn("ADMIN_TUTORIAL_FORUM_NAME", self.cfg)
        self.assertIn("ADMIN_TUTORIAL_POSTS_KEY", self.cfg)
        self.assertIn("view_channel=not admin", self.tutorial)

    def test_ordering_is_numbered_and_reverse_created(self) -> None:
        self.assertIn("reversed(tuple(enumerate(sections, start=1)))", self.tutorial)
        self.assertIn('name=f"{index:02d}・{section.emoji} {section.title}"', self.tutorial)
        self.assertIn("TUTORIAL_SCHEMA_VERSION = 2", self.cfg)
        self.assertIn("_delete_managed_threads", self.tutorial)

    def test_settings_has_separate_sync_buttons(self) -> None:
        self.assertIn('label="Player sync"', self.tutorial)
        self.assertIn('label="Admin sync"', self.tutorial)
        self.assertIn("Player Forum", self.tutorial)
        self.assertIn("Admin Forum", self.tutorial)

    def test_source_parses(self) -> None:
        ast.parse(self.tutorial)
        ast.parse(self.cfg)


if __name__ == "__main__":
    unittest.main()
