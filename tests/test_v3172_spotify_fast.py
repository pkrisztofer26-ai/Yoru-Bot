from __future__ import annotations

from pathlib import Path
import unittest

from app import music_config as musiccfg

ROOT = Path(__file__).resolve().parents[1]


class V3172SpotifyFastTests(unittest.TestCase):
    def test_release_metadata(self) -> None:
        version = tuple(int(p) for p in (ROOT / "VERSION").read_text().strip().split("."))
        self.assertGreaterEqual(version, (3, 17, 2))
        changelog = (ROOT / "CHANGELOG_3.17.2.txt").read_text(encoding="utf-8")
        self.assertIn("metadata-only", changelog)
        self.assertIn("just-in-time", changelog)
        self.assertIn("ISRC", changelog)

    def test_spotify_playlist_does_not_preload_or_resolve_every_source(self) -> None:
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        start = music.index("    async def _extract_spotify_tracks")
        end = music.index("    async def _resolve_input", start)
        body = music[start:end]
        self.assertIn("_spotdl_save_items(query, preload=False)", body)
        self.assertNotIn("preload=True", body)
        self.assertNotIn("_spotdl_source_urls(query", body)
        self.assertIn("Spotify • Fast Resolver", body)
        self.assertIn('item.get("isrc")', body)

    def test_source_resolution_is_jit_and_bounded(self) -> None:
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        start = music.index("    async def _extract_stream_url")
        end = music.index("    async def _send_channel", start)
        body = music[start:end]
        self.assertIn("_spotdl_source_urls", body)
        self.assertIn("MUSIC_SPOTIFY_SOURCE_TIMEOUT_SECONDS", body)
        self.assertIn("MUSIC_YTDLP_RESOLVE_TIMEOUT_SECONDS", body)
        self.assertIn("asyncio.wait_for", body)
        self.assertIn("_stream_url_cache", body)

    def test_spotdl_cache_enabled_and_retry_limited(self) -> None:
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        start = music.index("    async def _spotdl_save_items")
        end = music.index("    async def _spotdl_source_urls", start)
        body = music[start:end]
        self.assertNotIn('"--no-cache"', body)
        self.assertIn('"--max-retries"', body)
        self.assertIn("MUSIC_SPOTIFY_METADATA_THREADS", body)
        self.assertIn("_spotify_metadata_cache", body)

    def test_timeouts_are_short_enough_to_prevent_hour_long_hangs(self) -> None:
        self.assertLessEqual(musiccfg.MUSIC_SPOTIFY_METADATA_TIMEOUT_SECONDS, 30)
        self.assertLessEqual(musiccfg.MUSIC_SPOTIFY_PLAYLIST_TIMEOUT_SECONDS, 45)
        self.assertLessEqual(musiccfg.MUSIC_SPOTIFY_SOURCE_TIMEOUT_SECONDS, 12)
        self.assertLessEqual(musiccfg.MUSIC_YTDLP_RESOLVE_TIMEOUT_SECONDS, 20)

    def test_first_track_start_does_not_block_play_response(self) -> None:
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        start = music.index("    async def _enqueue_input")
        end = music.index("    def _queued_embed", start)
        body = music[start:end]
        self.assertIn("asyncio.create_task(self._start_track", body)
        self.assertNotIn("await self._start_track(guild, player, start_track)", body)

    def test_env_documents_python_only_default(self) -> None:
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("Python-only Fast Resolver", env)
        self.assertIn("LAVALINK_URI=", env)

    def test_tutorial_documents_fast_resolver_not_required_lavalink(self) -> None:
        tutorial = (ROOT / "app" / "cogs" / "tutorial.py").read_text(encoding="utf-8")
        self.assertIn("Python-only Fast Resolver", tutorial)
        self.assertIn("ISRC-first", tutorial)
        self.assertNotIn("Lavalink v4 + LavaSrc esetén", tutorial)

    def test_lavalink_is_not_required_on_python_host(self) -> None:
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        music = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        self.assertNotIn("wavelink==3.5.2", req)
        self.assertIn("Resolver cache ürítés", music)
        self.assertNotIn('label="Lavalink reconnect"', music)



if __name__ == "__main__":
    unittest.main()
