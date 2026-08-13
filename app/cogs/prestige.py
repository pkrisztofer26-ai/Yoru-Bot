from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.services.prestige import PrestigeResult, PrestigeService, PrestigeState
from app.ui import BRAND, GOLD, SUCCESS, error_embed, money, progress_bar


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


async def build_prestige_embed(service: PrestigeService, guild_id: int, user: discord.abc.User) -> tuple[discord.Embed, PrestigeState]:
    state = await service.state(guild_id, user.id)
    embed = discord.Embed(title="🌌 Prestige", color=GOLD if state.eligible else BRAND)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)

    current_rank = f"P{state.rank}" if state.rank else "Nincs"
    embed.description = (
        f"**Jelenlegi prestige:** {current_rank}\n"
        f"**Állandó income bónusz:** +{_percent(state.income_bonus)}\n"
        f"-# Maximum bónusz: +{_percent(state.income_bonus_cap)}"
    )

    level_progress = progress_bar(state.current_level, state.required_level, 12)
    wealth_progress = progress_bar(state.current_wealth, state.required_wealth, 12)
    embed.add_field(
        name=f"🌠 Következő: Prestige {state.rank + 1}",
        value=(
            f"⭐ Level: `{level_progress}` **{state.current_level}/{state.required_level}**\n"
            f"💎 Vagyon: `{wealth_progress}` **{money(state.current_wealth)} / {money(state.required_wealth)}**\n"
            f"🚀 Új income bónusz: **+{_percent(state.next_income_bonus)}**"
        ),
        inline=False,
    )

    embed.add_field(
        name="♻️ Ami nullázódik",
        value=(
            "• Tárca és bank\n"
            "• Progression level / XP\n"
            "• Nem-prémium inventory itemek\n"
            "• Aktív boosterek"
        ),
        inline=True,
    )
    embed.add_field(
        name="🛡️ Ami megmarad",
        value=(
            "• Lifetime statok\n"
            "• Achievementek / badge-ek\n"
            "• Profilcímek\n"
            "• Prémium reward itemek\n"
            "• Quest állapot / cooldownok"
        ),
        inline=True,
    )

    if state.total_wealth_sacrificed:
        embed.add_field(
            name="🕯️ Lifetime prestige",
            value=f"Feláldozott vagyon: **{money(state.total_wealth_sacrificed)}**",
            inline=False,
        )
    if state.last_prestige_at:
        embed.add_field(name="🕒 Legutóbbi prestige", value=f"<t:{int(state.last_prestige_at.timestamp())}:R>", inline=False)

    if state.eligible:
        embed.set_footer(text="Yoru • Készen állsz. A prestige végleges, a gomb megerősítést jelent.")
    else:
        embed.set_footer(text="Yoru • Teljesítsd mindkét követelményt a következő prestige-hez.")
    return embed, state


def build_prestige_success(user: discord.abc.User, result: PrestigeResult, unlocks: list[str]) -> discord.Embed:
    embed = discord.Embed(title=f"🌌 Prestige {result.new_rank} elérve", color=SUCCESS)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.description = (
        f"♻️ **Új ciklus indult.**\n"
        f"💎 Feláldozott vagyon: **{money(result.wealth_sacrificed)}**\n"
        f"🚀 Állandó income bónusz: **+{_percent(result.income_bonus)}**"
    )
    embed.add_field(name="🎒 Törölt itemek", value=f"**{result.removed_items} db**", inline=True)
    embed.add_field(name="⚡ Törölt boosterek", value=f"**{result.removed_boosters} db**", inline=True)
    if unlocks:
        embed.add_field(name="🏆 Új achievement", value="\n".join(f"• {name}" for name in unlocks), inline=False)
    embed.set_footer(text="Yoru • A prémium reward itemek és lifetime progression megmaradtak.")
    return embed


class PrestigeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, service: PrestigeService, guild_id: int, user: discord.abc.User, eligible: bool) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.service = service
        self.guild_id = guild_id
        self.user = user
        self.confirm.disabled = not eligible

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Ezt a prestige panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Prestige végrehajtása", emoji="🌌", style=discord.ButtonStyle.danger, custom_id="yoru_prestige_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.disabled = True
        try:
            result = await self.service.prestige(self.guild_id, self.user.id)
        except ValueError as error:
            refreshed, state = await build_prestige_embed(self.service, self.guild_id, self.user)
            self.confirm.disabled = not state.eligible
            await interaction.response.edit_message(embed=refreshed, view=self)
            await interaction.followup.send(embed=error_embed(self.user, str(error)), ephemeral=True)
            return

        newly_unlocked = await self.bot.progression.sync_achievements(self.guild_id, self.user.id)
        names: list[str] = []
        from app.services.progression import ACHIEVEMENTS
        for achievement_id in newly_unlocked:
            definition = ACHIEVEMENTS.get(achievement_id)
            if definition:
                names.append(definition[0])
        await interaction.response.edit_message(embed=build_prestige_success(self.user, result, names), view=None)
        self.stop()

    @discord.ui.button(label="Mégse", emoji="✖️", style=discord.ButtonStyle.secondary, custom_id="yoru_prestige_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed, _ = await build_prestige_embed(self.service, self.guild_id, self.user)
        embed.set_footer(text="Yoru • Prestige megszakítva.")
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


class PrestigeCog(commands.Cog):
    def __init__(self, bot: commands.Bot, service: PrestigeService) -> None:
        self.bot = bot
        self.service = service

    @app_commands.command(name="prestige", description="Prestige állapot és endgame újraindítás.")
    async def prestige_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        embed, state = await build_prestige_embed(self.service, interaction.guild_id, interaction.user)
        view = PrestigeView(self.bot, self.service, interaction.guild_id, interaction.user, state.eligible)
        await interaction.response.send_message(embed=embed, view=view)

    @commands.command(name="prestige", aliases=["rebirth", "ascend"])
    @commands.guild_only()
    async def prestige_prefix(self, ctx: commands.Context) -> None:
        embed, state = await build_prestige_embed(self.service, ctx.guild.id, ctx.author)
        view = PrestigeView(self.bot, self.service, ctx.guild.id, ctx.author, state.eligible)
        await ctx.send(embed=embed, view=view)

    @app_commands.command(name="prestigetop", description="Prestige ranglista.")
    async def prestigetop_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        await interaction.response.send_message(embed=await self._leaderboard_embed(interaction.guild, interaction.user))

    @commands.command(name="prestigetop", aliases=["ptop", "prestigelb"])
    @commands.guild_only()
    async def prestigetop_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await self._leaderboard_embed(ctx.guild, ctx.author))

    async def _leaderboard_embed(self, guild: discord.Guild, requester: discord.abc.User) -> discord.Embed:
        rows = await self.service.leaderboard(guild.id, 10)
        embed = discord.Embed(title="🌌 Prestige ranglista", color=GOLD)
        embed.set_author(name=requester.display_name, icon_url=requester.display_avatar.url)
        if not rows:
            embed.description = "Még senki sem prestige-elt ezen a szerveren."
            return embed
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, (user_id, rank, sacrificed) in enumerate(rows, start=1):
            member = guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            prefix = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
            lines.append(f"{prefix} **{name}** • P{rank} • {money(sacrificed)} feláldozva")
        embed.description = "\n".join(lines)
        embed.set_footer(text="Yoru • Prestige leaderboard")
        return embed
