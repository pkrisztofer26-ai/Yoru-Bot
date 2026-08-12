from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V3112ReleaseTests(unittest.TestCase):
    def test_version_is_3112_or_later(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        parts = tuple(int(part) for part in version.split("."))
        self.assertGreaterEqual(parts, (3, 11, 2))

    def test_ship_is_generated_image_card_without_old_verdict_clutter(self) -> None:
        text = (ROOT / "app" / "cogs" / "fun.py").read_text(encoding="utf-8")
        self.assertIn("from PIL import Image, ImageDraw, ImageFont", text)
        self.assertIn("display_avatar.replace", text)
        self.assertIn("display_avatar", text)
        self.assertIn("discord.File", text)
        self.assertIn("_build_ship_card", text)
        self.assertIn("_ship_score", text)
        self.assertIn("COMPATIBILITY", text)
        self.assertNotIn("_ship_verdict", text)
        self.assertNotIn("Ship meter", text)
        self.assertNotIn("Yoru szerint", text)
        self.assertNotIn("🔮 Ítélet", text)
        self.assertNotIn("Power couple", text)

    def test_ship_has_dependency_and_fallback(self) -> None:
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        fun = (ROOT / "app" / "cogs" / "fun.py").read_text(encoding="utf-8")
        self.assertIn("pillow==12.3.0", req)
        self.assertIn("_fallback_ship_embed", fun)
        self.assertIn("except Exception", fun)

    def test_spotify_uses_safe_resolver_chain_for_current_release(self) -> None:
        text = (ROOT / "app" / "cogs" / "music.py").read_text(encoding="utf-8")
        version = tuple(int(part) for part in (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))
        self.assertIn("_run_spotdl", text)
        self.assertIn("_spotdl_save_items", text)
        self.assertIn("_spotdl_source_urls", text)
        self.assertIn("fallback_query", text)
        self.assertIn("ytsearch1:", text)
        if version < (3, 17, 2):
            self.assertIn('args.append("--preload")', text)
            self.assertIn('item.get("download_url")', text)
        else:
            # v3.17.2 removes playlist-wide audio preloading and resolves only
            # the currently playing Spotify track.
            start = text.index("    async def _extract_spotify_tracks")
            end = text.index("    async def _resolve_input", start)
            body = text[start:end]
            self.assertIn("preload=False", body)
            self.assertNotIn("preload=True", body)
            self.assertNotIn('item.get("download_url")', body)
            self.assertIn("Spotify • Fast Resolver", body)
        if version < (3, 17, 1):
            self.assertNotIn("lavalink", text.lower())
            self.assertNotIn("lavasrc", text.lower())
        else:
            self.assertIn("wavelink", text.lower())
            self.assertIn("_extract_lavalink_tracks", text)

    def test_activity_system_release_boundary(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if version == "3.11.2":
            self.assertFalse((ROOT / "app" / "cogs" / "activity.py").exists())
            self.assertFalse((ROOT / "app" / "services" / "activity.py").exists())
        else:
            self.assertTrue((ROOT / "app" / "cogs" / "activity.py").exists())
            self.assertTrue((ROOT / "app" / "services" / "activity.py").exists())

    def test_changelog_is_packaged(self) -> None:
        changelog = (ROOT / "CHANGELOG_3.11.2.txt").read_text(encoding="utf-8")
        self.assertIn("Ship Image Card", changelog)
        self.assertIn("spotDL", changelog)
        self.assertIn("Activity System is NOT included", changelog)


if __name__ == "__main__":
    unittest.main()
