from __future__ import annotations

import discord
from discord.ext import commands

from app.amounts import parse_amount
from app.services.economy import CooldownError, JailError, EconomyService
from app.services.extras import ExtrasService
from app.ui import DANGER, GOLD, SUCCESS, action_embed, cooldown_embed, error_embed, money, player_embed


class ExtrasPrefixCog(commands.Cog):
    def __init__(self, bot: commands.Bot, extras: ExtrasService, economy: EconomyService) -> None:
        self.bot = bot
        self.extras = extras
        self.economy = economy

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
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed = parse_amount(bet, wallet)
            won, opponent, amount, wallet = await self.extras.chickenfight(ctx.guild.id, ctx.author.id, parsed)
        except JailError as e: return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        embed = player_embed("🐔 Chicken Fight", ctx.author, color=SUCCESS if won else DANGER)
        embed.add_field(name="⚔️ Ellenfél", value=f"**{opponent}**", inline=False)
        payout = parsed + amount if won else 0
        embed.add_field(name="🎟️ Tét", value=f"**{money(parsed)}**", inline=True)
        embed.add_field(name="Eredmény", value=(f"✅ **+{money(amount)}**" if won else f"❌ **-{money(amount)}**"), inline=True)
        embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="highlow", aliases=["hl"])
    @commands.guild_only()
    async def highlow(self, ctx: commands.Context, choice: str, bet: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed = parse_amount(bet, wallet)
            card, result, amount, wallet = await self.extras.highlow(ctx.guild.id, ctx.author.id, choice, parsed)
        except JailError as e: return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        color = GOLD if result == "tie" else (SUCCESS if result == "win" else DANGER)
        embed = player_embed("🃏 High / Low", ctx.author, description=f"A húzott lap: **{card}**", color=color)
        embed.add_field(name="🎯 Tipp", value=f"**{choice.title()}**", inline=True)
        embed.add_field(name="🎟️ Tét", value=f"**{money(parsed)}**", inline=True)
        result_text = "🤝 **$0**" if result == "tie" else (f"✅ **+{money(amount)}**" if result == "win" else f"❌ **-{money(amount)}**")
        payout = parsed if result == "tie" else (parsed + amount if result == "win" else 0)
        embed.add_field(name="Eredmény", value=result_text, inline=True)
        embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="rps", aliases=["kpo"])
    @commands.guild_only()
    async def rps(self, ctx: commands.Context, first: str, second: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        choices = {"rock", "r", "ko", "kő", "paper", "p", "papir", "papír", "scissors", "s", "ollo", "olló"}
        first_norm = first.lower().strip()
        second_norm = second.lower().strip()
        if first_norm in choices:
            choice, bet = first, second
        elif second_norm in choices:
            choice, bet = second, first
        else:
            return await ctx.send(embed=error_embed(ctx.author, "Használat: `!rps rock 25k` vagy `!rps 25k rock`."))
        try:
            parsed = parse_amount(bet, wallet)
            player, bot, profit, wallet = await self.extras.rps(ctx.guild.id, ctx.author.id, choice, parsed)
        except JailError as e: return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except ValueError as e: return await ctx.send(embed=error_embed(ctx.author, str(e)))
        icons = {"rock":"🪨","paper":"📄","scissors":"✂️"}
        color = GOLD if profit == 0 else (SUCCESS if profit > 0 else DANGER)
        embed = player_embed("✂️ Kő • Papír • Olló", ctx.author, color=color)
        embed.add_field(name="Te", value=f"{icons[player]} **{player.title()}**", inline=True)
        embed.add_field(name="Yoru", value=f"{icons[bot]} **{bot.title()}**", inline=True)
        embed.add_field(name="🎟️ Tét", value=f"**{money(parsed)}**", inline=True)
        result_text = "🤝 **Döntetlen • $0**" if profit == 0 else (f"✅ **+{money(profit)}**" if profit > 0 else f"❌ **-{money(abs(profit))}**")
        payout = parsed + profit if profit >= 0 else 0
        embed.add_field(name="Eredmény", value=result_text, inline=True)
        embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
        await ctx.send(embed=embed)
