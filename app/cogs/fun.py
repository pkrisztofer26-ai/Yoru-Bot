from __future__ import annotations

import asyncio
import hashlib
import io
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.database import Database
from app.fun_config import FUN_CHANNEL_KEY, FUN_DEFAULT_ENABLED, FUN_ENABLED_KEY
from app.services.server_settings import ServerSettingsService
from app.ui import BRAND, base_embed, error_embed

try:  # Pillow is optional at import time so the rest of Yoru can still boot.
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - host dependency failure
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]


SHIP_CARD_SIZE = (1100, 480)
SHIP_AVATAR_SIZE = 238
SHIP_AVATAR_BORDER = 8


def _stable_percent(*parts: object) -> int:
    payload = ":".join(str(part) for part in parts).encode("utf-8", "ignore")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % 101


def _mock_text(text: str) -> str:
    """Legacy helper kept for backwards-safe imports; Mock is no longer a command."""
    upper = False
    output: list[str] = []
    for char in text:
        if char.isalpha():
            output.append(char.upper() if upper else char.lower())
            upper = not upper
        else:
            output.append(char)
    return "".join(output)


def _ship_score(guild_id: int, first_id: int, second_id: int) -> int:
    low, high = sorted((first_id, second_id))
    return 100 if first_id == second_id else _stable_percent(guild_id, low, high, "ship")


def _font(size: int, *, bold: bool = False):
    if ImageFont is None:
        raise RuntimeError("Pillow nincs telepítve")
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered_text(draw: Any, xy: tuple[int, int], text: str, font: Any, fill: tuple[int, int, int, int]) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    draw.text((xy[0] - width / 2, xy[1] - height / 2 - box[1]), text, font=font, fill=fill)


def _fit_text(draw: Any, text: str, max_width: int, start_size: int = 34, min_size: int = 20):
    clean = text.strip() or "Ismeretlen"
    for size in range(start_size, min_size - 1, -1):
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), clean, font=font)
        if box[2] - box[0] <= max_width:
            return clean, font
    shortened = clean
    font = _font(min_size, bold=True)
    while len(shortened) > 4 and draw.textbbox((0, 0), shortened + "…", font=font)[2] > max_width:
        shortened = shortened[:-1]
    return shortened.rstrip() + "…", font


def _circular_avatar(raw: bytes, size: int) -> Any:
    if Image is None:
        raise RuntimeError("Pillow nincs telepítve")
    with Image.open(io.BytesIO(raw)) as source:
        avatar = source.convert("RGBA")
        width, height = avatar.size
        edge = min(width, height)
        left = (width - edge) // 2
        top = (height - edge) // 2
        avatar = avatar.crop((left, top, left + edge, top + edge)).resize((size, size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(avatar, (0, 0), mask)
    return output


def _build_ship_card(first_avatar: bytes, second_avatar: bytes, first_name: str, second_name: str, score: int) -> bytes:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow nincs telepítve")

    width, height = SHIP_CARD_SIZE
    image = Image.new("RGBA", SHIP_CARD_SIZE, (14, 10, 25, 255))
    pixels = image.load()
    # Lightweight dark-purple vertical gradient, deterministic and host-safe.
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(18 + 15 * t)
        g = int(12 + 5 * t)
        b = int(31 + 30 * t)
        for x in range(width):
            pixels[x, y] = (r, g, b, 255)

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((22, 22, width - 22, height - 22), radius=34, fill=(15, 12, 29, 220), outline=(126, 74, 222, 155), width=3)
    draw.ellipse((-110, -170, 360, 300), fill=(111, 45, 189, 35))
    draw.ellipse((760, 150, 1240, 630), fill=(183, 76, 240, 28))
    draw.rounded_rectangle((435, 138, 665, 343), radius=42, fill=(74, 42, 121, 88), outline=(190, 128, 255, 95), width=2)

    avatar_y = 116
    first_x = 104
    second_x = width - 104 - SHIP_AVATAR_SIZE

    for avatar_raw, avatar_x in ((first_avatar, first_x), (second_avatar, second_x)):
        border_box = (
            avatar_x - SHIP_AVATAR_BORDER,
            avatar_y - SHIP_AVATAR_BORDER,
            avatar_x + SHIP_AVATAR_SIZE + SHIP_AVATAR_BORDER,
            avatar_y + SHIP_AVATAR_SIZE + SHIP_AVATAR_BORDER,
        )
        draw.ellipse(border_box, fill=(153, 93, 235, 255))
        avatar = _circular_avatar(avatar_raw, SHIP_AVATAR_SIZE)
        image.alpha_composite(avatar, (avatar_x, avatar_y))

    header_font = _font(24, bold=True)
    score_font = _font(72, bold=True)
    sub_font = _font(20, bold=False)
    _centered_text(draw, (width // 2, 70), "YORU  •  SHIP", header_font, (218, 195, 255, 255))
    _centered_text(draw, (width // 2, 220), f"{score}%", score_font, (255, 255, 255, 255))
    _centered_text(draw, (width // 2, 292), "COMPATIBILITY", sub_font, (179, 151, 217, 255))

    first_label, first_font = _fit_text(draw, first_name, 330)
    second_label, second_font = _fit_text(draw, second_name, 330)
    _centered_text(draw, (first_x + SHIP_AVATAR_SIZE // 2, 405), first_label, first_font, (246, 240, 255, 255))
    _centered_text(draw, (second_x + SHIP_AVATAR_SIZE // 2, 405), second_label, second_font, (246, 240, 255, 255))

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


class FunCog(commands.GroupCog, group_name="fun", group_description="Yoru közösségi Ship funkciója."):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.settings = ServerSettingsService(db)

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, FUN_ENABLED_KEY, FUN_DEFAULT_ENABLED)

    async def home_status(self, guild: discord.Guild) -> str:
        enabled = await self.is_enabled(guild.id)
        channel_id = await self.settings.get_int(guild.id, FUN_CHANNEL_KEY)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not enabled:
            return "🔴 Kikapcsolva"
        if isinstance(channel, discord.abc.GuildChannel):
            return f"🟢 {channel.mention}"
        return "🟢 Aktív • minden csatorna"

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.is_enabled(guild.id)
        channel_id = await self.settings.get_int(guild.id, FUN_CHANNEL_KEY)
        channel = guild.get_channel(channel_id) if channel_id else None
        embed = base_embed("💞 Yoru • Fun", "A Fun modulban a **Ship** maradt: stabil páros-százalék egy generált kétavataros képkártyán.")
        embed.add_field(name="Állapot", value="🟢 Bekapcsolva" if enabled else "🔴 Kikapcsolva", inline=True)
        embed.add_field(name="💬 Fun csatorna", value=channel.mention if isinstance(channel, discord.abc.GuildChannel) else "Bármelyik", inline=True)
        embed.add_field(name="🎮 Parancs", value="`/fun ship` • `!ship`", inline=False)
        embed.set_footer(text="Yoru • Settings • Fun")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, existing: "FunSettingsView | None" = None) -> None:
        view = FunSettingsView(
            self,
            owner_id,
            interaction.guild,
            enabled=await self.is_enabled(interaction.guild_id),
            channel_page=existing.channel_page if existing else 0,
        )
        await interaction.response.edit_message(embed=await self.settings_embed(interaction.guild), view=view)

    async def back_to_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings_cog = self.bot.get_cog("SettingsCog")
        if settings_cog is None or not hasattr(settings_cog, "show_home"):
            return await interaction.response.send_message("❌ A Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, owner_id)

    async def _gate_interaction(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Ez a parancs csak szerveren használható.", ephemeral=True)
            return False
        if not await self.is_enabled(interaction.guild.id):
            await interaction.response.send_message("❌ A **Fun** modul ki van kapcsolva ezen a szerveren.", ephemeral=True)
            return False
        channel_id = await self.settings.get_int(interaction.guild.id, FUN_CHANNEL_KEY)
        if channel_id and interaction.channel_id != channel_id:
            channel = interaction.guild.get_channel(channel_id)
            target = channel.mention if isinstance(channel, discord.abc.GuildChannel) else "a beállított Fun csatornában"
            await interaction.response.send_message(f"❌ A Shipet itt használd: {target}", ephemeral=True)
            return False
        return True

    async def _gate_ctx(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        if not await self.is_enabled(ctx.guild.id):
            await ctx.send(embed=error_embed(ctx.author, "A **Fun** modul ki van kapcsolva ezen a szerveren."))
            return False
        channel_id = await self.settings.get_int(ctx.guild.id, FUN_CHANNEL_KEY)
        if channel_id and ctx.channel.id != channel_id:
            channel = ctx.guild.get_channel(channel_id)
            target = channel.mention if isinstance(channel, discord.abc.GuildChannel) else "a beállított Fun csatornában"
            await ctx.send(embed=error_embed(ctx.author, f"A Shipet itt használd: {target}"))
            return False
        return True

    def _fallback_ship_embed(self, guild_id: int, first: discord.Member, second: discord.Member) -> discord.Embed:
        score = _ship_score(guild_id, first.id, second.id)
        embed = discord.Embed(
            title="💞 Yoru Ship",
            description=f"{first.mention}  **×**  {second.mention}\n\n# **{score}%**",
            color=BRAND,
        )
        embed.set_author(name=f"{first.display_name}  ×  {second.display_name}", icon_url=first.display_avatar.url)
        embed.set_thumbnail(url=second.display_avatar.url)
        embed.set_footer(text="Yoru • ugyanarra a párosra mindig ugyanaz a százalék")
        return embed

    async def _ship_card_file(self, guild_id: int, first: discord.Member, second: discord.Member) -> discord.File:
        if Image is None:
            raise RuntimeError("Pillow nincs telepítve")
        first_asset = first.display_avatar.replace(size=256, static_format="png")
        second_asset = second.display_avatar.replace(size=256, static_format="png")
        first_bytes, second_bytes = await asyncio.gather(first_asset.read(), second_asset.read())
        score = _ship_score(guild_id, first.id, second.id)
        card = await asyncio.to_thread(
            _build_ship_card,
            first_bytes,
            second_bytes,
            first.display_name,
            second.display_name,
            score,
        )
        return discord.File(io.BytesIO(card), filename="yoru_ship.png")

    @app_commands.command(name="ship", description="Két tag stabil kompatibilitását mutatja egy generált képkártyán.")
    async def ship_slash(self, interaction: discord.Interaction, elso: discord.Member, masodik: discord.Member | None = None) -> None:
        if not await self._gate_interaction(interaction):
            return
        second = masodik or interaction.user
        await interaction.response.defer()
        try:
            file = await self._ship_card_file(interaction.guild_id, elso, second)
            await interaction.followup.send(file=file)
        except Exception:
            await interaction.followup.send(embed=self._fallback_ship_embed(interaction.guild_id, elso, second))

    @commands.command(name="ship")
    @commands.guild_only()
    async def ship_prefix(self, ctx: commands.Context, first: discord.Member, second: discord.Member | None = None) -> None:
        if not await self._gate_ctx(ctx):
            return
        second = second or ctx.author
        try:
            file = await self._ship_card_file(ctx.guild.id, first, second)
            await ctx.send(file=file)
        except Exception:
            await ctx.send(embed=self._fallback_ship_embed(ctx.guild.id, first, second))


class FunSettingsChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "FunSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="fun_channel",
            placeholder="Ship csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=2,
            max_values=1,
        )


class FunSettingsView(OwnedView):
    def __init__(self, cog: FunCog, owner_id: int, guild: discord.Guild, *, enabled: bool, channel_page: int = 0) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.enabled = enabled
        self.channel_page = channel_page
        self.add_item(FunSettingsChannelSelect(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, self)

    async def handle_channel_selection(self, interaction: discord.Interaction, _selection_key: str, channels: list[discord.abc.GuildChannel]) -> None:
        await self.cog.settings.set_int(interaction.guild_id, FUN_CHANNEL_KEY, int(channels[0].id))
        await self.refresh(interaction)

    async def handle_role_selection(self, *_args) -> None:
        return None

    @discord.ui.button(label="Fun", emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.enabled = not self.enabled
        await self.cog.settings.set_bool(interaction.guild_id, FUN_ENABLED_KEY, self.enabled)
        await self.refresh(interaction)

    @discord.ui.button(label="Csatorna törlése", emoji="💬", style=discord.ButtonStyle.secondary, row=0)
    async def clear_channel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_int(interaction.guild_id, FUN_CHANNEL_KEY, None)
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.back_to_settings(interaction, self.owner_id)
