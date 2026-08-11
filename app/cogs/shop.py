from __future__ import annotations

from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from app.services.shop import ShopService
from app.ui import base_embed, money
from app.shop_ui import build_shop_view
from app.profile_ui import make_profile_view
from app import economy_config as eco

RARITY = {"common":"⚪ Common","rare":"🔵 Rare","epic":"🟣 Epic","legendary":"🟡 Legendary","mythic":"🔴 Mythic"}
CATEGORY = {
    "game":"🎮 Játék",
    "market":"📈 Napi piac",
    "lootbox":"📦 Ládák",
    "booster":"⚡ Boosterek",
    "utility":"🧰 Utility",
    "reward":"🎁 Prémium jutalmak",
}


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot, shop: ShopService) -> None:
        self.bot = bot
        self.shop = shop

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return False
        try:
            await self.bot.economy.require_access(interaction.guild_id, "economy", interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return False
        return True

    @app_commands.command(name="shop", description="Megnyitja az interaktív Yoru Store-t.")
    async def shop_command(self, interaction: discord.Interaction, kategoria: str | None = None) -> None:
        if interaction.guild_id is None:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)
        if not await self._guard(interaction): return
        view = await build_shop_view(self.shop, interaction.guild_id, category=kategoria)
        await interaction.response.send_message(view=view)

    @app_commands.command(name="buy", description="Tárgy vásárlása a shopból.")
    async def buy(self, interaction: discord.Interaction, item: str, mennyiseg: app_commands.Range[int, 1, 100] = 1) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction): return
        try:
            name, emoji, total_price, new_wallet, stock = await self.shop.buy(interaction.guild_id, interaction.user.id, item, mennyiseg)
        except (ValueError, LookupError) as error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        if item.lower().strip() in eco.PREMIUM_REWARD_RULES and stock is not None:
            stock_text = f"\n🎁 Havi szerverkészlet: **{stock} db**"
        else:
            stock_text = f"\n📦 Mai készlet: **{stock} db**" if stock is not None else ""
        await interaction.response.send_message(f"✅ **{mennyiseg}× {emoji} {name}** • {money(total_price)}\n💰 Maradék: **{money(new_wallet)}**{stock_text}")

    @app_commands.command(name="sell", description="Tárgy eladása. A napi piaci tárgyak az aktuális ár 90%-án válthatók vissza.")
    async def sell(self, interaction: discord.Interaction, item: str, mennyiseg: app_commands.Range[int, 1, 100] = 1) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction): return
        try:
            name, emoji, value, wallet, stock = await self.shop.sell(interaction.guild_id, interaction.user.id, item, mennyiseg)
        except (ValueError, LookupError) as error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        stock_text = f"\n📦 Mai készlet: **{stock} db**" if stock is not None else ""
        await interaction.response.send_message(f"💱 **{mennyiseg}× {emoji} {name}** eladva • {money(value)}\n💰 Tárca: **{money(wallet)}**{stock_text}")

    @app_commands.command(name="use", description="Láda vagy booster használata.")
    async def use(self, interaction: discord.Interaction, item: str) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction): return
        try: label, reward, extra = await self.shop.use(interaction.guild_id, interaction.user.id, item)
        except ValueError as error: return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        if reward:
            embed = base_embed("📦 Láda kinyitva", f"Ritkaság: **{label}**\nJutalom: **{money(reward)}**\n{extra}")
        else:
            embed = base_embed("⚡ Booster aktiválva", f"**{label}**\n{extra}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inventory", description="Megnyitja egy felhasználó interaktív inventoryját.")
    async def inventory(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction): return
        target = member or interaction.user
        embed, view = await make_profile_view(self.bot, interaction.guild_id, target, interaction.user.id, initial_page="inventory")
        await interaction.response.send_message(embed=embed, view=view)
