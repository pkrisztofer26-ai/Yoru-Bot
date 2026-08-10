from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from app.help_ui import make_help_view


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help", aliases=["h", "commands", "cmds", "parancsok"])
    async def help_prefix(self, ctx: commands.Context) -> None:
        embed, view = make_help_view(ctx.author)
        view.message = await ctx.send(embed=embed, view=view)

    @app_commands.command(name="help", description="Interaktív Yoru parancs- és súgómenü.")
    async def help_slash(self, interaction: discord.Interaction) -> None:
        embed, view = make_help_view(interaction.user)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
    @staticmethod
    def _version() -> str:
        try:
            return Path("VERSION").read_text(encoding="utf-8").strip() or "ismeretlen"
        except OSError:
            return "ismeretlen"

    @commands.command(name="version", aliases=["ver", "v"])
    async def version_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(f"🌙 **Yoru v{self._version()}**")

    @app_commands.command(name="version", description="Megmutatja a jelenleg futó Yoru verziót.")
    async def version_slash(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"🌙 **Yoru v{self._version()}**", ephemeral=True)

