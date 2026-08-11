from __future__ import annotations

import hashlib

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.database import Database
from app.fun_config import FUN_CHANNEL_KEY, FUN_DEFAULT_ENABLED, FUN_ENABLED_KEY
from app.services.server_settings import ServerSettingsService
from app.ui import BRAND, base_embed, error_embed


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


def _ship_verdict(score: int) -> tuple[str, int]:
    if score <= 9:
        return "🚨 Katasztrófa", 0xED4245
    if score <= 29:
        return "💔 Nem az igazi", 0xED4245
    if score <= 49:
        return "😬 Van mit dolgozni", 0xFEE75C
    if score <= 69:
        return "💗 Van benne valami", 0xEB459E
    if score <= 84:
        return "💕 Nagyon működik", 0xEB459E
    if score <= 96:
        return "💘 Power couple", 0xF47FFF
    return "💍 Végzet", 0xF7B2FF


def _ship_bar(score: int) -> str:
    filled = max(0, min(10, round(score / 10)))
    return "▰" * filled + "▱" * (10 - filled)


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
        embed = base_embed("💞 Yoru • Fun", "A Fun modul letisztítva: jelenleg a **Ship 2.0** maradt benne.")
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

    def _ship_embed(self, guild_id: int, first: discord.Member, second: discord.Member) -> discord.Embed:
        low, high = sorted((first.id, second.id))
        score = 100 if first.id == second.id else _stable_percent(guild_id, low, high, "ship")
        verdict, color = _ship_verdict(score)
        bar = _ship_bar(score)

        embed = discord.Embed(
            title="💞 Yoru Ship 2.0",
            description=f"{first.mention}  **×**  {second.mention}",
            color=color,
        )
        embed.set_author(name=f"{first.display_name}  ×  {second.display_name}", icon_url=first.display_avatar.url)
        embed.set_thumbnail(url=second.display_avatar.url)
        embed.add_field(name="💘 Kompatibilitás", value=f"# **{score}%**", inline=True)
        embed.add_field(name="🔮 Ítélet", value=f"**{verdict}**", inline=True)
        embed.add_field(name="❤️ Ship meter", value=f"`{bar}`\n**{score}/100**", inline=False)
        if score >= 90:
            embed.add_field(name="✨ Yoru szerint", value="Ezt már nehéz lenne véletlennek nevezni.", inline=False)
        elif score >= 70:
            embed.add_field(name="✨ Yoru szerint", value="Itt azért rendesen megvan a kémia.", inline=False)
        elif score >= 50:
            embed.add_field(name="✨ Yoru szerint", value="Van potenciál. A többit intézzétek ti.", inline=False)
        elif score >= 30:
            embed.add_field(name="✨ Yoru szerint", value="Nem reménytelen, csak erős fejlesztés kell.", inline=False)
        else:
            embed.add_field(name="✨ Yoru szerint", value="Ezt inkább ne erőltessük. 💀", inline=False)
        embed.set_footer(text="Yoru • Ship eredmény ugyanarra a párosra mindig stabil")
        return embed

    @app_commands.command(name="ship", description="Két tag kompatibilitását méri egy szebb Ship 2.0 kártyán.")
    async def ship_slash(self, interaction: discord.Interaction, elso: discord.Member, masodik: discord.Member | None = None) -> None:
        if not await self._gate_interaction(interaction):
            return
        second = masodik or interaction.user
        await interaction.response.send_message(embed=self._ship_embed(interaction.guild_id, elso, second))

    @commands.command(name="ship")
    @commands.guild_only()
    async def ship_prefix(self, ctx: commands.Context, first: discord.Member, second: discord.Member | None = None) -> None:
        if not await self._gate_ctx(ctx):
            return
        second = second or ctx.author
        await ctx.send(embed=self._ship_embed(ctx.guild.id, first, second))


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
