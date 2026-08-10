from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.services.quests import QuestProgress, QuestService
from app.ui import BRAND, SUCCESS, error_embed, money, progress_bar


PERIOD_LABELS = {
    "daily": ("☀️", "Napi küldetések"),
    "weekly": ("📅", "Heti küldetések"),
}
ITEM_LABELS = {
    "lottery_ticket": "🎟️ Sorsjegy",
    "common_crate": "📦 Common Láda",
    "rare_crate": "🔷 Rare Láda",
    "work_booster": "🛠️ Work Booster",
    "crime_booster": "🕵️ Crime Booster",
}


def normalize_period(value: str) -> str:
    aliases = {
        "daily": "daily", "d": "daily", "napi": "daily",
        "weekly": "weekly", "w": "weekly", "heti": "weekly",
    }
    period = aliases.get(value.lower().strip())
    if period is None:
        raise ValueError("Periódus: `daily` vagy `weekly`.")
    return period


def _quest_line(quest: QuestProgress) -> str:
    definition = quest.definition
    if quest.claimed:
        state = "✅ **Átvéve**"
    elif quest.completed:
        state = "🎁 **Átvehető**"
    else:
        state = f"`{progress_bar(quest.progress, quest.target, 10)}` **{quest.progress}/{quest.target}**"
    rewards = f"💰 **{money(definition.reward_xp)}**"
    if definition.reward_item:
        rewards += f" + {ITEM_LABELS.get(definition.reward_item, f'`{definition.reward_item}`')}"
    return (
        f"{definition.emoji} **{quest.slot}. {definition.title}**\n"
        f"{definition.description}\n"
        f"{state}\n"
        f"-# Jutalom: {rewards}"
    )


async def build_quest_embed(service: QuestService, guild_id: int, user: discord.abc.User, period: str) -> discord.Embed:
    quests = await service.get_quests(guild_id, user.id, period)
    emoji, label = PERIOD_LABELS[period]
    embed = discord.Embed(title=f"{emoji} {label}", color=BRAND)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.description = "\n\n".join(_quest_line(quest) for quest in quests)
    completed = sum(1 for quest in quests if quest.completed)
    claimed = sum(1 for quest in quests if quest.claimed)
    reset_at = service.reset_at(period)
    embed.set_footer(text=f"Yoru • Kész: {completed}/{len(quests)} • Átvéve: {claimed}/{len(quests)}")
    embed.add_field(name="⏳ Frissül", value=f"<t:{int(reset_at.timestamp())}:R>", inline=False)
    return embed


class QuestView(discord.ui.View):
    def __init__(self, service: QuestService, guild_id: int, user: discord.abc.User, requester_id: int, period: str = "daily") -> None:
        super().__init__(timeout=300)
        self.service = service
        self.guild_id = guild_id
        self.user = user
        self.requester_id = requester_id
        self.period = period
        self._sync_styles()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ezt a quest panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    def _sync_styles(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "yoru_quest_daily":
                item.style = discord.ButtonStyle.primary if self.period == "daily" else discord.ButtonStyle.secondary
            elif item.custom_id == "yoru_quest_weekly":
                item.style = discord.ButtonStyle.primary if self.period == "weekly" else discord.ButtonStyle.secondary

    @discord.ui.button(label="Napi", emoji="☀️", style=discord.ButtonStyle.primary, custom_id="yoru_quest_daily")
    async def daily(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.period = "daily"
        self._sync_styles()
        await interaction.response.edit_message(embed=await build_quest_embed(self.service, self.guild_id, self.user, self.period), view=self)

    @discord.ui.button(label="Heti", emoji="📅", style=discord.ButtonStyle.secondary, custom_id="yoru_quest_weekly")
    async def weekly(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.period = "weekly"
        self._sync_styles()
        await interaction.response.edit_message(embed=await build_quest_embed(self.service, self.guild_id, self.user, self.period), view=self)

    @discord.ui.button(label="Jutalmak átvétele", emoji="🎁", style=discord.ButtonStyle.success, custom_id="yoru_quest_claim_all")
    async def claim_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        total_xp, items, count = await self.service.claim_all(self.guild_id, self.user.id, self.period)
        if count == 0:
            await interaction.response.send_message("ℹ️ Nincs átvehető quest jutalmad ezen az oldalon.", ephemeral=True)
            return
        item_text = ""
        if items:
            item_text = "\n" + "\n".join(f"• {ITEM_LABELS.get(item, item)}" for item in items)
        await interaction.response.edit_message(embed=await build_quest_embed(self.service, self.guild_id, self.user, self.period), view=self)
        await interaction.followup.send(f"✅ **{count}** quest jutalom átvéve • **{money(total_xp)}**{item_text}", ephemeral=True)


class QuestCog(commands.Cog):
    def __init__(self, bot: commands.Bot, service: QuestService) -> None:
        self.bot = bot
        self.service = service

    @app_commands.command(name="quests", description="Megnyitja a napi vagy heti Yoru küldetéseidet.")
    @app_commands.describe(period="daily vagy weekly")
    async def quests_slash(self, interaction: discord.Interaction, period: str = "daily") -> None:
        if interaction.guild_id is None:
            return
        try:
            normalized = normalize_period(period)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        view = QuestView(self.service, interaction.guild_id, interaction.user, interaction.user.id, normalized)
        await interaction.response.send_message(embed=await build_quest_embed(self.service, interaction.guild_id, interaction.user, normalized), view=view)

    @commands.command(name="quests", aliases=["quest", "q"])
    @commands.guild_only()
    async def quests_prefix(self, ctx: commands.Context, period: str = "daily") -> None:
        try:
            normalized = normalize_period(period)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        view = QuestView(self.service, ctx.guild.id, ctx.author, ctx.author.id, normalized)
        await ctx.send(embed=await build_quest_embed(self.service, ctx.guild.id, ctx.author, normalized), view=view)

    @app_commands.command(name="questclaim", description="Átvesz egy kész quest jutalmat.")
    @app_commands.describe(period="daily vagy weekly", slot="Quest sorszáma: 1-3")
    async def questclaim_slash(self, interaction: discord.Interaction, period: str, slot: int) -> None:
        if interaction.guild_id is None:
            return
        try:
            normalized = normalize_period(period)
            xp, item = await self.service.claim(interaction.guild_id, interaction.user.id, normalized, slot)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        extra = f"\n🎒 **{ITEM_LABELS.get(item, item)}**" if item else ""
        embed = discord.Embed(title="🎁 Quest jutalom", description=f"💰 **{money(xp)}**{extra}", color=SUCCESS)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="questclaim", aliases=["qclaim", "qc"])
    @commands.guild_only()
    async def questclaim_prefix(self, ctx: commands.Context, period: str, slot: int) -> None:
        try:
            normalized = normalize_period(period)
            xp, item = await self.service.claim(ctx.guild.id, ctx.author.id, normalized, slot)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        extra = f"\n🎒 **{ITEM_LABELS.get(item, item)}**" if item else ""
        embed = discord.Embed(title="🎁 Quest jutalom", description=f"💰 **{money(xp)}**{extra}", color=SUCCESS)
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
