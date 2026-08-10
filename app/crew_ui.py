from __future__ import annotations

import discord

from app import crew_config as cfg
from app.ui import BRAND, GOLD, money, progress_bar

ROLE_LABELS = {
    "leader": "👑 Leader",
    "officer": "⭐ Officer",
    "member": "👤 Member",
}


def _member_name(guild: discord.Guild | None, user_id: int) -> str:
    if guild is None:
        return f"User {user_id}"
    member = guild.get_member(user_id)
    return member.display_name if member else f"User {user_id}"


async def build_crew_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    membership = await bot.crew.get_membership(guild_id, target.id)
    guild = bot.get_guild(guild_id)

    if membership is None:
        embed = discord.Embed(title="👥 Crew", color=BRAND)
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
        embed.description = (
            "Még nem vagy Crew tagja. Alapíts saját csapatot vagy fogadj el egy meghívást.\n\n"
            f"💵 Alapítás: **{money(cfg.CREW_CREATE_COST)}**\n"
            "🤝 Egy játékos egyszerre csak **1 Crew** tagja lehet.\n"
            "📈 A magasabb Crew szint több férőhelyet és kis közös income bónuszt ad."
        )
        embed.add_field(
            name="⚙️ Kezdés",
            value="`!crewcreate <név>` • `!crewaccept` • `!crewtop`",
            inline=False,
        )
        embed.set_footer(text="Yoru • Crew rendszer")
        return embed

    crew = membership.crew
    member = membership.member
    owner_name = _member_name(guild, crew.owner_id)
    next_cost = crew.upgrade_cost

    embed = discord.Embed(title=f"👥 {crew.name}", color=GOLD if member.role == "leader" else BRAND)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.description = crew.description or "-# Ennek a Crew-nak még nincs leírása."
    embed.add_field(name="🏛️ Crew Level", value=f"**Level {crew.level}/{cfg.CREW_MAX_LEVEL}**", inline=True)
    embed.add_field(name="🏦 Crew Bank", value=f"**{money(crew.bank)}**", inline=True)
    embed.add_field(name="👥 Tagok", value=f"**{crew.member_count}/{crew.member_cap}**", inline=True)
    embed.add_field(name="👑 Leader", value=f"**{owner_name}**", inline=True)
    embed.add_field(name="🎖️ Rangod", value=f"**{ROLE_LABELS.get(member.role, member.role.title())}**", inline=True)
    embed.add_field(name="💸 Befizetésed", value=f"**{money(member.contributed)}**", inline=True)
    embed.add_field(
        name="🚀 Crew bónusz",
        value=f"**+{crew.income_bonus * 100:g}%** a támogatott economy jutalmakra",
        inline=False,
    )
    if next_cost is not None:
        embed.add_field(
            name=f"⬆️ Következő fejlesztés • Level {crew.level + 1}",
            value=(
                f"`{progress_bar(crew.bank, next_cost, 12)}` **{money(crew.bank)} / {money(next_cost)}**\n"
                f"Új férőhely: **{cfg.member_cap(crew.level + 1)}** • új bónusz: **+{cfg.income_bonus(crew.level + 1) * 100:g}%**"
            ),
            inline=False,
        )
    else:
        embed.add_field(name="🏆 Max Level", value="A Crew elérte a jelenlegi maximális szintet.", inline=False)

    embed.set_footer(text=f"Yoru • Crew ID: {crew.crew_id} • Összes befizetés: {money(crew.total_contributed)}")
    return embed


async def build_crew_members_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    membership = await bot.crew.get_membership(guild_id, target.id)
    if membership is None:
        return await build_crew_embed(bot, guild_id, target)
    guild = bot.get_guild(guild_id)
    members = await bot.crew.members(guild_id, membership.crew.crew_id)
    embed = discord.Embed(title=f"👥 {membership.crew.name} • Tagok", color=BRAND)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    lines = []
    for member in members[:25]:
        name = _member_name(guild, member.user_id)
        lines.append(f"{ROLE_LABELS.get(member.role, '👤 Member')} **{name}** • {money(member.contributed)}")
    embed.description = "\n".join(lines) or "Nincsenek tagok."
    embed.set_footer(text=f"Yoru • {len(members)}/{membership.crew.member_cap} tag")
    return embed


async def build_crew_top_embed(bot, guild_id: int, requester: discord.abc.User) -> discord.Embed:
    guild = bot.get_guild(guild_id)
    crews = await bot.crew.leaderboard(guild_id, 10)
    embed = discord.Embed(title="🏆 Crew ranglista", color=GOLD)
    embed.set_author(name=requester.display_name, icon_url=requester.display_avatar.url)
    if not crews:
        embed.description = "Még nincs Crew ezen a szerveren."
        return embed
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for index, crew in enumerate(crews, start=1):
        leader = _member_name(guild, crew.owner_id)
        prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
        lines.append(
            f"{prefix} **{crew.name}** • Level **{crew.level}** • 👥 {crew.member_count}/{crew.member_cap}\n"
            f"-# 🏦 {money(crew.bank)} • 💸 lifetime {money(crew.total_contributed)} • Leader: {leader}"
        )
    embed.description = "\n\n".join(lines)
    embed.set_footer(text="Yoru • Rendezés: level → lifetime befizetés → bank")
    return embed


class CrewView(discord.ui.View):
    def __init__(self, bot, guild_id: int, target: discord.abc.User, requester_id: int) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.target = target
        self.requester_id = requester_id
        self.page = "crew"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ezt a Crew panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    def _styles(self) -> None:
        mapping = {
            "yoru_crew_overview": "crew",
            "yoru_crew_members": "members",
            "yoru_crew_top": "top",
        }
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.style = discord.ButtonStyle.primary if mapping.get(item.custom_id) == self.page else discord.ButtonStyle.secondary

    async def _switch(self, interaction: discord.Interaction, page: str) -> None:
        self.page = page
        self._styles()
        if page == "crew":
            embed = await build_crew_embed(self.bot, self.guild_id, self.target)
            if self.target.id == self.requester_id and await self.bot.crew.get_membership(self.guild_id, self.target.id) is None:
                invite = await self.bot.crew.pending_invite(self.guild_id, self.target.id)
                if invite:
                    crew, expires = invite
                    embed.add_field(
                        name="📨 Aktív meghívó",
                        value=f"**{crew.name}** • lejár <t:{int(expires.timestamp())}:R>\nElfogadás: `!crewaccept` vagy `/crewaccept`",
                        inline=False,
                    )
        elif page == "members":
            embed = await build_crew_members_embed(self.bot, self.guild_id, self.target)
        else:
            embed = await build_crew_top_embed(self.bot, self.guild_id, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Crew", emoji="👥", style=discord.ButtonStyle.primary, custom_id="yoru_crew_overview")
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "crew")

    @discord.ui.button(label="Tagok", emoji="🧑‍🤝‍🧑", style=discord.ButtonStyle.secondary, custom_id="yoru_crew_members")
    async def members(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "members")

    @discord.ui.button(label="Toplista", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="yoru_crew_top")
    async def top(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "top")
