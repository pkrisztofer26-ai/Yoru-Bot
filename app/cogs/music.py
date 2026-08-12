from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import random
import re
import shutil
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.settings import OwnedView, PagedGuildChannelSelect, PagedGuildRoleSelect
from app.database import Database
from app import music_config as musiccfg
from app.services.server_settings import ServerSettingsService
from app.ui import BRAND, SUCCESS, base_embed, error_embed, player_embed

try:  # Optional at import time: missing deps must not stop the whole bot.
    import yt_dlp  # type: ignore
except ImportError:  # pragma: no cover - host environment
    yt_dlp = None

try:  # Optional at import time so a dependency issue never blocks the whole bot.
    import wavelink  # type: ignore
except ImportError:  # pragma: no cover - host environment
    wavelink = None

logger = logging.getLogger("yoru.music")


FFMPEG_EXECUTABLE = os.getenv("FFMPEG_EXECUTABLE", "ffmpeg").strip() or "ffmpeg"
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn -loglevel warning"
SPOTIFY_RE = re.compile(r"(?:https?://open\.spotify\.com/(?:intl-[^/]+/)?(?:track|album|playlist)/|spotify:(?:track|album|playlist):)", re.I)
YOUTUBE_PLAYLIST_RE = re.compile(r"(?:youtube\.com|youtu\.be).*(?:[?&]list=)", re.I)


@dataclass(slots=True)
class Track:
    # query is the fallback lookup. When Lavalink is active, raw Lavalink track data is cached below.
    query: str
    title: str
    webpage_url: str
    duration: int | None
    requester_id: int
    source: str = "YouTube"
    thumbnail: str | None = None
    fallback_query: str | None = None
    lavalink_data: dict[str, Any] | None = None
    isrc: str | None = None


@dataclass
class GuildPlayer:
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    volume: float = 0.75
    loop_current: bool = False
    skip_current: bool = False
    stop_requested: bool = False
    last_text_channel_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    idle_task: asyncio.Task | None = None


def _format_duration(seconds: int | None) -> str:
    if not seconds or seconds < 0:
        return "LIVE / ?"
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _truncate(text: str, length: int) -> str:
    text = str(text)
    return text if len(text) <= length else text[: max(0, length - 1)] + "…"


def _thumbnail_from_info(data: dict[str, Any]) -> str | None:
    thumb = data.get("thumbnail")
    if isinstance(thumb, str) and thumb.startswith("http"):
        return thumb
    thumbs = data.get("thumbnails")
    if isinstance(thumbs, list):
        for item in reversed(thumbs):
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                return str(item["url"])
    return None


def _spotify_artists(item: dict[str, Any]) -> list[str]:
    raw = item.get("artists")
    if isinstance(raw, list):
        values: list[str] = []
        for artist in raw:
            if isinstance(artist, str) and artist.strip():
                values.append(artist.strip())
            elif isinstance(artist, dict) and artist.get("name"):
                values.append(str(artist["name"]).strip())
        if values:
            return values
    raw_artist = item.get("artist") or item.get("album_artist")
    if isinstance(raw_artist, str) and raw_artist.strip():
        return [raw_artist.strip()]
    return []


class MusicCog(commands.GroupCog, group_name="music", group_description="Yoru zenelejátszó és queue kezelés."):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.settings = ServerSettingsService(db)
        self.players: dict[int, GuildPlayer] = {}
        self._lavalink_node = None
        self._lavalink_error: str | None = None
        self._lavalink_connect_lock = asyncio.Lock()
        # v3.17.2: Python-only Spotify fast path. Metadata is cached and audio
        # source resolution happens only when a track is about to play. This
        # prevents a 50-100 song playlist from resolving 50-100 audio sources
        # before the command can return.
        self._spotify_metadata_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._stream_url_cache: dict[str, tuple[float, str]] = {}
        self._spotify_source_semaphore = asyncio.Semaphore(musiccfg.MUSIC_SPOTIFY_SOURCE_CONCURRENCY)

    async def cog_load(self) -> None:
        # One global persistent view handles all published music panels after restarts.
        self.bot.add_view(MusicPanelView(self))
        await self.connect_lavalink()

    async def cog_unload(self) -> None:
        for player in self.players.values():
            if player.idle_task and not player.idle_task.done():
                player.idle_task.cancel()
        for voice in list(self.bot.voice_clients):
            try:
                await self._disconnect_voice(voice, force=True)
            except Exception:
                pass
        if self._lavalink_node is not None:
            try:
                await self._lavalink_node.close(eject=True)
            except Exception:
                pass
            self._lavalink_node = None

    def _lavalink_env(self) -> tuple[str, str, str]:
        uri = os.getenv("LAVALINK_URI", "").strip()
        password = os.getenv("LAVALINK_PASSWORD", "").strip()
        identifier = os.getenv("LAVALINK_IDENTIFIER", "yoru-main").strip() or "yoru-main"
        return uri, password, identifier

    def _lavalink_ready(self) -> bool:
        return wavelink is not None and self._lavalink_node is not None

    async def connect_lavalink(self, *, force: bool = False) -> bool:
        """Connect the optional Lavalink v4 node. Failure degrades to the legacy backend."""
        async with self._lavalink_connect_lock:
            if self._lavalink_ready() and not force:
                return True
            uri, password, identifier = self._lavalink_env()
            if wavelink is None:
                self._lavalink_error = "A wavelink dependency nincs telepítve."
                return False
            if not uri or not password:
                self._lavalink_error = "LAVALINK_URI / LAVALINK_PASSWORD nincs beállítva."
                return False
            if force and self._lavalink_node is not None:
                try:
                    await self._lavalink_node.close(eject=True)
                except Exception:
                    pass
                self._lavalink_node = None
            try:
                node = wavelink.Node(
                    identifier=identifier,
                    uri=uri,
                    password=password,
                    retries=1,
                    resume_timeout=120,
                    inactive_player_timeout=None,
                )
                await asyncio.wait_for(
                    wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=100),
                    timeout=15.0,
                )
            except Exception as exc:
                self._lavalink_node = None
                self._lavalink_error = _truncate(str(exc), 300) or exc.__class__.__name__
                logger.warning("Lavalink connection unavailable: %s", self._lavalink_error)
                return False
            self._lavalink_node = node
            self._lavalink_error = None
            logger.info("Lavalink connected: %s", uri)
            return True

    def lavalink_status_text(self) -> str:
        uri, password, _identifier = self._lavalink_env()
        if self._lavalink_ready():
            return f"✅ Lavalink + LavaSrc • `{uri}`"
        if not uri or not password:
            return "⚪ Nincs konfigurálva • legacy fallback aktív"
        return f"⚠️ Node offline • {_truncate(self._lavalink_error or 'kapcsolódási hiba', 160)}"

    def _is_lavalink_voice(self, voice: Any) -> bool:
        return wavelink is not None and isinstance(voice, wavelink.Player)

    def _voice_playing(self, voice: Any) -> bool:
        if voice is None:
            return False
        return bool(voice.playing) if self._is_lavalink_voice(voice) else bool(voice.is_playing())

    def _voice_paused(self, voice: Any) -> bool:
        if voice is None:
            return False
        return bool(voice.paused) if self._is_lavalink_voice(voice) else bool(voice.is_paused())

    def _voice_connected(self, voice: Any) -> bool:
        if voice is None:
            return False
        return bool(voice.connected) if self._is_lavalink_voice(voice) else bool(voice.is_connected())

    async def _pause_voice(self, voice: Any, paused: bool) -> None:
        if self._is_lavalink_voice(voice):
            await voice.pause(paused)
        elif paused:
            voice.pause()
        else:
            voice.resume()

    async def _skip_voice(self, voice: Any) -> None:
        if self._is_lavalink_voice(voice):
            await voice.skip(force=True)
        else:
            voice.stop()

    async def _disconnect_voice(self, voice: Any, *, force: bool = False) -> None:
        if self._is_lavalink_voice(voice):
            await voice.disconnect()
        else:
            await voice.disconnect(force=force)

    async def _set_voice_volume(self, voice: Any, percent: int) -> None:
        if self._is_lavalink_voice(voice):
            await voice.set_volume(percent)
        elif isinstance(getattr(voice, "source", None), discord.PCMVolumeTransformer):
            voice.source.volume = percent / 100

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, musiccfg.MUSIC_ENABLED_KEY, musiccfg.MUSIC_DEFAULT_ENABLED)

    async def get_default_volume(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, musiccfg.MUSIC_VOLUME_KEY)
        return max(musiccfg.MUSIC_MIN_VOLUME, min(musiccfg.MUSIC_MAX_VOLUME, value or musiccfg.MUSIC_DEFAULT_VOLUME))

    async def get_max_queue(self, guild_id: int) -> int:
        value = await self.settings.get_int(guild_id, musiccfg.MUSIC_MAX_QUEUE_KEY)
        return max(musiccfg.MUSIC_MIN_QUEUE, min(musiccfg.MUSIC_MAX_QUEUE, value or musiccfg.MUSIC_DEFAULT_MAX_QUEUE))

    async def home_status(self, guild: discord.Guild) -> str:
        enabled = await self.is_enabled(guild.id)
        if not enabled:
            return "🔴 Kikapcsolva"
        channel_id = await self.settings.get_int(guild.id, musiccfg.MUSIC_CHANNEL_KEY)
        channel = guild.get_channel(channel_id) if channel_id else None
        return f"🟢 {channel.mention}" if isinstance(channel, discord.abc.GuildChannel) else "🟢 Aktív"

    def _voice_runtime_problem(self) -> str | None:
        if self._lavalink_ready():
            return None
        if importlib.util.find_spec("nacl") is None:
            return "A hoston hiányzik a **PyNaCl** voice dependency. A friss `discord.py[voice]` requirements szükséges."
        if importlib.util.find_spec("davey") is None:
            return "A hoston hiányzik a **davey** voice dependency. A friss `discord.py[voice]` requirements szükséges."
        if yt_dlp is None:
            return "A hoston nincs telepítve a **yt-dlp** dependency."
        if shutil.which(FFMPEG_EXECUTABLE) is None:
            return f"A hoston nem található az **FFmpeg** (`{FFMPEG_EXECUTABLE}`)."
        return None

    def _spotify_available(self) -> bool:
        return self._lavalink_ready() or importlib.util.find_spec("spotdl") is not None

    def _runtime_problem(self) -> str | None:
        return self._voice_runtime_problem()

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.is_enabled(guild.id)
        volume = await self.get_default_volume(guild.id)
        max_queue = await self.get_max_queue(guild.id)
        channel_id = await self.settings.get_int(guild.id, musiccfg.MUSIC_CHANNEL_KEY)
        dj_role_id = await self.settings.get_int(guild.id, musiccfg.MUSIC_DJ_ROLE_KEY)
        channel = guild.get_channel(channel_id) if channel_id else None
        role = guild.get_role(dj_role_id) if dj_role_id else None
        runtime = self._runtime_problem()
        embed = base_embed(
            "🎵 Yoru • Music",
            "YouTube, YouTube playlist és Spotify track/album/playlist támogatás. Spotifyhoz a Python-only Fast Resolver metadata-cache + just-in-time audio feloldást használ.",
        )
        embed.add_field(name="Állapot", value="🟢 Bekapcsolva" if enabled else "🔴 Kikapcsolva", inline=True)
        embed.add_field(name="🔊 Alap hangerő", value=f"**{volume}%**", inline=True)
        embed.add_field(name="📋 Queue limit", value=f"**{max_queue}**", inline=True)
        embed.add_field(name="💬 Music csatorna", value=channel.mention if isinstance(channel, discord.abc.GuildChannel) else "Bármelyik", inline=True)
        embed.add_field(name="🎧 DJ rang", value=role.mention if role else "Nincs • bárki vezérelhet", inline=True)
        embed.add_field(name="🧰 Voice runtime", value=(f"⚠️ {runtime}" if runtime else "✅ discord voice + yt-dlp + FFmpeg"), inline=False)
        embed.add_field(name="⚡ Spotify backend", value=("✅ Python Fast Resolver • metadata cache • JIT source lookup" if importlib.util.find_spec("spotdl") else "❌ spotDL nincs telepítve"), inline=False)
        embed.add_field(
            name="🧠 Resolver cache",
            value=f"Spotify metadata: **{len(self._spotify_metadata_cache)}** • Stream URL: **{len(self._stream_url_cache)}**\nTimeout: track **{musiccfg.MUSIC_SPOTIFY_METADATA_TIMEOUT_SECONDS}s** • playlist **{musiccfg.MUSIC_SPOTIFY_PLAYLIST_TIMEOUT_SECONDS}s**",
            inline=False,
        )
        embed.set_footer(text="Yoru • Settings • Music")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, existing: "MusicSettingsView | None" = None) -> None:
        view = MusicSettingsView(
            self, owner_id, interaction.guild,
            enabled=await self.is_enabled(interaction.guild_id),
            channel_page=existing.channel_page if existing else 0,
            role_page=existing.role_page if existing else 0,
        )
        await interaction.response.edit_message(embed=await self.settings_embed(interaction.guild), view=view)

    async def back_to_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings_cog = self.bot.get_cog("SettingsCog")
        if settings_cog is None or not hasattr(settings_cog, "show_home"):
            return await interaction.response.send_message("❌ A Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, owner_id)

    async def _player(self, guild_id: int) -> GuildPlayer:
        player = self.players.get(guild_id)
        if player is None:
            player = GuildPlayer(volume=(await self.get_default_volume(guild_id)) / 100)
            self.players[guild_id] = player
        return player

    def _voice_client(self, guild: discord.Guild) -> Any | None:
        return guild.voice_client

    async def _channel_allowed(self, guild: discord.Guild, channel_id: int) -> tuple[bool, str | None]:
        configured = await self.settings.get_int(guild.id, musiccfg.MUSIC_CHANNEL_KEY)
        if not configured or configured == channel_id:
            return True, None
        channel = guild.get_channel(configured)
        target = channel.mention if isinstance(channel, discord.abc.GuildChannel) else "a beállított Music csatornában"
        return False, f"A Music parancsokat itt használd: {target}"

    async def _is_dj(self, member: discord.Member) -> bool:
        if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
            return True
        role_id = await self.settings.get_int(member.guild.id, musiccfg.MUSIC_DJ_ROLE_KEY)
        if role_id is None:
            return True
        return any(role.id == role_id for role in member.roles)

    async def _gate_interaction(self, interaction: discord.Interaction, *, control: bool = False, require_voice: bool = True) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Ez a parancs csak szerveren használható.", ephemeral=True)
            return False
        if not await self.is_enabled(interaction.guild.id):
            await interaction.response.send_message("❌ A **Music** modul ki van kapcsolva ezen a szerveren.", ephemeral=True)
            return False
        allowed, reason = await self._channel_allowed(interaction.guild, interaction.channel_id)
        if not allowed:
            await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
            return False
        if control and not await self._is_dj(interaction.user):
            await interaction.response.send_message("❌ Ehhez a beállított **DJ rang** vagy Manage Server jogosultság kell.", ephemeral=True)
            return False
        voice = self._voice_client(interaction.guild)
        member_channel = interaction.user.voice.channel if interaction.user.voice else None
        if require_voice and member_channel is None:
            await interaction.response.send_message("❌ Előbb lépj be egy voice csatornába.", ephemeral=True)
            return False
        if voice is not None and member_channel is not None and voice.channel.id != member_channel.id:
            await interaction.response.send_message(f"❌ Előbb lépj be ugyanabba a voice-ba, ahol Yoru van: {voice.channel.mention}", ephemeral=True)
            return False
        return True

    async def _gate_ctx(self, ctx: commands.Context, *, control: bool = False, require_voice: bool = True) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return False
        if not await self.is_enabled(ctx.guild.id):
            await ctx.send(embed=error_embed(ctx.author, "A **Music** modul ki van kapcsolva ezen a szerveren."))
            return False
        allowed, reason = await self._channel_allowed(ctx.guild, ctx.channel.id)
        if not allowed:
            await ctx.send(embed=error_embed(ctx.author, reason or "Rossz csatorna."))
            return False
        if control and not await self._is_dj(ctx.author):
            await ctx.send(embed=error_embed(ctx.author, "Ehhez a beállított **DJ rang** vagy Manage Server jogosultság kell."))
            return False
        voice = self._voice_client(ctx.guild)
        member_channel = ctx.author.voice.channel if ctx.author.voice else None
        if require_voice and member_channel is None:
            await ctx.send(embed=error_embed(ctx.author, "Előbb lépj be egy voice csatornába."))
            return False
        if voice is not None and member_channel is not None and voice.channel.id != member_channel.id:
            await ctx.send(embed=error_embed(ctx.author, f"Előbb lépj be ugyanabba a voice-ba, ahol Yoru van: {voice.channel.mention}"))
            return False
        return True

    async def _connect_for_member(self, guild: discord.Guild, member: discord.Member) -> Any:
        if member.voice is None or member.voice.channel is None:
            raise ValueError("Előbb lépj be egy voice csatornába.")
        voice = self._voice_client(guild)

        if self._lavalink_ready():
            if voice is not None and not self._is_lavalink_voice(voice):
                await self._disconnect_voice(voice, force=True)
                voice = None
            if voice is None:
                try:
                    voice = await member.voice.channel.connect(cls=wavelink.Player, self_deaf=True)
                except Exception as exc:
                    raise ValueError(f"Lavalink voice csatlakozási hiba: {_truncate(str(exc), 300)}") from exc
                await self._set_voice_volume(voice, await self.get_default_volume(guild.id))
            elif getattr(getattr(voice, "channel", None), "id", None) != member.voice.channel.id:
                await voice.move_to(member.voice.channel)
            return voice

        runtime = self._voice_runtime_problem()
        if runtime:
            raise ValueError(runtime)
        if voice is not None and self._is_lavalink_voice(voice):
            await self._disconnect_voice(voice, force=True)
            voice = None
        if voice is None:
            try:
                voice = await member.voice.channel.connect(self_deaf=True)
            except RuntimeError as exc:
                text = str(exc)
                if "davey" in text.lower():
                    raise ValueError("A hoston hiányzik a **davey** voice dependency. A `discord.py[voice]` requirements kell.") from exc
                if "nacl" in text.lower():
                    raise ValueError("A hoston hiányzik a **PyNaCl** voice dependency. A `discord.py[voice]` requirements kell.") from exc
                raise ValueError(f"Nem sikerült csatlakozni voice-ba: {text}") from exc
        elif voice.channel.id != member.voice.channel.id:
            await voice.move_to(member.voice.channel)
        return voice

    async def _extract_metadata(self, query: str, requester_id: int) -> Track:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp nincs telepítve")

        def work() -> dict[str, Any]:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "default_search": "ytsearch1",
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[union-attr]
                data = ydl.extract_info(query, download=False)
                if data is None:
                    raise ValueError("Nem találtam lejátszható találatot.")
                if "entries" in data:
                    entries = [entry for entry in (data.get("entries") or []) if entry]
                    if not entries:
                        raise ValueError("Nem találtam lejátszható találatot.")
                    data = entries[0]
                return dict(data)

        data = await asyncio.to_thread(work)
        title = str(data.get("title") or query)
        webpage = str(data.get("webpage_url") or data.get("original_url") or data.get("url") or query)
        duration_raw = data.get("duration")
        duration = int(duration_raw) if isinstance(duration_raw, (int, float)) else None
        return Track(
            query=webpage if webpage.startswith("http") else query,
            title=title,
            webpage_url=webpage,
            duration=duration,
            requester_id=requester_id,
            source="YouTube" if "youtu" in webpage.lower() else "Web",
            thumbnail=_thumbnail_from_info(data),
        )

    async def _extract_youtube_playlist(self, query: str, requester_id: int, limit: int) -> list[Track]:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp nincs telepítve")

        def work() -> dict[str, Any]:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": False,
                "extract_flat": "in_playlist",
                "playlistend": max(1, min(limit, musiccfg.MUSIC_MAX_PLAYLIST_ITEMS)),
            }
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[union-attr]
                data = ydl.extract_info(query, download=False)
                if not isinstance(data, dict):
                    raise ValueError("Nem sikerült betölteni a YouTube playlistet.")
                return data

        data = await asyncio.to_thread(work)
        entries = [entry for entry in (data.get("entries") or []) if isinstance(entry, dict)]
        tracks: list[Track] = []
        for entry in entries[:limit]:
            title = str(entry.get("title") or "Ismeretlen zene")
            url = str(entry.get("webpage_url") or entry.get("url") or "")
            video_id = str(entry.get("id") or "")
            if url and not url.startswith("http") and video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
            elif not url and video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
            if not url:
                continue
            duration_raw = entry.get("duration")
            duration = int(duration_raw) if isinstance(duration_raw, (int, float)) else None
            tracks.append(Track(url, title, url, duration, requester_id, "YouTube", _thumbnail_from_info(entry)))
        if not tracks:
            raise ValueError("A YouTube playlistben nem találtam betölthető videót.")
        return tracks

    async def _run_spotdl(self, *args: str, timeout: float | None = None) -> tuple[str, str]:
        """Run spotDL in an isolated subprocess with a hard timeout.

        A hung provider can therefore never block the Discord event loop for
        minutes. The subprocess is killed on timeout instead of leaving a
        resolver running indefinitely.
        """
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "spotdl",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        deadline = float(timeout or musiccfg.MUSIC_SPOTIFY_METADATA_TIMEOUT_SECONDS)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=deadline)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise ValueError(f"A Spotify feloldása túllépte a {round(deadline)} mp-es időkorlátot.")
        out_text = (stdout or b"").decode("utf-8", errors="replace").strip()
        err_text = (stderr or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            detail = err_text or out_text or f"spotDL exit code {proc.returncode}"
            raise ValueError(_truncate(detail, 500))
        return out_text, err_text

    def _cache_get(self, cache: dict[str, tuple[float, Any]], key: str, ttl: int) -> Any | None:
        cached = cache.get(key)
        if cached is None:
            return None
        created, value = cached
        if time.monotonic() - created > ttl:
            cache.pop(key, None)
            return None
        return value

    def _cache_put(self, cache: dict[str, tuple[float, Any]], key: str, value: Any) -> None:
        cache[key] = (time.monotonic(), value)
        # Avoid unbounded growth on long-running large servers.
        if len(cache) > musiccfg.MUSIC_RESOLVER_CACHE_MAX_ITEMS:
            oldest = min(cache, key=lambda item: cache[item][0])
            cache.pop(oldest, None)

    async def _spotdl_save_items(self, query: str, *, preload: bool = False) -> list[dict[str, Any]]:
        """Fetch Spotify metadata only.

        v3.17.2 deliberately does NOT preload playlist audio sources. Preload
        was the main cause of huge playlists taking tens of minutes because it
        searched an audio provider for every track before returning.
        """
        cached = self._cache_get(self._spotify_metadata_cache, query, musiccfg.MUSIC_SPOTIFY_METADATA_CACHE_SECONDS)
        if cached is not None:
            return [dict(item) for item in cached]

        with tempfile.TemporaryDirectory(prefix="yoru_spotify_") as temp_name:
            save_path = Path(temp_name) / "metadata.spotdl"
            args = [
                "save",
                query,
                "--save-file",
                str(save_path),
                "--headless",
                "--max-retries",
                "1",
                "--threads",
                str(musiccfg.MUSIC_SPOTIFY_METADATA_THREADS),
                "--log-level",
                "ERROR",
            ]
            # Kept only for backwards compatibility with older internal calls;
            # the fast resolver never requests preload=True.
            if preload:
                args.append("--preload")
            is_list = "/playlist/" in query.lower() or "/album/" in query.lower() or query.lower().startswith(("spotify:playlist:", "spotify:album:"))
            timeout = musiccfg.MUSIC_SPOTIFY_PLAYLIST_TIMEOUT_SECONDS if is_list else musiccfg.MUSIC_SPOTIFY_METADATA_TIMEOUT_SECONDS
            await self._run_spotdl(*args, timeout=timeout)
            if not save_path.exists():
                raise ValueError("A spotDL nem hozta létre a metadata fájlt.")
            try:
                raw = json.loads(save_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("A Spotify metadata válasza hibás volt.") from exc

        if isinstance(raw, dict):
            raw_items = raw.get("songs") or raw.get("tracks") or raw.get("items") or []
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        items = [item for item in raw_items if isinstance(item, dict)]
        if items:
            self._cache_put(self._spotify_metadata_cache, query, [dict(item) for item in items])
        return items

    async def _spotdl_source_urls(self, query: str, *, timeout: float | None = None) -> list[str]:
        """Resolve a single Spotify track's preferred audio provider just-in-time."""
        stdout, _stderr = await self._run_spotdl(
            "url",
            query,
            "--headless",
            "--max-retries",
            "1",
            "--threads",
            "1",
            "--audio",
            "youtube-music",
            "youtube",
            "--log-level",
            "ERROR",
            timeout=timeout or musiccfg.MUSIC_SPOTIFY_SOURCE_TIMEOUT_SECONDS,
        )
        urls: list[str] = []
        for line in stdout.splitlines():
            candidate = line.strip().strip('"').strip("'")
            if candidate.startswith(("http://", "https://")) and "open.spotify.com" not in candidate.lower():
                urls.append(candidate)
        return urls

    def _track_from_lavalink(self, playable: Any, requester_id: int, *, source_label: str, fallback_url: str) -> Track:
        title = str(getattr(playable, "title", None) or "Ismeretlen zene")
        uri = str(getattr(playable, "uri", None) or fallback_url)
        length = getattr(playable, "length", None)
        duration = int(length // 1000) if isinstance(length, (int, float)) and length > 0 else None
        artwork = getattr(playable, "artwork", None)
        raw = getattr(playable, "raw_data", None)
        return Track(
            query=uri or fallback_url,
            title=title,
            webpage_url=uri if uri.startswith("http") else fallback_url,
            duration=duration,
            requester_id=requester_id,
            source=source_label,
            thumbnail=str(artwork) if isinstance(artwork, str) and artwork.startswith("http") else None,
            lavalink_data=dict(raw) if isinstance(raw, dict) else None,
        )

    async def _extract_lavalink_tracks(self, query: str, requester_id: int, limit: int) -> tuple[list[Track], str]:
        if not self._lavalink_ready() or wavelink is None:
            raise ValueError("A Lavalink node nem elérhető.")
        is_url = query.startswith(("http://", "https://"))
        try:
            if is_url:
                result = await wavelink.Playable.search(query, node=self._lavalink_node)
            else:
                result = await wavelink.Playable.search(query, source="ytsearch", node=self._lavalink_node)
        except Exception as exc:
            raise ValueError(f"Lavalink keresési hiba: {_truncate(str(exc), 500)}") from exc
        if not result:
            raise ValueError("A Lavalink nem talált lejátszható zenét.")
        if isinstance(result, wavelink.Playlist):
            items = list(result.tracks)[: max(1, min(limit, musiccfg.MUSIC_MAX_PLAYLIST_ITEMS))]
        else:
            items = list(result)[: max(1, min(limit, musiccfg.MUSIC_MAX_PLAYLIST_ITEMS))]
        spotify = bool(SPOTIFY_RE.search(query))
        source_label = "Spotify • LavaSrc" if spotify else "Lavalink"
        tracks = [self._track_from_lavalink(item, requester_id, source_label=source_label, fallback_url=query) for item in items]
        kind = "Spotify • LavaSrc" if spotify else ("Lavalink playlist" if isinstance(result, wavelink.Playlist) else "Lavalink / keresés")
        return tracks, kind

    async def _extract_spotify_tracks(self, query: str, requester_id: int, limit: int) -> list[Track]:
        if importlib.util.find_spec("spotdl") is None:
            raise ValueError("Spotify linkhez hiányzik a **spotDL** dependency. A friss `requirements.txt` telepítése szükséges.")

        # FAST PATH: exactly one metadata pass. No --preload and no playlist-wide
        # `spotdl url` call. Audio is resolved only for the current track.
        items = await self._spotdl_save_items(query, preload=False)
        if not items:
            raise ValueError("A Spotify linkből nem sikerült zenéket kiolvasni.")

        items = items[: max(1, min(limit, musiccfg.MUSIC_MAX_PLAYLIST_ITEMS))]
        tracks: list[Track] = []
        for item in items:
            name = str(item.get("name") or item.get("title") or "").strip()
            artists = _spotify_artists(item)
            if not name:
                continue
            artist_text = ", ".join(artists)
            display_title = f"{artist_text} — {name}" if artist_text else name
            spotify_url = str(item.get("url") or item.get("spotify_url") or query)
            duration_raw = item.get("duration")
            duration = int(float(duration_raw)) if isinstance(duration_raw, (int, float)) else None
            thumbnail = item.get("cover_url") or item.get("cover") or item.get("album_art")
            isrc = str(item.get("isrc") or "").strip() or None

            # ISRC is the first lightweight audio lookup. Title/artist remains
            # only a fallback for sources where ISRC is not indexed.
            fallback_search = f"ytsearch1:{artist_text + ' - ' if artist_text else ''}{name} audio"
            primary_search = f"ytsearch1:{isrc}" if isrc else fallback_search
            tracks.append(
                Track(
                    query=primary_search,
                    title=display_title,
                    webpage_url=spotify_url,
                    duration=duration,
                    requester_id=requester_id,
                    source="Spotify • Fast Resolver",
                    thumbnail=str(thumbnail) if isinstance(thumbnail, str) and thumbnail.startswith("http") else None,
                    fallback_query=fallback_search if primary_search != fallback_search else None,
                    isrc=isrc,
                )
            )

        if not tracks:
            raise ValueError("A Spotify linkből nem sikerült érvényes zenéket kiolvasni.")
        return tracks

    async def _resolve_input(self, query: str, requester_id: int, limit: int) -> tuple[list[Track], str]:
        query = query.strip()
        if not query:
            raise ValueError("Adj meg egy zenét, YouTube/Spotify linket vagy playlistet.")
        # v3.17.2: Spotify is intentionally Python-first. It no longer waits
        # for an external Lavalink node and never resolves a whole playlist's
        # audio sources up front.
        if SPOTIFY_RE.search(query):
            return await self._extract_spotify_tracks(query, requester_id, limit), "Spotify • Fast Resolver"
        if self._lavalink_ready():
            try:
                return await self._extract_lavalink_tracks(query, requester_id, limit)
            except ValueError as exc:
                logger.warning("Lavalink resolve failed, legacy fallback: %s", exc)
        if YOUTUBE_PLAYLIST_RE.search(query):
            return await self._extract_youtube_playlist(query, requester_id, limit), "YouTube playlist"
        return [await self._extract_metadata(query, requester_id)], "YouTube / keresés"

    async def _extract_stream_url(self, track: Track) -> str:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp nincs telepítve")

        cache_key = track.webpage_url or track.query
        cached = self._cache_get(self._stream_url_cache, cache_key, musiccfg.MUSIC_STREAM_CACHE_SECONDS)
        if isinstance(cached, str) and cached.startswith("http"):
            return cached

        # For Spotify tracks source matching is JIT: only the track that is
        # actually about to play gets a spotDL provider lookup. If that lookup
        # is slow/unavailable, a hard timeout drops immediately to ISRC/title.
        provider_url: str | None = None
        if track.source.startswith("Spotify") and SPOTIFY_RE.search(track.webpage_url):
            try:
                async with self._spotify_source_semaphore:
                    urls = await self._spotdl_source_urls(
                        track.webpage_url,
                        timeout=musiccfg.MUSIC_SPOTIFY_SOURCE_TIMEOUT_SECONDS,
                    )
                if urls:
                    provider_url = urls[0]
            except Exception as exc:
                logger.info("Spotify JIT provider lookup fallback for %s: %s", track.title, _truncate(str(exc), 180))

        def work() -> str:
            opts = {
                "format": "bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "default_search": "ytsearch1",
                "socket_timeout": musiccfg.MUSIC_YTDLP_SOCKET_TIMEOUT_SECONDS,
                "retries": 1,
                "extractor_retries": 1,
                "fragment_retries": 1,
            }
            candidates: list[str] = []
            for candidate in (provider_url, track.query, track.fallback_query):
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

            failures: list[str] = []
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[union-attr]
                for candidate in candidates:
                    try:
                        data = ydl.extract_info(candidate, download=False)
                        if data is None:
                            raise ValueError("üres yt-dlp válasz")
                        if "entries" in data:
                            entries = [entry for entry in (data.get("entries") or []) if entry]
                            if not entries:
                                raise ValueError("nincs találat")
                            data = entries[0]
                        url = data.get("url")
                        if not url:
                            raise ValueError("nincs audio stream URL")
                        return str(url)
                    except Exception as exc:
                        failures.append(_truncate(str(exc), 180))

            detail = " • ".join(failures[-3:])
            raise ValueError(f"Nem sikerült lejátszható audio streamet találni. {detail}".strip())

        try:
            url = await asyncio.wait_for(
                asyncio.to_thread(work),
                timeout=musiccfg.MUSIC_YTDLP_RESOLVE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise ValueError(f"A zene audioforrásának feloldása túllépte a {musiccfg.MUSIC_YTDLP_RESOLVE_TIMEOUT_SECONDS} mp-es limitet; Yoru átugorja.") from exc
        self._cache_put(self._stream_url_cache, cache_key, url)
        return url

    async def _send_channel(self, guild_id: int, embed: discord.Embed) -> None:
        player = self.players.get(guild_id)
        if not player or not player.last_text_channel_id:
            return
        channel = self.bot.get_channel(player.last_text_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def _cancel_idle(self, player: GuildPlayer) -> None:
        if player.idle_task and not player.idle_task.done():
            player.idle_task.cancel()
        player.idle_task = None

    async def _schedule_idle_disconnect(self, guild_id: int) -> None:
        player = self.players.get(guild_id)
        if player is None:
            return
        await self._cancel_idle(player)

        async def idle() -> None:
            try:
                await asyncio.sleep(musiccfg.MUSIC_IDLE_DISCONNECT_SECONDS)
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    return
                state = self.players.get(guild_id)
                voice = self._voice_client(guild)
                if state and voice and state.current is None and not state.queue and not self._voice_playing(voice) and not self._voice_paused(voice):
                    await self._disconnect_voice(voice)
                    self.players.pop(guild_id, None)
                    await self._refresh_panel(guild)
            except asyncio.CancelledError:
                pass

        player.idle_task = asyncio.create_task(idle())

    async def _start_track(self, guild: discord.Guild, player: GuildPlayer, track: Track) -> None:
        voice = self._voice_client(guild)
        if voice is None or not self._voice_connected(voice):
            player.current = None
            await self._schedule_idle_disconnect(guild.id)
            await self._refresh_panel(guild)
            return

        player.current = track
        player.stop_requested = False
        player.skip_current = False
        await self._cancel_idle(player)

        if self._is_lavalink_voice(voice):
            try:
                playable = wavelink.Playable(track.lavalink_data) if track.lavalink_data else None
                if playable is None:
                    result = await wavelink.Playable.search(track.query, node=self._lavalink_node)
                    if not result:
                        raise ValueError("A Lavalink nem találta újra a tracket.")
                    playable = result.tracks[0] if isinstance(result, wavelink.Playlist) else result[0]
                try:
                    playable.extras = {"requester_id": track.requester_id, "yoru_title": track.title}
                except Exception:
                    pass
                await voice.play(playable, volume=max(0, min(1000, round(player.volume * 100))))
            except Exception as exc:
                player.current = None
                embed = base_embed("❌ Music hiba", f"**{_truncate(track.title, 100)}** nem indult el Lavalinken.\n`{_truncate(str(exc), 700)}`")
                embed.set_footer(text="Yoru • Music • Lavalink")
                await self._send_channel(guild.id, embed)
                await self._advance(guild.id, playback_error=True)
                return
        else:
            try:
                stream_url = await self._extract_stream_url(track)
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(
                        stream_url,
                        executable=FFMPEG_EXECUTABLE,
                        before_options=FFMPEG_BEFORE_OPTIONS,
                        options=FFMPEG_OPTIONS,
                    ),
                    volume=player.volume,
                )
            except Exception as exc:
                player.current = None
                embed = base_embed("❌ Music hiba", f"**{_truncate(track.title, 100)}** nem indult el.\n`{_truncate(str(exc), 700)}`")
                embed.set_footer(text="Yoru • Music • Legacy")
                await self._send_channel(guild.id, embed)
                await self._advance(guild.id, playback_error=True)
                return

            def after(error: Exception | None) -> None:
                self.bot.loop.call_soon_threadsafe(asyncio.create_task, self._advance(guild.id, playback_error=error is not None))

            try:
                voice.play(source, after=after)
            except Exception as exc:
                player.current = None
                embed = base_embed("❌ Music hiba", f"Nem sikerült elindítani a lejátszást.\n`{_truncate(str(exc), 700)}`")
                embed.set_footer(text="Yoru • Music • Legacy")
                await self._send_channel(guild.id, embed)
                await self._advance(guild.id, playback_error=True)
                return

        embed = base_embed("🎵 Most szól", f"**[{_truncate(track.title, 180)}]({track.webpage_url})**")
        embed.add_field(name="⏱️ Hossz", value=_format_duration(track.duration), inline=True)
        embed.add_field(name="🔊 Hangerő", value=f"{round(player.volume * 100)}%", inline=True)
        embed.add_field(name="📋 Queue", value=f"{len(player.queue)} zene", inline=True)
        embed.add_field(name="Forrás", value=track.source, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text="Yoru • Music • " + ("Lavalink" if self._is_lavalink_voice(voice) else "Fast Resolver"))
        await self._send_channel(guild.id, embed)
        await self._refresh_panel(guild)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: Any) -> None:
        if wavelink is None:
            return
        voice = getattr(payload, "player", None)
        guild = getattr(voice, "guild", None)
        if guild is None or guild.id not in self.players:
            return
        await self._advance(guild.id, playback_error=False)

    async def _advance(self, guild_id: int, *, playback_error: bool = False) -> None:
        guild = self.bot.get_guild(guild_id)
        player = self.players.get(guild_id)
        if guild is None or player is None:
            return
        async with player.lock:
            previous = player.current
            if player.stop_requested:
                player.current = None
                player.stop_requested = False
                player.skip_current = False
                await self._schedule_idle_disconnect(guild_id)
                await self._refresh_panel(guild)
                return
            if player.loop_current and previous is not None and not player.skip_current and not playback_error:
                next_track = previous
            else:
                next_track = player.queue.popleft() if player.queue else None
            player.current = None
            player.skip_current = False
            if next_track is None:
                await self._schedule_idle_disconnect(guild_id)
                await self._refresh_panel(guild)
                return
            player.current = next_track  # reserve it against simultaneous /play calls
        await self._start_track(guild, player, next_track)

    async def _enqueue_input(
        self,
        guild: discord.Guild,
        member: discord.Member,
        text_channel_id: int,
        query: str,
    ) -> tuple[list[Track], bool, str, int]:
        runtime = self._runtime_problem()
        if runtime:
            raise ValueError(runtime)
        player = await self._player(guild.id)
        max_queue = await self.get_max_queue(guild.id)
        await self._connect_for_member(guild, member)
        voice = self._voice_client(guild)
        if voice is None:
            raise ValueError("Nem sikerült voice csatornához csatlakozni.")

        async with player.lock:
            idle = player.current is None and not self._voice_playing(voice) and not self._voice_paused(voice)
            capacity = max_queue - len(player.queue) + (1 if idle else 0)
        if capacity <= 0:
            raise ValueError(f"A queue tele van (**{max_queue}** zene).")

        requested_limit = min(capacity, musiccfg.MUSIC_MAX_PLAYLIST_ITEMS)
        tracks, source_kind = await self._resolve_input(query, member.id, requested_limit)
        if not tracks:
            raise ValueError("Nem találtam hozzáadható zenét.")

        started = False
        start_track: Track | None = None
        added: list[Track] = []
        async with player.lock:
            idle = player.current is None and not self._voice_playing(voice) and not self._voice_paused(voice)
            room = max_queue - len(player.queue)
            if idle and tracks:
                start_track = tracks[0]
                player.current = start_track  # reserve slot
                added.append(start_track)
                tracks = tracks[1:]
                started = True
            if room > 0 and tracks:
                batch = tracks[:room]
                player.queue.extend(batch)
                added.extend(batch)
            player.last_text_channel_id = text_channel_id
        await self._cancel_idle(player)

        if start_track is not None:
            # Do not keep /play or !play waiting while yt-dlp/spotDL resolves the
            # first audio source. The slot is already reserved above, so a
            # second /play cannot race it. _start_track handles its own errors.
            asyncio.create_task(self._start_track(guild, player, start_track))
        else:
            await self._refresh_panel(guild)
        return added, started, source_kind, len(player.queue)

    def _queued_embed(self, user: discord.abc.User, tracks: list[Track], started: bool, source_kind: str, queue_size: int) -> discord.Embed:
        if len(tracks) == 1:
            track = tracks[0]
            title = "🎵 Betöltve" if started else "➕ Queue"
            embed = player_embed(title, user, description=f"**[{_truncate(track.title, 180)}]({track.webpage_url})**", color=SUCCESS if started else BRAND)
            embed.add_field(name="Állapot", value="▶️ Indul" if started else "⏭️ Queue-ban", inline=True)
            embed.add_field(name="Hossz", value=_format_duration(track.duration), inline=True)
            embed.add_field(name="Forrás", value=track.source, inline=True)
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
        else:
            embed = player_embed("🎶 Playlist hozzáadva", user, description=f"**{len(tracks)} zene** bekerült Yoru Musicba.", color=SUCCESS)
            embed.add_field(name="Forrás", value=source_kind, inline=True)
            embed.add_field(name="Queue", value=f"**{queue_size}** várakozik", inline=True)
            embed.add_field(name="Lejátszás", value="▶️ Elindult" if started else "⏭️ Sorba állítva", inline=True)
            preview = "\n".join(f"`{i}.` {_truncate(t.title, 70)}" for i, t in enumerate(tracks[:8], start=1))
            if len(tracks) > 8:
                preview += f"\n… és még **{len(tracks) - 8}**"
            embed.add_field(name="Hozzáadva", value=preview, inline=False)
        embed.set_footer(text="Yoru • Music")
        return embed

    async def _play_interaction(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._gate_interaction(interaction):
            return
        await interaction.response.defer(thinking=True)
        try:
            tracks, started, source_kind, queue_size = await self._enqueue_input(interaction.guild, interaction.user, interaction.channel_id, query)
        except Exception as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await interaction.followup.send(embed=self._queued_embed(interaction.user, tracks, started, source_kind, queue_size))

    async def _play_ctx(self, ctx: commands.Context, query: str) -> None:
        if not await self._gate_ctx(ctx):
            return
        async with ctx.typing():
            try:
                tracks, started, source_kind, queue_size = await self._enqueue_input(ctx.guild, ctx.author, ctx.channel.id, query)
            except Exception as exc:
                return await ctx.send(embed=error_embed(ctx.author, str(exc)))
        await ctx.send(embed=self._queued_embed(ctx.author, tracks, started, source_kind, queue_size))

    def _queue_embed(self, guild: discord.Guild, player: GuildPlayer) -> discord.Embed:
        embed = base_embed("📋 Music Queue")
        if player.current:
            embed.add_field(name="▶️ Most", value=f"**{_truncate(player.current.title, 180)}** • `{_format_duration(player.current.duration)}`\n{player.current.source}", inline=False)
        if player.queue:
            lines = [f"`{index}.` **{_truncate(track.title, 70)}** • `{_format_duration(track.duration)}`" for index, track in enumerate(list(player.queue)[:10], start=1)]
            if len(player.queue) > 10:
                lines.append(f"… és még **{len(player.queue) - 10}** zene")
            embed.add_field(name=f"⏭️ Következik • {len(player.queue)}", value="\n".join(lines), inline=False)
        elif not player.current:
            embed.description = "A queue üres."
        embed.add_field(name="🔁 Loop", value="Be" if player.loop_current else "Ki", inline=True)
        embed.add_field(name="🔊 Hangerő", value=f"{round(player.volume * 100)}%", inline=True)
        voice = self._voice_client(guild)
        embed.add_field(name="🔈 Voice", value=voice.channel.mention if voice else "Nincs csatlakozva", inline=True)
        embed.set_footer(text="Yoru • Music")
        return embed

    async def _panel_embed(self, guild: discord.Guild) -> discord.Embed:
        player = await self._player(guild.id)
        voice = self._voice_client(guild)
        embed = base_embed(
            "🎶 Yoru Music Player",
            "Tagoknak is használható interaktív lejátszó. A **Zene hozzáadása** gomb elfogad keresést, YouTube linket/playlistet és Spotify track/album/playlist linket.",
        )
        if player.current:
            current = player.current
            embed.add_field(
                name="▶️ Most szól",
                value=f"**[{_truncate(current.title, 180)}]({current.webpage_url})**\n`{_format_duration(current.duration)}` • {current.source}",
                inline=False,
            )
            if current.thumbnail:
                embed.set_thumbnail(url=current.thumbnail)
        else:
            embed.add_field(name="▶️ Most szól", value="*Semmi.* Nyomd meg a **Zene hozzáadása** gombot.", inline=False)

        if player.queue:
            lines = [f"`{i}.` {_truncate(track.title, 65)}" for i, track in enumerate(list(player.queue)[:5], start=1)]
            if len(player.queue) > 5:
                lines.append(f"… +**{len(player.queue) - 5}**")
            embed.add_field(name=f"📋 Queue • {len(player.queue)}", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📋 Queue", value="Üres", inline=False)
        embed.add_field(name="🔊 Hangerő", value=f"**{round(player.volume * 100)}%**", inline=True)
        embed.add_field(name="🔁 Loop", value="**BE**" if player.loop_current else "KI", inline=True)
        if voice:
            state = "⏸️ Szünet" if self._voice_paused(voice) else ("▶️ Lejátszás" if self._voice_playing(voice) else "🟡 Várakozik")
            embed.add_field(name="🎧 Voice", value=f"{voice.channel.mention}\n{state}", inline=True)
        else:
            embed.add_field(name="🎧 Voice", value="Nincs csatlakozva", inline=True)
        embed.set_footer(text="Yoru • Music • Fast Resolver")
        return embed

    async def _get_saved_panel_message(self, guild: discord.Guild) -> discord.Message | None:
        channel_id = await self.settings.get_int(guild.id, musiccfg.MUSIC_PANEL_CHANNEL_KEY)
        message_id = await self.settings.get_int(guild.id, musiccfg.MUSIC_PANEL_MESSAGE_KEY)
        if not channel_id or not message_id:
            return None
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await self.settings.set_int(guild.id, musiccfg.MUSIC_PANEL_CHANNEL_KEY, None)
            await self.settings.set_int(guild.id, musiccfg.MUSIC_PANEL_MESSAGE_KEY, None)
            return None

    async def publish_panel(self, guild: discord.Guild, channel: discord.abc.Messageable) -> discord.Message:
        existing = await self._get_saved_panel_message(guild)
        if existing is not None:
            await existing.edit(embed=await self._panel_embed(guild), view=MusicPanelView(self))
            return existing
        message = await channel.send(embed=await self._panel_embed(guild), view=MusicPanelView(self))
        await self.settings.set_int(guild.id, musiccfg.MUSIC_PANEL_CHANNEL_KEY, message.channel.id)
        await self.settings.set_int(guild.id, musiccfg.MUSIC_PANEL_MESSAGE_KEY, message.id)
        return message

    async def _refresh_panel(self, guild: discord.Guild) -> None:
        try:
            message = await self._get_saved_panel_message(guild)
            if message is not None:
                await message.edit(embed=await self._panel_embed(guild), view=MusicPanelView(self))
        except Exception:
            # Panel refresh must never break playback.
            pass

    async def _set_volume(self, guild: discord.Guild, percent: int) -> None:
        if not musiccfg.MUSIC_MIN_VOLUME <= percent <= musiccfg.MUSIC_MAX_VOLUME:
            raise ValueError(f"A hangerő {musiccfg.MUSIC_MIN_VOLUME}–{musiccfg.MUSIC_MAX_VOLUME}% között legyen.")
        player = await self._player(guild.id)
        player.volume = percent / 100
        voice = self._voice_client(guild)
        if voice:
            await self._set_voice_volume(voice, percent)
        await self._refresh_panel(guild)

    @app_commands.command(name="play", description="Keresés, YouTube/Spotify link vagy playlist hozzáadása.")
    async def play_slash(self, interaction: discord.Interaction, keresés: str) -> None:
        await self._play_interaction(interaction, keresés)

    @commands.command(name="play", aliases=["mplay", "musicplay"])
    @commands.guild_only()
    async def play_prefix(self, ctx: commands.Context, *, query: str) -> None:
        await self._play_ctx(ctx, query)

    @app_commands.command(name="panel", description="Megnyitja vagy frissíti az interaktív Yoru Music panelt.")
    async def panel_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, require_voice=False):
            return
        existing = await self._get_saved_panel_message(interaction.guild)
        if existing is not None:
            await existing.edit(embed=await self._panel_embed(interaction.guild), view=MusicPanelView(self))
            return await interaction.response.send_message(f"🎶 Music panel frissítve: {existing.jump_url}", ephemeral=True)
        await interaction.response.send_message(embed=await self._panel_embed(interaction.guild), view=MusicPanelView(self))
        message = await interaction.original_response()
        await self.settings.set_int(interaction.guild.id, musiccfg.MUSIC_PANEL_CHANNEL_KEY, message.channel.id)
        await self.settings.set_int(interaction.guild.id, musiccfg.MUSIC_PANEL_MESSAGE_KEY, message.id)

    @commands.command(name="musicpanel", aliases=["mpanel"])
    @commands.guild_only()
    async def panel_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, require_voice=False):
            return
        message = await self.publish_panel(ctx.guild, ctx.channel)
        if message.channel.id != ctx.channel.id:
            await ctx.send(f"🎶 Music panel frissítve: {message.jump_url}")

    @app_commands.command(name="pause", description="Szünetelteti az aktuális zenét.")
    async def pause_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        voice = self._voice_client(interaction.guild)
        if voice is None or not self._voice_playing(voice): return await interaction.response.send_message("❌ Most nem szól zene.", ephemeral=True)
        await self._pause_voice(voice, True); await self._refresh_panel(interaction.guild)
        await interaction.response.send_message("⏸️ **Szüneteltetve.**")

    @commands.command(name="pause", aliases=["mpause"])
    @commands.guild_only()
    async def pause_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        voice = self._voice_client(ctx.guild)
        if voice is None or not self._voice_playing(voice): return await ctx.send(embed=error_embed(ctx.author, "Most nem szól zene."))
        await self._pause_voice(voice, True); await self._refresh_panel(ctx.guild); await ctx.send("⏸️ **Szüneteltetve.**")

    @app_commands.command(name="resume", description="Folytatja a szüneteltetett zenét.")
    async def resume_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        voice = self._voice_client(interaction.guild)
        if voice is None or not self._voice_paused(voice): return await interaction.response.send_message("❌ Nincs szüneteltetett zene.", ephemeral=True)
        await self._pause_voice(voice, False); await self._refresh_panel(interaction.guild); await interaction.response.send_message("▶️ **Folytatva.**")

    @commands.command(name="resume", aliases=["mresume"])
    @commands.guild_only()
    async def resume_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        voice = self._voice_client(ctx.guild)
        if voice is None or not self._voice_paused(voice): return await ctx.send(embed=error_embed(ctx.author, "Nincs szüneteltetett zene."))
        await self._pause_voice(voice, False); await self._refresh_panel(ctx.guild); await ctx.send("▶️ **Folytatva.**")

    @app_commands.command(name="skip", description="Átugorja az aktuális zenét.")
    async def skip_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        voice = self._voice_client(interaction.guild); player = await self._player(interaction.guild.id)
        if voice is None or (not self._voice_playing(voice) and not self._voice_paused(voice)): return await interaction.response.send_message("❌ Most nem szól zene.", ephemeral=True)
        player.skip_current = True; await self._skip_voice(voice); await interaction.response.send_message("⏭️ **Átugorva.**")

    @commands.command(name="skip", aliases=["mskip", "next"])
    @commands.guild_only()
    async def skip_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        voice = self._voice_client(ctx.guild); player = await self._player(ctx.guild.id)
        if voice is None or (not self._voice_playing(voice) and not self._voice_paused(voice)): return await ctx.send(embed=error_embed(ctx.author, "Most nem szól zene."))
        player.skip_current = True; await self._skip_voice(voice); await ctx.send("⏭️ **Átugorva.**")

    @app_commands.command(name="stop", description="Leállítja a zenét és üríti a queue-t.")
    async def stop_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        player = await self._player(interaction.guild.id); voice = self._voice_client(interaction.guild)
        player.queue.clear(); player.loop_current = False; player.stop_requested = True
        if voice and (self._voice_playing(voice) or self._voice_paused(voice)): await self._skip_voice(voice)
        else: player.current = None; player.stop_requested = False; await self._schedule_idle_disconnect(interaction.guild.id); await self._refresh_panel(interaction.guild)
        await interaction.response.send_message("⏹️ **Leállítva, queue ürítve.**")

    @commands.command(name="stop", aliases=["mstop"])
    @commands.guild_only()
    async def stop_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        player = await self._player(ctx.guild.id); voice = self._voice_client(ctx.guild)
        player.queue.clear(); player.loop_current = False; player.stop_requested = True
        if voice and (self._voice_playing(voice) or self._voice_paused(voice)): await self._skip_voice(voice)
        else: player.current = None; player.stop_requested = False; await self._schedule_idle_disconnect(ctx.guild.id); await self._refresh_panel(ctx.guild)
        await ctx.send("⏹️ **Leállítva, queue ürítve.**")

    @app_commands.command(name="queue", description="Megmutatja az aktuális music queue-t.")
    async def queue_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, require_voice=False): return
        await interaction.response.send_message(embed=self._queue_embed(interaction.guild, await self._player(interaction.guild.id)))

    @commands.command(name="queue", aliases=["mq", "musicqueue"])
    @commands.guild_only()
    async def queue_prefix(self, ctx: commands.Context) -> None:
        if await self._gate_ctx(ctx, require_voice=False): await ctx.send(embed=self._queue_embed(ctx.guild, await self._player(ctx.guild.id)))

    @app_commands.command(name="now", description="Megmutatja, mi szól jelenleg.")
    async def now_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, require_voice=False): return
        player = await self._player(interaction.guild.id)
        if not player.current: return await interaction.response.send_message("❌ Most nem szól zene.", ephemeral=True)
        await interaction.response.send_message(embed=self._queue_embed(interaction.guild, player))

    @commands.command(name="nowplaying", aliases=["np", "mnow"])
    @commands.guild_only()
    async def now_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, require_voice=False): return
        player = await self._player(ctx.guild.id)
        if not player.current: return await ctx.send(embed=error_embed(ctx.author, "Most nem szól zene."))
        await ctx.send(embed=self._queue_embed(ctx.guild, player))

    @app_commands.command(name="volume", description="Beállítja a hangerőt 5–150% között.")
    async def volume_slash(self, interaction: discord.Interaction, százalék: app_commands.Range[int, 5, 150]) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        await self._set_volume(interaction.guild, int(százalék))
        await interaction.response.send_message(f"🔊 Hangerő: **{százalék}%**")

    @commands.command(name="volume", aliases=["vol", "mvol"])
    @commands.guild_only()
    async def volume_prefix(self, ctx: commands.Context, percent: int) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        try: await self._set_volume(ctx.guild, percent)
        except ValueError as exc: return await ctx.send(embed=error_embed(ctx.author, str(exc)))
        await ctx.send(f"🔊 Hangerő: **{percent}%**")

    @app_commands.command(name="loop", description="Be-/kikapcsolja az aktuális zene ismétlését.")
    async def loop_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        player = await self._player(interaction.guild.id); player.loop_current = not player.loop_current
        await self._refresh_panel(interaction.guild)
        await interaction.response.send_message(f"🔁 Loop: **{'BE' if player.loop_current else 'KI'}**")

    @commands.command(name="loop", aliases=["mloop"])
    @commands.guild_only()
    async def loop_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        player = await self._player(ctx.guild.id); player.loop_current = not player.loop_current
        await self._refresh_panel(ctx.guild); await ctx.send(f"🔁 Loop: **{'BE' if player.loop_current else 'KI'}**")

    @app_commands.command(name="shuffle", description="Megkeveri a queue-t.")
    async def shuffle_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        player = await self._player(interaction.guild.id)
        if len(player.queue) < 2: return await interaction.response.send_message("❌ Legalább 2 zene kell a queue-ban.", ephemeral=True)
        values = list(player.queue); random.shuffle(values); player.queue = deque(values)
        await self._refresh_panel(interaction.guild); await interaction.response.send_message("🔀 **Queue megkeverve.**")

    @commands.command(name="shuffle", aliases=["mixqueue", "mshuffle"])
    @commands.guild_only()
    async def shuffle_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        player = await self._player(ctx.guild.id)
        if len(player.queue) < 2: return await ctx.send(embed=error_embed(ctx.author, "Legalább 2 zene kell a queue-ban."))
        values = list(player.queue); random.shuffle(values); player.queue = deque(values)
        await self._refresh_panel(ctx.guild); await ctx.send("🔀 **Queue megkeverve.**")

    @app_commands.command(name="leave", description="Yoru kilép a voice csatornából és üríti a queue-t.")
    async def leave_slash(self, interaction: discord.Interaction) -> None:
        if not await self._gate_interaction(interaction, control=True): return
        voice = self._voice_client(interaction.guild)
        if voice is None: return await interaction.response.send_message("❌ Yoru nincs voice csatornában.", ephemeral=True)
        player = await self._player(interaction.guild.id); player.queue.clear(); player.current = None; player.stop_requested = True
        await self._cancel_idle(player); await self._disconnect_voice(voice); self.players.pop(interaction.guild.id, None)
        await self._refresh_panel(interaction.guild); await interaction.response.send_message("👋 **Kiléptem a voice csatornából.**")

    @commands.command(name="leave", aliases=["musicdc", "mleave"])
    @commands.guild_only()
    async def leave_prefix(self, ctx: commands.Context) -> None:
        if not await self._gate_ctx(ctx, control=True): return
        voice = self._voice_client(ctx.guild)
        if voice is None: return await ctx.send(embed=error_embed(ctx.author, "Yoru nincs voice csatornában."))
        player = await self._player(ctx.guild.id); player.queue.clear(); player.current = None; player.stop_requested = True
        await self._cancel_idle(player); await self._disconnect_voice(voice); self.players.pop(ctx.guild.id, None)
        await self._refresh_panel(ctx.guild); await ctx.send("👋 **Kiléptem a voice csatornából.**")


class MusicAddModal(discord.ui.Modal, title="Zene hozzáadása"):
    query = discord.ui.TextInput(
        label="Keresés / YouTube / Spotify link",
        placeholder="pl. The Weeknd - Blinding Lights vagy playlist link",
        min_length=1,
        max_length=500,
    )

    def __init__(self, cog: MusicCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog._gate_interaction(interaction):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            tracks, started, source_kind, queue_size = await self.cog._enqueue_input(
                interaction.guild, interaction.user, interaction.channel_id, str(self.query.value)
            )
        except Exception as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await interaction.followup.send(
            embed=self.cog._queued_embed(interaction.user, tracks, started, source_kind, queue_size),
            ephemeral=True,
        )


class MusicPanelVolumeModal(discord.ui.Modal, title="Music hangerő"):
    percent = discord.ui.TextInput(label="Hangerő (%)", placeholder="5 - 150", min_length=1, max_length=3)

    def __init__(self, cog: MusicCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog._gate_interaction(interaction, control=True):
            return
        try:
            value = int(str(self.percent.value).strip())
            await self.cog._set_volume(interaction.guild, value)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(f"🔊 Hangerő: **{value}%**", ephemeral=True)


class MusicPanelView(discord.ui.View):
    def __init__(self, cog: MusicCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Zene hozzáadása", emoji="➕", style=discord.ButtonStyle.success, custom_id="yoru:music:add", row=0)
    async def add_music(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Csak szerveren használható.", ephemeral=True)
        if not await self.cog.is_enabled(interaction.guild.id):
            return await interaction.response.send_message("❌ A Music modul ki van kapcsolva.", ephemeral=True)
        allowed, reason = await self.cog._channel_allowed(interaction.guild, interaction.channel_id)
        if not allowed:
            return await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
        await interaction.response.send_modal(MusicAddModal(self.cog))

    @discord.ui.button(label="Pause / Resume", emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="yoru:music:pause_resume", row=0)
    async def pause_resume(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, control=True): return
        voice = self.cog._voice_client(interaction.guild)
        if voice is None or (not self.cog._voice_playing(voice) and not self.cog._voice_paused(voice)):
            return await interaction.response.send_message("❌ Most nem szól zene.", ephemeral=True)
        if self.cog._voice_paused(voice):
            await self.cog._pause_voice(voice, False); text = "▶️ Folytatva."
        else:
            await self.cog._pause_voice(voice, True); text = "⏸️ Szüneteltetve."
        await self.cog._refresh_panel(interaction.guild)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.primary, custom_id="yoru:music:skip", row=0)
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, control=True): return
        voice = self.cog._voice_client(interaction.guild); player = await self.cog._player(interaction.guild.id)
        if voice is None or (not self.cog._voice_playing(voice) and not self.cog._voice_paused(voice)):
            return await interaction.response.send_message("❌ Most nem szól zene.", ephemeral=True)
        player.skip_current = True; await self.cog._skip_voice(voice)
        await interaction.response.send_message("⏭️ Átugorva.", ephemeral=True)

    @discord.ui.button(label="Queue", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="yoru:music:queue", row=0)
    async def queue(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, require_voice=False): return
        await interaction.response.send_message(embed=self.cog._queue_embed(interaction.guild, await self.cog._player(interaction.guild.id)), ephemeral=True)

    @discord.ui.button(label="Frissítés", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="yoru:music:refresh", row=0)
    async def refresh(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, require_voice=False): return
        await interaction.response.edit_message(embed=await self.cog._panel_embed(interaction.guild), view=MusicPanelView(self.cog))

    @discord.ui.button(label="Shuffle", emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="yoru:music:shuffle", row=1)
    async def shuffle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, control=True): return
        player = await self.cog._player(interaction.guild.id)
        if len(player.queue) < 2: return await interaction.response.send_message("❌ Legalább 2 zene kell a queue-ban.", ephemeral=True)
        values = list(player.queue); random.shuffle(values); player.queue = deque(values)
        await self.cog._refresh_panel(interaction.guild); await interaction.response.send_message("🔀 Queue megkeverve.", ephemeral=True)

    @discord.ui.button(label="Loop", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="yoru:music:loop", row=1)
    async def loop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, control=True): return
        player = await self.cog._player(interaction.guild.id); player.loop_current = not player.loop_current
        await self.cog._refresh_panel(interaction.guild)
        await interaction.response.send_message(f"🔁 Loop: **{'BE' if player.loop_current else 'KI'}**", ephemeral=True)

    @discord.ui.button(label="Hangerő", emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="yoru:music:volume", row=1)
    async def volume(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Csak szerveren használható.", ephemeral=True)
        if not await self.cog._is_dj(interaction.user):
            return await interaction.response.send_message("❌ Ehhez DJ rang vagy Manage Server kell.", ephemeral=True)
        await interaction.response.send_modal(MusicPanelVolumeModal(self.cog))

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="yoru:music:stop", row=1)
    async def stop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, control=True): return
        player = await self.cog._player(interaction.guild.id); voice = self.cog._voice_client(interaction.guild)
        player.queue.clear(); player.loop_current = False; player.stop_requested = True
        if voice and (self.cog._voice_playing(voice) or self.cog._voice_paused(voice)): await self.cog._skip_voice(voice)
        else: player.current = None; player.stop_requested = False; await self.cog._refresh_panel(interaction.guild)
        await interaction.response.send_message("⏹️ Leállítva, queue ürítve.", ephemeral=True)

    @discord.ui.button(label="Kilépés", emoji="👋", style=discord.ButtonStyle.danger, custom_id="yoru:music:leave", row=1)
    async def leave(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not await self.cog._gate_interaction(interaction, control=True): return
        voice = self.cog._voice_client(interaction.guild)
        if voice is None: return await interaction.response.send_message("❌ Yoru nincs voice csatornában.", ephemeral=True)
        player = await self.cog._player(interaction.guild.id); player.queue.clear(); player.current = None; player.stop_requested = True
        await self.cog._cancel_idle(player); await self.cog._disconnect_voice(voice); self.cog.players.pop(interaction.guild.id, None)
        await self.cog._refresh_panel(interaction.guild); await interaction.response.send_message("👋 Kiléptem a voice csatornából.", ephemeral=True)


class MusicTuneModal(discord.ui.Modal, title="Music alapbeállítások"):
    volume = discord.ui.TextInput(label="Alap hangerő (%)", min_length=1, max_length=3)
    max_queue = discord.ui.TextInput(label="Queue limit", min_length=1, max_length=3)

    def __init__(self, view: "MusicSettingsView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            volume = int(str(self.volume.value).strip())
            queue = int(str(self.max_queue.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Csak számot adj meg.", ephemeral=True)
        if not musiccfg.MUSIC_MIN_VOLUME <= volume <= musiccfg.MUSIC_MAX_VOLUME:
            return await interaction.response.send_message(f"❌ Hangerő: {musiccfg.MUSIC_MIN_VOLUME}–{musiccfg.MUSIC_MAX_VOLUME}%.", ephemeral=True)
        if not musiccfg.MUSIC_MIN_QUEUE <= queue <= musiccfg.MUSIC_MAX_QUEUE:
            return await interaction.response.send_message(f"❌ Queue limit: {musiccfg.MUSIC_MIN_QUEUE}–{musiccfg.MUSIC_MAX_QUEUE}.", ephemeral=True)
        await self.parent_view.cog.settings.set_int(interaction.guild_id, musiccfg.MUSIC_VOLUME_KEY, volume)
        await self.parent_view.cog.settings.set_int(interaction.guild_id, musiccfg.MUSIC_MAX_QUEUE_KEY, queue)
        player = self.parent_view.cog.players.get(interaction.guild_id)
        if player is not None:
            player.volume = volume / 100
            voice = self.parent_view.cog._voice_client(interaction.guild)
            if voice:
                await self.parent_view.cog._set_voice_volume(voice, volume)
        await self.parent_view.cog._refresh_panel(interaction.guild)
        await self.parent_view.refresh(interaction)


class MusicSettingsChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "MusicSettingsView") -> None:
        super().__init__(view, view.guild, page_attr="channel_page", selection_key="music_channel", placeholder="Music parancs csatorna…", channel_types=(discord.ChannelType.text, discord.ChannelType.news), row=2, max_values=1)


class MusicSettingsRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "MusicSettingsView") -> None:
        super().__init__(view, view.guild, page_attr="role_page", selection_key="dj_role", placeholder="DJ rang…", row=3, max_values=1)


class MusicSettingsView(OwnedView):
    def __init__(self, cog: MusicCog, owner_id: int, guild: discord.Guild, *, enabled: bool, channel_page: int = 0, role_page: int = 0) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.enabled = enabled
        self.channel_page = channel_page
        self.role_page = role_page
        self.add_item(MusicSettingsChannelSelect(self))
        self.add_item(MusicSettingsRoleSelect(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, self)

    async def handle_channel_selection(self, interaction: discord.Interaction, _selection_key: str, channels: list[discord.abc.GuildChannel]) -> None:
        channel_id = int(channels[0].id)
        await self.cog.settings.set_int(interaction.guild_id, musiccfg.MUSIC_CHANNEL_KEY, channel_id)
        await self.cog.settings.add_exemption(interaction.guild_id, "links", "channel", channel_id)
        await self.cog.settings.add_exemption(interaction.guild_id, "invite", "channel", channel_id)
        await self.refresh(interaction)

    async def handle_role_selection(self, interaction: discord.Interaction, _selection_key: str, roles: list[discord.Role]) -> None:
        await self.cog.settings.set_int(interaction.guild_id, musiccfg.MUSIC_DJ_ROLE_KEY, int(roles[0].id))
        await self.refresh(interaction)

    @discord.ui.button(label="Music", emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.enabled = not self.enabled
        await self.cog.settings.set_bool(interaction.guild_id, musiccfg.MUSIC_ENABLED_KEY, self.enabled)
        if not self.enabled:
            voice = self.cog._voice_client(interaction.guild)
            player = self.cog.players.get(interaction.guild_id)
            if player:
                player.queue.clear(); player.loop_current = False; player.stop_requested = True
            if voice:
                await self.cog._disconnect_voice(voice)
            self.cog.players.pop(interaction.guild_id, None)
        await self.cog._refresh_panel(interaction.guild)
        await self.refresh(interaction)

    @discord.ui.button(label="Hangerő / Queue", emoji="🎚️", style=discord.ButtonStyle.primary, row=0)
    async def tune(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(MusicTuneModal(self))

    @discord.ui.button(label="Player panel", emoji="🎶", style=discord.ButtonStyle.success, row=0)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        channel_id = await self.cog.settings.get_int(interaction.guild_id, musiccfg.MUSIC_CHANNEL_KEY)
        channel = interaction.guild.get_channel(channel_id) if channel_id else interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            return await interaction.response.send_message("❌ Nem találom a Music csatornát.", ephemeral=True)
        message = await self.cog.publish_panel(interaction.guild, channel)
        await interaction.response.send_message(f"🎶 Music panel kész/frissítve: {message.jump_url}", ephemeral=True)

    @discord.ui.button(label="Resolver cache ürítés", emoji="🧹", style=discord.ButtonStyle.primary, row=1)
    async def clear_resolver_cache(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.cog._spotify_metadata_cache.clear()
        self.cog._stream_url_cache.clear()
        await self.refresh(interaction)

    @discord.ui.button(label="Csatorna törlése", emoji="💬", style=discord.ButtonStyle.secondary, row=1)
    async def clear_channel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_int(interaction.guild_id, musiccfg.MUSIC_CHANNEL_KEY, None)
        await self.refresh(interaction)

    @discord.ui.button(label="DJ rang törlése", emoji="🎧", style=discord.ButtonStyle.secondary, row=1)
    async def clear_role(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_int(interaction.guild_id, musiccfg.MUSIC_DJ_ROLE_KEY, None)
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.back_to_settings(interaction, self.owner_id)
