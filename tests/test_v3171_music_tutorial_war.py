from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V3171MusicTutorialWarTests(unittest.TestCase):
    def test_release_metadata(self) -> None:
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertGreaterEqual(version, (3, 17, 1))
        changelog = (ROOT / "CHANGELOG_3.17.1.txt").read_text(encoding="utf-8")
        self.assertIn("Lavalink", changelog)
        self.assertIn("Tutorial", changelog)
        self.assertIn("Frakció", changelog)

    def test_music_backend_dependencies_match_release(self) -> None:
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertIn("import wavelink", music)  # optional backwards-compatible import
        self.assertIn("async def _extract_lavalink_tracks", music)
        self.assertIn("_run_spotdl", music)
        self.assertIn("_spotdl_save_items", music)
        self.assertIn("_extract_stream_url", music)
        if version < (3, 17, 2):
            self.assertIn("wavelink==3.5.2", req)
            self.assertIn("Spotify • LavaSrc", music)
        else:
            self.assertNotIn("wavelink==3.5.2", req)
            self.assertIn("Spotify • Fast Resolver", music)

    def test_music_backend_order_matches_release(self) -> None:
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        start = music.index("    async def _resolve_input")
        end = music.index("    async def _extract_stream_url", start)
        body = music[start:end]
        if version < (3, 17, 2):
            self.assertLess(body.index("self._lavalink_ready()"), body.index("SPOTIFY_RE.search(query)"))
            self.assertLess(body.index("_extract_lavalink_tracks"), body.index("_extract_spotify_tracks"))
        else:
            # Python-only fast Spotify path is primary from v3.17.2. Lavalink
            # remains optional for backwards compatibility/non-Spotify input.
            self.assertLess(body.index("SPOTIFY_RE.search(query)"), body.index("self._lavalink_ready()"))
            self.assertLess(body.index("_extract_spotify_tracks"), body.index("_extract_lavalink_tracks"))

    def test_lavalink_template_pins_lavasrc_and_youtube_source(self) -> None:
        yml = (ROOT / "lavalink" / "application.yml.example").read_text(encoding="utf-8")
        self.assertIn("lavasrc-plugin:4.8.3", yml)
        self.assertIn("youtube-plugin:1.18.1", yml)
        self.assertRegex(yml, r"(?m)^\s*youtube:\s*false\s*$")
        self.assertRegex(yml, r"(?m)^\s*spotify:\s*true\s*$")
        self.assertIn('ytsearch:"%ISRC%"', yml)
        self.assertIn("ytmsearch:%QUERY%", yml)
        self.assertIn("SPOTIFY_CLIENT_ID", yml)
        self.assertIn("SPOTIFY_CLIENT_SECRET", yml)

    def test_war_challenge_dms_target_owner(self) -> None:
        crew = (ROOT / "app" / "crew_ui.py").read_text(encoding="utf-8")
        self.assertIn("async def _notify_war_challenge", crew)
        self.assertIn("target.owner_id", crew)
        self.assertIn("await user.send(embed=embed)", crew)
        create_pos = crew.index("war_created = await self.bot.factions.create_war")
        notify_pos = crew.index("await self._notify_war_challenge(interaction, war_created)", create_pos)
        self.assertGreater(notify_pos, create_pos)

    def test_tutorial_forum_is_admin_only_syncable_and_maintained(self) -> None:
        tut = (ROOT / "app" / "cogs" / "tutorial.py").read_text(encoding="utf-8")
        self.assertIn("guild.create_forum", tut)
        self.assertIn("forum.create_thread", tut)
        self.assertIn("TUTORIAL_POSTS_KEY", tut)
        self.assertIn("@commands.has_guild_permissions(administrator=True)", tut)
        self.assertIn("maintain_tutorial_forums", tut)
        self.assertGreaterEqual(tut.count("TutorialSection("), 15)
        self.assertIn("auto_archive_duration=10080", tut)

    def test_tutorial_is_in_settings_and_admin_prefix_guard(self) -> None:
        settings = (ROOT / "app" / "cogs" / "settings.py").read_text(encoding="utf-8")
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertIn('@discord.ui.button(label="Tutorial"', settings)
        if version < (3, 17, 2):
            self.assertIn("Wavelink", settings)
        else:
            self.assertIn("spotDL Fast Resolver", settings)
        self.assertIn("TutorialCog(self, self.database)", main)
        self.assertRegex(main, r'"tutorial"\s*,')
        self.assertRegex(main, r'"tutorialsync"\s*,')
        self.assertRegex(main, r'"tutsync"\s*,')

    def test_env_example_has_lavalink_but_no_real_secrets(self) -> None:
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("LAVALINK_URI=", env)
        self.assertIn("LAVALINK_PASSWORD=CHANGE_ME_LAVALINK_PASSWORD", env)
        self.assertIn("SPOTIFY_CLIENT_ID=", env)
        self.assertIn("SPOTIFY_CLIENT_SECRET=", env)


if __name__ == "__main__":
    unittest.main()
