from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.services.economy import CooldownError
from app.amounts import parse_amount
from app.services.progression import ACHIEVEMENTS, ProgressionService
from app.ui import DANGER, GOLD, SUCCESS, action_embed, base_embed, cooldown_embed, error_embed, money, progress_bar
from app.profile_ui import make_profile_view


class ProgressionCog(commands.Cog):
    def __init__(self, bot: commands.Bot, progression: ProgressionService) -> None:
        self.bot = bot
        self.progression = progression

    @app_commands.command(name="achievements", description="Megmutatja az achievementjeidet.")
    async def achievements_slash(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return
        target = member or interaction.user
        embed, view = await make_profile_view(self.bot, interaction.guild_id, target, interaction.user.id, initial_page="achievements")
        await interaction.response.send_message(embed=embed, view=view)

    @commands.command(name="achievements", aliases=["ach"])
    @commands.guild_only()
    async def achievements_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        embed, view = await make_profile_view(self.bot, ctx.guild.id, target, ctx.author.id, initial_page="achievements")
        await ctx.send(embed=embed, view=view)

    @app_commands.command(name="badges", description="Megmutatja a feloldott badge-eket.")
    async def badges_slash(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return
        target = member or interaction.user
        embed, view = await make_profile_view(self.bot, interaction.guild_id, target, interaction.user.id, initial_page="badges")
        await interaction.response.send_message(embed=embed, view=view)

    @commands.command(name="badges", aliases=["badge"])
    @commands.guild_only()
    async def badges_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        embed, view = await make_profile_view(self.bot, ctx.guild.id, target, ctx.author.id, initial_page="badges")
        await ctx.send(embed=embed, view=view)

    @app_commands.command(name="titles", description="Megmutatja a feloldott profilcímeidet.")
    async def titles_slash(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return
        target = member or interaction.user
        embed, view = await make_profile_view(self.bot, interaction.guild_id, target, interaction.user.id, initial_page="titles")
        await interaction.response.send_message(embed=embed, view=view)

    @commands.command(name="titles", aliases=["cimek", "ttl"])
    @commands.guild_only()
    async def titles_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        embed, view = await make_profile_view(self.bot, ctx.guild.id, target, ctx.author.id, initial_page="titles")
        await ctx.send(embed=embed, view=view)

    @app_commands.command(name="title", description="Profilcím kiválasztása.")
    async def title_slash(self, interaction: discord.Interaction, cim: str) -> None:
        if interaction.guild_id is None:
            return
        try:
            selected = await self.progression.choose_title(interaction.guild_id, interaction.user.id, cim)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🎖️ Profilcím", interaction.user, color=SUCCESS)
        embed.add_field(name="Aktív cím", value=f"**{selected}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="title", aliases=["cim", "settitle"])
    @commands.guild_only()
    async def title_prefix(self, ctx: commands.Context, *, title: str) -> None:
        try:
            selected = await self.progression.choose_title(ctx.guild.id, ctx.author.id, title)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = action_embed("🎖️ Profilcím", ctx.author, color=SUCCESS)
        embed.add_field(name="Aktív cím", value=f"**{selected}**", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="boosters", description="Megmutatja az aktív boostereidet.")
    async def boosters_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        rows = await self.progression.active_boosters(interaction.guild_id, interaction.user.id)
        desc = "\n".join(f"⚡ **{bid}** • x{mult:.2f} • <t:{int(exp.timestamp())}:R>" for bid, mult, exp in rows) or "Nincs aktív boostered."
        await interaction.response.send_message(embed=base_embed("⚡ Aktív boosterek", desc), ephemeral=True)

    @commands.command(name="boosters", aliases=["boost", "bst"])
    @commands.guild_only()
    async def boosters_prefix(self, ctx: commands.Context) -> None:
        rows = await self.progression.active_boosters(ctx.guild.id, ctx.author.id)
        desc = "\n".join(f"⚡ **{bid}** • x{mult:.2f} • <t:{int(exp.timestamp())}:R>" for bid, mult, exp in rows) or "Nincs aktív boostered."
        await ctx.send(embed=base_embed("⚡ Aktív boosterek", desc))

    @app_commands.command(name="banklevel", description="Megmutatja a bankod szintjét és kamatát.")
    async def banklevel_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        level, rate, cap = await self.progression.bank_level(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(embed=base_embed("🏦 Bank szint", f"**Szint:** {level}/5\n**Kamat / igénylés:** {rate*100:.2f}%\n**Kamatplafon / igénylés:** {money(cap)}"), ephemeral=True)

    @commands.command(name="banklevel", aliases=["bl", "banklvl"])
    @commands.guild_only()
    async def banklevel_prefix(self, ctx: commands.Context) -> None:
        level, rate, cap = await self.progression.bank_level(ctx.guild.id, ctx.author.id)
        await ctx.send(embed=base_embed("🏦 Bank szint", f"**Szint:** {level}/5\n**Kamat / igénylés:** {rate*100:.2f}%\n**Kamatplafon / igénylés:** {money(cap)}"))

    @app_commands.command(name="invest", description="Pénz befektetése low/medium/high kockázattal.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def invest_slash(self, interaction: discord.Interaction, kockazat: str, osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        current_wallet, _ = await self.progression.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            parsed = parse_amount(osszeg, current_wallet)
            profit, wallet, ready, label = await self.progression.invest(interaction.guild_id, interaction.user.id, kockazat, parsed)
        except CooldownError as error:
            return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Befektetés", error.ready_at), ephemeral=True)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        sign = "+" if profit >= 0 else "-"
        embed = action_embed("📈 Befektetés", interaction.user, color=SUCCESS if profit >= 0 else DANGER)
        embed.add_field(name="⚖️ Kockázat", value=f"**{label}**", inline=True)
        embed.add_field(name="📊 Eredmény", value=f"**{sign}{money(abs(profit))}**", inline=True)
        embed.add_field(name="💰 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=False)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="invest", aliases=["invst", "befektet"])
    @commands.guild_only()
    async def invest_prefix(self, ctx: commands.Context, risk: str, amount: str) -> None:
        wallet, _ = await self.progression.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed = parse_amount(amount, wallet)
            profit, wallet, ready, label = await self.progression.invest(ctx.guild.id, ctx.author.id, risk, parsed)
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Befektetés", error.ready_at))
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        sign = "+" if profit >= 0 else "-"
        embed = action_embed("📈 Befektetés", ctx.author, color=SUCCESS if profit >= 0 else DANGER)
        embed.add_field(name="⚖️ Kockázat", value=f"**{label}**", inline=True)
        embed.add_field(name="📊 Eredmény", value=f"**{sign}{money(abs(profit))}**", inline=True)
        embed.add_field(name="💰 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=False)
        await ctx.send(embed=embed)
