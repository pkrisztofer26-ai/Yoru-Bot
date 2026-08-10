from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.services.economy import CooldownError, JailError
from app.services.extras import ExtrasService
from app.amounts import parse_amount
from app.ui import DANGER, GOLD, SUCCESS, action_embed, cooldown_embed, error_embed, money, player_embed


class ExtrasCog(commands.Cog):
    def __init__(self, bot: commands.Bot, extras: ExtrasService) -> None:
        self.bot = bot
        self.extras = extras

    @app_commands.command(name="weekly", description="Átveszed a heti economy jutalmadat.")
    async def weekly(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        try: reward, ready = await self.extras.weekly(interaction.guild_id, interaction.user.id)
        except CooldownError as e: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Weekly", e.ready_at), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("📅 Weekly", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="monthly", description="Átveszed a havi economy jutalmadat.")
    async def monthly(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        try: reward, ready = await self.extras.monthly(interaction.guild_id, interaction.user.id)
        except CooldownError as e: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Monthly", e.ready_at), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("🗓️ Monthly", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="interest", description="Banki kamatot veszel fel 6 óránként.")
    async def interest(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        try: reward, bank, ready = await self.extras.interest(interaction.guild_id, interaction.user.id)
        except CooldownError as e: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Interest", e.ready_at), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("🏦 Banki kamat", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jóváírt kamat", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready.timestamp())}:R>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="scratch", description="Felhasználsz egy Sorsjegyet.")
    async def scratch(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        try: label, reward, wallet = await self.extras.scratch(interaction.guild_id, interaction.user.id)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        embed = action_embed("🎟️ Sorsjegy", interaction.user, description=f"**{label}**", color=SUCCESS if reward else GOLD)
        embed.add_field(name="💰 Nyeremény", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="giveitem", description="Tárgyat adsz egy másik tagnak.")
    async def giveitem(self, interaction: discord.Interaction, member: discord.Member, item: str, mennyiseg: app_commands.Range[int, 1, 1000] = 1) -> None:
        if interaction.guild_id is None: return
        if member.bot: return await interaction.response.send_message(embed=error_embed(interaction.user, "Botnak nem adhatsz tárgyat."), ephemeral=True)
        try: name, emoji, qty = await self.extras.give_item(interaction.guild_id, interaction.user.id, member.id, item, mennyiseg)
        except (ValueError, LookupError) as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        await interaction.response.send_message(f"🎁 {interaction.user.mention} adott {member.mention} részére **{qty}× {emoji} {name}** tárgyat.")

    @app_commands.command(name="chickenfight", description="A Chickened harcol egy random ellenféllel pénztétért.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def chickenfight(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None: return
        current_wallet, _ = await self.extras.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, current_wallet)
            won, opponent, amount, wallet = await self.extras.chickenfight(interaction.guild_id, interaction.user.id, tet)
        except JailError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
        except ValueError as e: return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        color = SUCCESS if won else DANGER
        embed = player_embed("🐔 Chicken Fight", interaction.user, color=color)
        embed.add_field(name="⚔️ Ellenfél", value=f"**{opponent}**", inline=False)
        payout = tet + amount if won else 0
        embed.add_field(name="🎟️ Tét", value=f"**{money(tet)}**", inline=True)
        embed.add_field(name="Eredmény", value=(f"✅ **+{money(amount)}**" if won else f"❌ **-{money(amount)}**"), inline=True)
        embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="highlow", description="Tippeld meg, 7-nél magasabb vagy alacsonyabb lap jön-e.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def highlow(self, interaction: discord.Interaction, tipp: str, osszeg: str) -> None:
        if interaction.guild_id is None: return
        current_wallet, _ = await self.extras.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, current_wallet)
            card, result, amount, wallet = await self.extras.highlow(interaction.guild_id, interaction.user.id, tipp, tet)
        except (JailError, ValueError) as e:
            if isinstance(e, JailError): return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        color = GOLD if result == "tie" else (SUCCESS if result == "win" else DANGER)
        embed = player_embed("🃏 High / Low", interaction.user, description=f"A húzott lap: **{card}**", color=color)
        embed.add_field(name="🎯 Tipp", value=f"**{tipp.title()}**", inline=True)
        embed.add_field(name="🎟️ Tét", value=f"**{money(tet)}**", inline=True)
        result_text = "🤝 **$0**" if result == "tie" else (f"✅ **+{money(amount)}**" if result == "win" else f"❌ **-{money(amount)}**")
        payout = tet if result == "tie" else (tet + amount if result == "win" else 0)
        embed.add_field(name="Eredmény", value=result_text, inline=True)
        embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rps", description="Kő-papír-olló pénztétért a bot ellen.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def rps(self, interaction: discord.Interaction, valasztas: str, osszeg: str) -> None:
        if interaction.guild_id is None: return
        current_wallet, _ = await self.extras.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            tet = parse_amount(osszeg, current_wallet)
            player, bot, profit, wallet = await self.extras.rps(interaction.guild_id, interaction.user.id, valasztas, tet)
        except (JailError, ValueError) as e:
            if isinstance(e, JailError): return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(e.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(e)), ephemeral=True)
        icons = {"rock":"🪨","paper":"📄","scissors":"✂️"}
        color = GOLD if profit == 0 else (SUCCESS if profit > 0 else DANGER)
        embed = player_embed("✂️ Kő • Papír • Olló", interaction.user, color=color)
        embed.add_field(name="Te", value=f"{icons[player]} **{player.title()}**", inline=True)
        embed.add_field(name="Yoru", value=f"{icons[bot]} **{bot.title()}**", inline=True)
        embed.add_field(name="🎟️ Tét", value=f"**{money(tet)}**", inline=True)
        result = "🤝 **Döntetlen • $0**" if profit == 0 else (f"✅ **+{money(profit)}**" if profit > 0 else f"❌ **-{money(abs(profit))}**")
        payout = tet + profit if profit >= 0 else 0
        embed.add_field(name="Eredmény", value=result, inline=True)
        embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
        embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
        await interaction.response.send_message(embed=embed)
