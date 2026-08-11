from __future__ import annotations

import ast
from pathlib import Path
import unittest

from app import music_config as musiccfg

ROOT = Path(__file__).resolve().parents[1]


class MusicFunTests(unittest.TestCase):
    def test_music_limits_are_safe(self) -> None:
        self.assertGreaterEqual(musiccfg.MUSIC_DEFAULT_VOLUME, musiccfg.MUSIC_MIN_VOLUME)
        self.assertLessEqual(musiccfg.MUSIC_DEFAULT_VOLUME, musiccfg.MUSIC_MAX_VOLUME)
        self.assertGreaterEqual(musiccfg.MUSIC_DEFAULT_MAX_QUEUE, musiccfg.MUSIC_MIN_QUEUE)
        self.assertLessEqual(musiccfg.MUSIC_DEFAULT_MAX_QUEUE, musiccfg.MUSIC_MAX_QUEUE)

    def test_fun_helpers_present(self) -> None:
        text = (ROOT / "app" / "cogs" / "fun.py").read_text(encoding="utf-8")
        self.assertIn("def _stable_percent", text)
        self.assertIn("def _mock_text", text)
        self.assertIn('group_name="fun"', text)

    def test_settings_buttons_are_enabled_and_wired(self) -> None:
        text = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('label="Music"', text)
        self.assertIn('get_cog("MusicCog")', text)
        self.assertIn('label="Fun"', text)
        self.assertIn('get_cog("FunCog")', text)
        self.assertNotIn('label="Music", emoji="🎵", style=discord.ButtonStyle.secondary, disabled=True', text)
        self.assertNotIn('label="Fun", emoji="🎉", style=discord.ButtonStyle.secondary, disabled=True', text)

    def test_main_loads_both_cogs(self) -> None:
        text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("await self.add_cog(MusicCog(self, self.database))", text)
        self.assertIn("await self.add_cog(FunCog(self, self.database))", text)

    def test_voice_dependencies_declared(self) -> None:
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertIn("discord.py[voice]==2.7.1", req)
        self.assertIn("yt-dlp", req)
        self.assertIn("spotdl==4.5.2", req)
        self.assertIn("pillow==12.3.0", req)
        self.assertIn("davey>=0.1.0", req)
        self.assertIn("pynacl>=1.5.0,<1.6", req)
        self.assertNotIn("pynacl==1.6.2", req)

    def test_music_sources_and_member_panel_present(self) -> None:
        text = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        self.assertIn("_extract_youtube_playlist", text)
        self.assertIn("_extract_spotify_tracks", text)
        self.assertIn('name="panel"', text)
        self.assertIn("class MusicPanelView", text)
        self.assertIn('custom_id="yoru:music:add"', text)
        self.assertIn("self.bot.add_view(MusicPanelView(self))", text)

    def test_music_panel_state_keys_exist(self) -> None:
        self.assertEqual(musiccfg.MUSIC_PANEL_CHANNEL_KEY, "music_panel_channel_id")
        self.assertEqual(musiccfg.MUSIC_PANEL_MESSAGE_KEY, "music_panel_message_id")
        self.assertLessEqual(musiccfg.MUSIC_MAX_PLAYLIST_ITEMS, musiccfg.MUSIC_MAX_QUEUE)

    def test_no_prefix_name_or_alias_collisions(self) -> None:
        seen: dict[str, str] = {}
        collisions: list[str] = []
        for path in sorted((ROOT / "app" / "cogs").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    target = dec.func
                    if not (
                        isinstance(target, ast.Attribute)
                        and target.attr == "command"
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "commands"
                    ):
                        continue
                    name = node.name
                    aliases: list[str] = []
                    for kw in dec.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            name = str(kw.value.value)
                        if kw.arg == "aliases" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            aliases = [str(item.value) for item in kw.value.elts if isinstance(item, ast.Constant)]
                    for token in [name, *aliases]:
                        key = token.casefold()
                        here = f"{path.name}:{node.name}"
                        if key in seen:
                            collisions.append(f"{key}: {seen[key]} / {here}")
                        else:
                            seen[key] = here
        self.assertEqual(collisions, [], "Prefix command collision(s): " + "; ".join(collisions))


if __name__ == "__main__":
    unittest.main()
