from __future__ import annotations

import discord
from discord.ext import commands

from app.amounts import parse_amount
from app.services.economy import CooldownError, JailError, EconomyService
from app.services.extras import ExtrasService
from app.ui import DANGER, GOLD, SUCCESS, action_embed, cooldown_embed, error_embed, money, player_embed
from app.cogs.access_utils import handle_wrong_economy_channel, handle_wrong_gambling_channel


class ExtrasPrefixCog(commands.Cog):
    def __init__(self, bot: commands.Bot, extras: ExtrasService, economy: EconomyService) -> None:
        self.bot = bot
        self.extras = extras
        self.economy = economy

    _FEATURES = {
        "weekly": "weekly", "monthly": "monthly", "interest": "interest",
        "scratch": "economy", "giveitem": "economy",
        "chickenfight": "gambling", "highlow": "gambling", "rps": "gambling",
    }

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.command is None:
            return
        feature = self._FEATURES.get(ctx.command.name)
        if feature is None:
            return

        if feature == "gambling":
            try:
                await self.economy.prepare_context(ctx.guild.id)
                await self.economy.guild_settings.require_feature(ctx.guild.id, "gambling")
            except ValueError as error:
                await ctx.send(embed=error_embed(ctx.author, str(error)))
                raise commands.CheckFailure(str(error)) from error
            try:
                await self.economy.guild_settings.require_channel(
                    ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None)
                )
            except ValueError as error:
                await handle_wrong_gambling_channel(ctx, self.economy)
                raise commands.CheckFailure(str(error)) from error
            return

        try:
            await self.economy.prepare_context(ctx.guild.id)
            await self.economy.guild_settings.require_feature(ctx.guild.id, feature)
        except ValueError as error:
            await ctx.send(embed=error_embed(ctx.author, str(error)))
            raise commands.CheckFailure(str(error)) from error
        try:
            await self.economy.guild_settings.require_channel(
                ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None)
            )
        except ValueError as error:
            await handle_wrong_economy_channel(ctx, self.economy)
            raise commands.CheckFailure(str(error)) from error

    @commands.command(name="weekly", aliases=["wk", "week"])
    @commands.guild_only()
    async def weekly(self, ctx: commands.Context) -> None:
        try: reward, ready = await self.extras.weekly(ctx.guild.id, ctx.author.id)
        except CooldownError as e: return await ctx.send(embed=cooldown_embed(ctx.author, "Weekly", e.ready_at))
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        embed = action_embed("📅 Weekly", ctx.author, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="monthly", aliases=["mo", "month"])
    @commands.guild_only()
    async def monthly(self, ctx: commands.Context) -> None:
        try: reward, ready = await self.extras.monthly(ctx.guild.id, ctx.author.id)
        except CooldownError as e: return await ctx.send(embed=cooldown_embed(ctx.author, "Monthly", e.ready_at))
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        embed = action_embed("🗓️ Monthly", ctx.author, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="interest", aliases=["int", "kamat"])
    @commands.guild_only()
    async def interest(self, ctx: commands.Context) -> None:
        try: reward, bank, ready = await self.extras.interest(ctx.guild.id, ctx.author.id)
        except CooldownError as e: return await ctx.send(embed=cooldown_embed(ctx.author, "Interest", e.ready_at))
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        embed = action_embed("🏦 Banki kamat", ctx.author, color=SUCCESS)
        embed.add_field(name="💰 Jóváírt kamat", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="scratch", aliases=["scr", "sorsjegy"])
    @commands.guild_only()
    async def scratch(self, ctx: commands.Context) -> None:
        try: label, reward, wallet = await self.extras.scratch(ctx.guild.id, ctx.author.id)
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        embed = action_embed("🎟️ Sorsjegy", ctx.author, description=f"**{label}**", color=SUCCESS if reward else GOLD)
        embed.add_field(name="💰 Nyeremény", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="giveitem", aliases=["gi", "giftitem"])
    @commands.guild_only()
    async def giveitem(self, ctx: commands.Context, member: discord.Member, item: str, quantity: int = 1) -> None:
        if member.bot: return await ctx.send(embed=error_embed(ctx.author, "Botnak nem adhatsz tárgyat."))
        try: name, emoji, qty = await self.extras.give_item(ctx.guild.id, ctx.author.id, member.id, item, quantity)
        except (ValueError, LookupError) as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        embed = action_embed("🎁 Item küldés", ctx.author, color=SUCCESS)
        embed.add_field(name="👤 Címzett", value=f"**{member.display_name}**", inline=True)
        embed.add_field(name="📦 Tárgy", value=f"**{qty}× {emoji} {name}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="chickenfight", aliases=["cock", "fight", "chicken"])
    @commands.guild_only()
    async def chickenfight(self, ctx: commands.Context, bet: str) -> None:
        cog = self.bot.get_cog("ExtrasCog")
        if cog is None:
            return await ctx.send(embed=error_embed(ctx.author, "A gambling modul nem érhető el."))
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try: parsed = parse_amount(bet, wallet)
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        await cog.run_chicken_prefix(ctx, parsed)

    @commands.command(name="highlow", aliases=["hl"])
    @commands.guild_only()
    async def highlow(self, ctx: commands.Context, first: str, second: str | None = None) -> None:
        cog = self.bot.get_cog("ExtrasCog")
        if cog is None:
            return await ctx.send(embed=error_embed(ctx.author, "A gambling modul nem érhető el."))
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        bet_text = first if second is None else second
        # Backwards compatibility: `!hl high 100k` still opens the new button-based game.
        if second is not None:
            try:
                parse_amount(first, wallet)
                bet_text = first
            except ValueError:
                bet_text = second
        try: parsed = parse_amount(bet_text, wallet)
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        await cog.start_highlow_prefix(ctx, parsed)

    @commands.command(name="rps", aliases=["kpo"])
    @commands.guild_only()
    async def rps(self, ctx: commands.Context, first: str, second: str) -> None:
        cog = self.bot.get_cog("ExtrasCog")
        if cog is None:
            return await ctx.send(embed=error_embed(ctx.author, "A gambling modul nem érhető el."))
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        choices = {"rock", "r", "ko", "kő", "paper", "p", "papir", "papír", "scissors", "s", "ollo", "olló"}
        first_norm = first.lower().strip(); second_norm = second.lower().strip()
        if first_norm in choices: choice, bet = first, second
        elif second_norm in choices: choice, bet = second, first
        else: return await ctx.send(embed=error_embed(ctx.author, "Használat: `!rps rock 25k` vagy `!rps 25k rock`."))
        try: parsed = parse_amount(bet, wallet)
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        await cog.run_rps_prefix(ctx, choice, parsed)

