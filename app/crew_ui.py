from __future__ import annotations

import discord

from app import crew_config as legacy_cfg
from app import faction_config as cfg
from app.amounts import parse_amount
from app.ui import BRAND, GOLD, SUCCESS, money, progress_bar

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


def _war_definition(objective_id: str):
    return next((item for item in cfg.WAR_OBJECTIVES if item.objective_id == objective_id), None)


async def build_crew_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    """Backwards-compatible name, Frakció 2.0 overview content."""
    membership = await bot.crew.get_membership(guild_id, target.id)
    guild = bot.get_guild(guild_id)

    if membership is None:
        embed = discord.Embed(title="🌙 Frakció", color=BRAND)
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
        embed.description = (
            "Még nem vagy Frakció tagja. Az egész rendszer innen, interaktívan kezelhető.\n\n"
            f"💵 Alapítás: **{money(await bot.crew.create_cost(guild_id))}**\n"
            "🤝 Egy játékos egyszerre csak **1 Frakció** tagja lehet.\n"
            "✨ Frakció XP, közös célok, perk tree, belső rangok és Frakció Wars."
        )
        invite = await bot.crew.pending_invite(guild_id, target.id)
        if invite:
            crew, expires = invite
            embed.add_field(
                name="📨 Aktív meghívó",
                value=f"**{crew.name}** • lejár <t:{int(expires.timestamp())}:R>\nAz **Elfogadás** gombbal csatlakozhatsz.",
                inline=False,
            )
        embed.set_footer(text="Yoru • Frakció 2.0")
        return embed

    crew = membership.crew
    member = membership.member
    progress = await bot.factions.progress(guild_id, crew.crew_id)
    perks = await bot.factions.perk_ranks(guild_id, crew.crew_id)
    level, current, needed, percent = cfg.level_progress(progress.xp)
    custom_rank = await bot.factions.custom_rank_for_member(guild_id, crew.crew_id, target.id)
    owner_name = _member_name(guild, crew.owner_id)
    treasury_bonus = await bot.factions.income_bonus(guild_id, crew.crew_id)

    embed = discord.Embed(title=f"🌙 {crew.name}", color=GOLD if member.role == "leader" else BRAND)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.description = crew.description or "-# Ennek a Frakciónak még nincs leírása."
    embed.add_field(name="✨ Frakció Level", value=f"**Lv. {level}/{cfg.FACTION_MAX_LEVEL}**\n`{progress_bar(current, needed, 10)}` {percent}%", inline=True)
    embed.add_field(name="🌙 Frakció XP", value=f"**{progress.xp:,} XP**".replace(",", " "), inline=True)
    embed.add_field(name="🌲 Perk pont", value=f"**{progress.perk_points_available}** szabad / {progress.perk_points_total} összes", inline=True)
    embed.add_field(name="⚔️ War rekord", value=f"**{progress.war_wins}W / {progress.war_losses}L / {progress.war_draws}D** • {progress.war_points} pont", inline=True)
    embed.add_field(name="🏦 Frakció Bank", value=f"**{money(crew.bank)}**", inline=True)
    embed.add_field(name="👥 Tagok", value=f"**{crew.member_count}/{crew.member_cap}**", inline=True)
    embed.add_field(name="👑 Leader", value=f"**{owner_name}**", inline=True)
    rank_text = ROLE_LABELS.get(member.role, member.role.title())
    if custom_rank:
        rank_text += f"\n🎖️ **{custom_rank['name']}**"
    embed.add_field(name="🎖️ Rangod", value=rank_text, inline=True)
    embed.add_field(name="💸 Befizetésed", value=f"**{money(member.contributed)}**", inline=True)
    contrib = await bot.factions.member_progress(guild_id, crew.crew_id, target.id)
    embed.add_field(name="⚡ Contribution", value=f"**{contrib['contribution_xp']:,} XP**".replace(",", " "), inline=True)
    total_bonus = crew.income_bonus + treasury_bonus
    embed.add_field(
        name="🚀 Economy bónusz",
        value=f"**+{total_bonus * 100:g}%** támogatott income\n-# Infrastructure + Közös Kassza perk",
        inline=False,
    )
    if perks:
        active = [f"{cfg.PERK_BY_KEY[k].emoji} {cfg.PERK_BY_KEY[k].name} **{v}/{cfg.PERK_BY_KEY[k].max_rank}**" for k, v in perks.items() if k in cfg.PERK_BY_KEY and v]
        if active:
            embed.add_field(name="🌲 Aktív perkek", value=" • ".join(active), inline=False)
    embed.set_footer(text=f"Yoru • Frakció ID: {crew.crew_id} • Infrastructure Lv. {crew.level}/{legacy_cfg.CREW_MAX_LEVEL}")
    return embed


async def build_objectives_embed(bot, guild_id: int, user: discord.abc.User) -> discord.Embed:
    membership = await bot.crew.get_membership(guild_id, user.id)
    if membership is None:
        return await build_crew_embed(bot, guild_id, user)
    embed = discord.Embed(title=f"🎯 {membership.crew.name} • Közös célok", color=BRAND)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    if not await bot.factions.objectives_enabled(guild_id):
        embed.description = "A közös célok jelenleg ki vannak kapcsolva ezen a szerveren."
        return embed
    daily, weekly = await bot.factions.objectives(guild_id, membership.crew.crew_id)
    for label, rows in (("☀️ Daily", daily), ("📆 Weekly", weekly)):
        lines = []
        for obj in rows:
            done = "✅" if obj["completed"] else obj["emoji"]
            lines.append(
                f"{done} **{obj['label']}**\n"
                f"`{progress_bar(obj['progress'], obj['target'], 10)}` **{obj['progress']:,}/{obj['target']:,}**\n"
                f"-# Jutalom: {obj['reward_xp']:,} Frakció XP + {money(obj['reward_bank'])} bank"
                .replace(",", " ")
            )
        embed.add_field(name=label, value="\n\n".join(lines) or "Nincs aktív cél.", inline=False)
    embed.set_footer(text="Yoru • A progress minden Frakció tag közös aktivitásából épül")
    return embed


async def build_perks_embed(bot, guild_id: int, user: discord.abc.User, selected: str | None = None) -> discord.Embed:
    membership = await bot.crew.get_membership(guild_id, user.id)
    if membership is None:
        return await build_crew_embed(bot, guild_id, user)
    progress = await bot.factions.progress(guild_id, membership.crew.crew_id)
    ranks = await bot.factions.perk_ranks(guild_id, membership.crew.crew_id)
    embed = discord.Embed(title=f"🌲 {membership.crew.name} • Perk Tree", color=BRAND)
    embed.description = f"Elkölthető pont: **{progress.perk_points_available}** • minden **5 Frakció Level = 1 pont**."
    for perk in cfg.PERKS:
        rank = int(ranks.get(perk.key, 0))
        marker = "👉 " if selected == perk.key else ""
        embed.add_field(
            name=f"{marker}{perk.emoji} {perk.name} • {rank}/{perk.max_rank}",
            value=f"`{progress_bar(rank, perk.max_rank, 10)}`\n{perk.description}",
            inline=False,
        )
    embed.set_footer(text="Yoru • Leader vagy megfelelő belső rang fejlesztheti")
    return embed


async def build_crew_members_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    membership = await bot.crew.get_membership(guild_id, target.id)
    if membership is None:
        return await build_crew_embed(bot, guild_id, target)
    guild = bot.get_guild(guild_id)
    members = await bot.crew.members(guild_id, membership.crew.crew_id)
    rows = []
    for member in members[:25]:
        faction = await bot.factions.member_progress(guild_id, membership.crew.crew_id, member.user_id)
        rank = await bot.factions.custom_rank_for_member(guild_id, membership.crew.crew_id, member.user_id)
        rows.append((member, faction, rank))
    embed = discord.Embed(title=f"👥 {membership.crew.name} • Tagok", color=BRAND)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    lines = []
    for member, faction, rank in rows:
        name = _member_name(guild, member.user_id)
        custom = f" • 🎖️ {rank['name']}" if rank else ""
        lines.append(
            f"{ROLE_LABELS.get(member.role, '👤 Member')} **{name}**{custom}\n"
            f"-# ⚡ {faction['contribution_xp']:,} contribution XP • 💸 {money(member.contributed)}".replace(",", " ")
        )
    embed.description = "\n\n".join(lines) or "Nincsenek tagok."
    embed.set_footer(text=f"Yoru • {len(members)}/{membership.crew.member_cap} tag • Belső rangok külön panelen")
    return embed


async def build_war_embed(bot, guild_id: int, user: discord.abc.User) -> discord.Embed:
    membership = await bot.crew.get_membership(guild_id, user.id)
    if membership is None:
        return await build_crew_embed(bot, guild_id, user)
    embed = discord.Embed(title=f"⚔️ {membership.crew.name} • Frakció Wars", color=GOLD)
    if not await bot.factions.wars_enabled(guild_id):
        embed.description = "A Frakció Wars jelenleg ki van kapcsolva ezen a szerveren."
        return embed
    war = await bot.factions.war_for_crew(guild_id, membership.crew.crew_id)
    if not war:
        embed.description = "Nincs aktív vagy függőben lévő War. Válassz ellenfelet az alábbi listából."
        tuning = await bot.factions.tuning(guild_id)
        embed.add_field(
            name="🏆 Jutalom",
            value=f"Győztes alapjutalom: **{money(int(tuning['win_bank']))} + {int(tuning['win_xp']):,} XP**".replace(",", " "),
            inline=False,
        )
        return embed
    left = await bot.crew.get_crew(guild_id, int(war["challenger_crew_id"]))
    right = await bot.crew.get_crew(guild_id, int(war["target_crew_id"]))
    definition = _war_definition(str(war["objective_id"]))
    objective = f"{definition.emoji} {definition.label}" if definition else str(war["objective_id"])
    status_labels = {"pending": "⏳ Kihívás", "active": "⚔️ Aktív", "resolved": "✅ Lezárt"}
    embed.description = f"**{left.name if left else war['challenger_crew_id']}** vs **{right.name if right else war['target_crew_id']}**"
    embed.add_field(name="Állapot", value=status_labels.get(str(war["status"]), str(war["status"])), inline=True)
    embed.add_field(name="Objective", value=objective, inline=True)
    embed.add_field(name="Lejár", value=f"<t:{int(discord.utils.parse_time(str(war['expires_at'])).timestamp())}:R>" if discord.utils.parse_time(str(war["expires_at"])) else str(war["expires_at"]), inline=True)
    target = int(war["target"])
    embed.add_field(
        name="📊 Score",
        value=(
            f"**{left.name if left else 'Kihívó'}** • `{progress_bar(int(war['challenger_score']), target, 10)}` {int(war['challenger_score']):,}/{target:,}\n"
            f"**{right.name if right else 'Cél'}** • `{progress_bar(int(war['target_score']), target, 10)}` {int(war['target_score']):,}/{target:,}"
        ).replace(",", " "),
        inline=False,
    )
    if war["status"] == "pending" and int(war["target_crew_id"]) == membership.crew.crew_id:
        embed.add_field(name="📨 Teendő", value="A Frakció vezetése elfogadhatja vagy elutasíthatja a kihívást.", inline=False)
    embed.set_footer(text="Yoru • Objective-alapú, absztrakt Frakció War")
    return embed


async def build_crew_top_embed(bot, guild_id: int, requester: discord.abc.User) -> discord.Embed:
    guild = bot.get_guild(guild_id)
    crews = await bot.factions.leaderboard(guild_id, 10)
    embed = discord.Embed(title="🏆 Frakció ranglista", color=GOLD)
    embed.set_author(name=requester.display_name, icon_url=requester.display_avatar.url)
    if not crews:
        embed.description = "Még nincs Frakció ezen a szerveren."
        return embed
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for index, crew in enumerate(crews, start=1):
        leader = _member_name(guild, int(crew["owner_id"]))
        prefix = medals[index - 1] if index <= 3 else f"`#{index}`"
        lines.append(
            f"{prefix} **{crew['name']}** • Frakció Lv. **{crew['faction_level']}** • 👥 {crew['member_count']}\n"
            f"-# 🌙 {int(crew['faction_xp']):,} XP • ⚔️ {int(crew['war_points'])} war pont • 🏦 {money(int(crew['bank']))} • Leader: {leader}".replace(",", " ")
        )
    embed.description = "\n\n".join(lines)
    embed.set_footer(text="Yoru • Rendezés: Frakció Level → XP → lifetime befizetés")
    return embed


class _ActionButton(discord.ui.Button):
    def __init__(self, *, callback, **kwargs):
        super().__init__(**kwargs)
        self._fn = callback

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._fn(interaction)


class _ActionSelect(discord.ui.Select):
    def __init__(self, *, callback, **kwargs):
        super().__init__(**kwargs)
        self._fn = callback

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._fn(interaction, self)


class FactionInviteUserSelect(discord.ui.UserSelect):
    """Native member picker for Frakció invites; safe on large servers."""

    def __init__(self, parent_view: "CrewView") -> None:
        super().__init__(
            placeholder="Játékos meghívása a Frakcióba…",
            min_values=1,
            max_values=1,
            row=2,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        member = self.values[0]
        if getattr(member, "bot", False):
            return await interaction.response.send_message("❌ Botot nem hívhatsz meg.", ephemeral=True)
        try:
            expires = await self.parent_view.bot.crew.invite(
                self.parent_view.guild_id, interaction.user.id, member.id
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(
            f"📨 **{member.display_name}** meghívva • lejár <t:{int(expires.timestamp())}:R>.",
            ephemeral=True,
        )


class FactionCreateModal(discord.ui.Modal, title="🌙 Frakció alapítása"):
    name = discord.ui.TextInput(label="Frakció neve", min_length=3, max_length=24)

    def __init__(self, view: "CrewView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.bot.crew.create(interaction.guild_id, interaction.user.id, str(self.name.value))
        except (ValueError, RuntimeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.parent_view.target = interaction.user
        await self.parent_view.refresh(interaction, "overview")


class FactionDepositModal(discord.ui.Modal, title="🏦 Frakció Bank befizetés"):
    amount = discord.ui.TextInput(label="Összeg", placeholder="pl. 500k, 2m, all", max_length=24)

    def __init__(self, view: "CrewView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            wallet, _ = await self.parent_view.bot.database.get_balance(interaction.guild_id, interaction.user.id)
            parsed = parse_amount(str(self.amount.value), wallet)
            await self.parent_view.bot.crew.deposit(interaction.guild_id, interaction.user.id, parsed)
        except (ValueError, RuntimeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction, "overview")


class FactionDescriptionModal(discord.ui.Modal, title="📝 Frakció leírás"):
    description = discord.ui.TextInput(label="Leírás", style=discord.TextStyle.paragraph, required=False, max_length=160)

    def __init__(self, view: "CrewView", current: str) -> None:
        super().__init__()
        self.parent_view = view
        self.description.default = current

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.bot.crew.set_description(interaction.guild_id, interaction.user.id, str(self.description.value))
        except (ValueError, RuntimeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction, "overview")


class FactionRankCreateModal(discord.ui.Modal, title="🎖️ Új belső rang"):
    rank_name = discord.ui.TextInput(label="Rang neve", min_length=2, max_length=24)
    permissions = discord.ui.TextInput(
        label="Jogok vesszővel",
        placeholder="invite,kick,manage_wars",
        required=False,
        max_length=200,
    )

    def __init__(self, view: "FactionRanksView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        perms = [part.strip() for part in str(self.permissions.value).split(",") if part.strip()]
        try:
            await self.parent_view.bot.factions.create_custom_rank(interaction.guild_id, interaction.user.id, str(self.rank_name.value), perms)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class FactionRanksView(discord.ui.View):
    def __init__(self, bot, guild_id: int, crew_id: int, owner_id: int, parent: "CrewView") -> None:
        super().__init__(timeout=600)
        self.bot, self.guild_id, self.crew_id, self.owner_id, self.parent = bot, guild_id, crew_id, owner_id, parent
        self.selected_rank_id: int | None = None
        self.selected_user_id: int | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    async def embed(self) -> discord.Embed:
        crew = await self.bot.crew.get_crew(self.guild_id, self.crew_id)
        ranks = await self.bot.factions.custom_ranks(self.guild_id, self.crew_id)
        embed = discord.Embed(title=f"🎖️ {crew.name if crew else 'Frakció'} • Belső rangok", color=BRAND)
        if not ranks:
            embed.description = "Még nincs egyedi belső rang. Hozz létre egyet a gombbal."
        else:
            lines = []
            for rank in ranks:
                perms = ", ".join(f"{cfg.CUSTOM_RANK_PERMISSIONS[p][0]} {cfg.CUSTOM_RANK_PERMISSIONS[p][1]}" for p in rank["permissions"]) or "Nincs extra jog"
                mark = "👉 " if self.selected_rank_id == rank["rank_id"] else ""
                lines.append(f"{mark}**{rank['name']}** • ID `{rank['rank_id']}`\n-# {perms}")
            embed.description = "\n\n".join(lines)
        embed.add_field(
            name="🔐 Használható jogkulcsok",
            value=" • ".join(f"`{key}`" for key in cfg.CUSTOM_RANK_PERMISSIONS),
            inline=False,
        )
        embed.set_footer(text="Yoru • A Leader mindig minden Frakció-joggal rendelkezik")
        return embed

    async def prepare(self) -> None:
        self.clear_items()
        ranks = await self.bot.factions.custom_ranks(self.guild_id, self.crew_id)
        members = await self.bot.crew.members(self.guild_id, self.crew_id)
        if ranks:
            options = [discord.SelectOption(label=r["name"][:100], value=str(r["rank_id"]), emoji="🎖️", default=self.selected_rank_id == r["rank_id"]) for r in ranks[:25]]
            async def choose_rank(interaction, select):
                self.selected_rank_id = int(select.values[0])
                await self.refresh(interaction)
            self.add_item(_ActionSelect(callback=choose_rank, placeholder="Belső rang kiválasztása…", options=options, row=0))
        if members:
            guild = self.bot.get_guild(self.guild_id)
            options = []
            for member in members[:25]:
                options.append(discord.SelectOption(label=_member_name(guild, member.user_id)[:100], value=str(member.user_id), emoji="👤", default=self.selected_user_id == member.user_id))
            async def choose_member(interaction, select):
                self.selected_user_id = int(select.values[0])
                await self.refresh(interaction)
            self.add_item(_ActionSelect(callback=choose_member, placeholder="Frakció tag kiválasztása…", options=options, row=1))

        async def create(interaction):
            await interaction.response.send_modal(FactionRankCreateModal(self))
        async def assign(interaction):
            if self.selected_rank_id is None or self.selected_user_id is None:
                return await interaction.response.send_message("❌ Válassz rangot és tagot.", ephemeral=True)
            try:
                await self.bot.factions.assign_custom_rank(self.guild_id, interaction.user.id, self.selected_user_id, self.selected_rank_id)
            except ValueError as exc:
                return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            await self.refresh(interaction)
        async def clear_rank(interaction):
            if self.selected_user_id is None:
                return await interaction.response.send_message("❌ Válassz tagot.", ephemeral=True)
            try:
                await self.bot.factions.assign_custom_rank(self.guild_id, interaction.user.id, self.selected_user_id, None)
            except ValueError as exc:
                return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            await self.refresh(interaction)
        async def delete_rank(interaction):
            if self.selected_rank_id is None:
                return await interaction.response.send_message("❌ Válassz rangot.", ephemeral=True)
            try:
                await self.bot.factions.delete_custom_rank(self.guild_id, interaction.user.id, self.selected_rank_id)
            except ValueError as exc:
                return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            self.selected_rank_id = None
            await self.refresh(interaction)
        async def back(interaction):
            await self.parent.refresh(interaction, "members")

        self.add_item(_ActionButton(callback=create, label="Új rang", emoji="➕", style=discord.ButtonStyle.success, row=2))
        self.add_item(_ActionButton(callback=assign, label="Kiosztás", emoji="🎖️", style=discord.ButtonStyle.primary, row=2))
        self.add_item(_ActionButton(callback=clear_rank, label="Rang levétele", emoji="🧹", style=discord.ButtonStyle.secondary, row=2))
        self.add_item(_ActionButton(callback=delete_rank, label="Rang törlése", emoji="🗑️", style=discord.ButtonStyle.danger, row=2))
        self.add_item(_ActionButton(callback=back, label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.prepare()
        await interaction.response.edit_message(embed=await self.embed(), view=self)


class CrewView(discord.ui.View):
    """Primary interaction-first Frakció player UI.  Legacy class name kept stable."""

    def __init__(self, bot, guild_id: int, target: discord.abc.User, requester_id: int) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.target = target
        self.requester_id = requester_id
        self.page = "overview"
        self.selected_perk: str | None = None
        self.selected_opponent: int | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ezt a Frakció panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    async def _notify_war_challenge(self, interaction: discord.Interaction, war: dict) -> None:
        """Best-effort DM to the challenged Frakció owner. A failed DM never cancels the War."""
        guild = interaction.guild
        if guild is None:
            return
        target = await self.bot.crew.get_crew(self.guild_id, int(war["target_crew_id"]))
        challenger = await self.bot.crew.get_crew(self.guild_id, int(war["challenger_crew_id"]))
        if target is None:
            return
        user = self.bot.get_user(int(target.owner_id))
        if user is None:
            try:
                user = await self.bot.fetch_user(int(target.owner_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        definition = _war_definition(str(war["objective_id"]))
        objective = f"{definition.emoji} {definition.label}" if definition else str(war["objective_id"])
        expires = discord.utils.parse_time(str(war.get("expires_at") or ""))
        embed = discord.Embed(title="⚔️ Frakció War kihívás érkezett!", color=GOLD)
        embed.description = (
            f"A **{challenger.name if challenger else 'másik Frakció'}** kihívta a **{target.name}** Frakciót "
            f"a **{guild.name}** szerveren."
        )
        embed.add_field(name="🎯 Objective", value=objective, inline=True)
        embed.add_field(name="📊 Cél", value=f"**{int(war['target']):,}**".replace(",", " "), inline=True)
        if expires is not None:
            embed.add_field(name="⏳ Kihívás lejár", value=f"<t:{int(expires.timestamp())}:R>", inline=True)
        jump_url = getattr(getattr(interaction, "message", None), "jump_url", None)
        if jump_url:
            embed.add_field(name="➡️ Teendő", value=f"Nyisd meg a **Frakció → Wars** panelt, majd **Elfogadás / Elutasítás**.\n[Ugrás a War panelhez]({jump_url})", inline=False)
        else:
            embed.add_field(name="➡️ Teendő", value="Nyisd meg a **Frakció → Wars** panelt, majd **Elfogadás / Elutasítás**.", inline=False)
        embed.set_footer(text="Yoru • Frakció 2.0 • War értesítés")
        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _embed(self) -> discord.Embed:
        if self.page == "objectives":
            return await build_objectives_embed(self.bot, self.guild_id, self.target)
        if self.page == "perks":
            return await build_perks_embed(self.bot, self.guild_id, self.target, self.selected_perk)
        if self.page == "members":
            return await build_crew_members_embed(self.bot, self.guild_id, self.target)
        if self.page == "wars":
            return await build_war_embed(self.bot, self.guild_id, self.target)
        if self.page == "top":
            return await build_crew_top_embed(self.bot, self.guild_id, self.target)
        return await build_crew_embed(self.bot, self.guild_id, self.target)

    async def _switch(self, interaction: discord.Interaction, page: str) -> None:
        await self.refresh(interaction, page)

    def _nav_button(self, label: str, emoji: str, page: str, row: int = 0) -> discord.ui.Button:
        async def callback(interaction):
            await self._switch(interaction, page)
        return _ActionButton(
            callback=callback, label=label, emoji=emoji,
            style=discord.ButtonStyle.primary if self.page == page else discord.ButtonStyle.secondary,
            row=row,
        )

    async def prepare(self) -> discord.Embed:
        self.clear_items()
        membership = await self.bot.crew.get_membership(self.guild_id, self.target.id)
        own_panel = self.target.id == self.requester_id
        if membership is None:
            if own_panel:
                async def create(interaction):
                    await interaction.response.send_modal(FactionCreateModal(self))
                async def accept(interaction):
                    try:
                        await self.bot.crew.accept(self.guild_id, interaction.user.id)
                    except (ValueError, RuntimeError) as exc:
                        return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                    self.target = interaction.user
                    await self.refresh(interaction, "overview")
                self.add_item(_ActionButton(callback=create, label="Frakció alapítás", emoji="➕", style=discord.ButtonStyle.success, row=0))
                self.add_item(_ActionButton(callback=accept, label="Meghívó elfogadás", emoji="🤝", style=discord.ButtonStyle.primary, row=0))
            self.add_item(self._nav_button("Toplista", "🏆", "top", 0))
            return await self._embed()

        for label, emoji, page in (("Frakció", "🌙", "overview"), ("Célok", "🎯", "objectives"), ("Perkek", "🌲", "perks"), ("Tagok", "👥", "members"), ("Wars", "⚔️", "wars")):
            self.add_item(self._nav_button(label, emoji, page, 0))

        if not own_panel:
            return await self._embed()

        if self.page == "overview":
            async def deposit(interaction):
                await interaction.response.send_modal(FactionDepositModal(self))
            async def desc(interaction):
                current = membership.crew.description
                await interaction.response.send_modal(FactionDescriptionModal(self, current))
            async def upgrade(interaction):
                try:
                    await self.bot.crew.upgrade(self.guild_id, interaction.user.id)
                except (ValueError, RuntimeError) as exc:
                    return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                await self.refresh(interaction, "overview")
            async def top(interaction):
                await self.refresh(interaction, "top")
            self.add_item(_ActionButton(callback=deposit, label="Befizetés", emoji="🏦", style=discord.ButtonStyle.success, row=1))
            if await self.bot.factions.has_permission(self.guild_id, self.requester_id, "manage_profile"):
                self.add_item(_ActionButton(callback=desc, label="Leírás", emoji="📝", style=discord.ButtonStyle.secondary, row=1))
            if await self.bot.factions.has_permission(self.guild_id, self.requester_id, "upgrade"):
                self.add_item(_ActionButton(callback=upgrade, label="Infrastructure", emoji="⬆️", style=discord.ButtonStyle.primary, row=1))
            self.add_item(_ActionButton(callback=top, label="Toplista", emoji="🏆", style=discord.ButtonStyle.secondary, row=1))
            if await self.bot.factions.has_permission(self.guild_id, self.requester_id, "invite"):
                self.add_item(FactionInviteUserSelect(self))

        elif self.page == "perks":
            ranks = await self.bot.factions.perk_ranks(self.guild_id, membership.crew.crew_id)
            options = [discord.SelectOption(label=f"{perk.name} • {ranks.get(perk.key,0)}/{perk.max_rank}", value=perk.key, emoji=perk.emoji, description=perk.description[:100], default=self.selected_perk == perk.key) for perk in cfg.PERKS]
            async def select_perk(interaction, select):
                self.selected_perk = select.values[0]
                await self.refresh(interaction, "perks")
            self.add_item(_ActionSelect(callback=select_perk, placeholder="Perk ág kiválasztása…", options=options, row=1))
            if await self.bot.factions.has_permission(self.guild_id, self.requester_id, "manage_perks"):
                async def buy(interaction):
                    if not self.selected_perk:
                        return await interaction.response.send_message("❌ Előbb válassz perk ágat.", ephemeral=True)
                    try:
                        await self.bot.factions.buy_perk(self.guild_id, interaction.user.id, self.selected_perk)
                    except ValueError as exc:
                        return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                    await self.refresh(interaction, "perks")
                self.add_item(_ActionButton(callback=buy, label="Perk fejlesztése", emoji="⬆️", style=discord.ButtonStyle.success, row=2))

        elif self.page == "members":
            if await self.bot.factions.has_permission(self.guild_id, self.requester_id, "manage_ranks"):
                async def ranks(interaction):
                    view = FactionRanksView(self.bot, self.guild_id, membership.crew.crew_id, self.requester_id, self)
                    await view.prepare()
                    await interaction.response.edit_message(embed=await view.embed(), view=view)
                self.add_item(_ActionButton(callback=ranks, label="Belső rangok", emoji="🎖️", style=discord.ButtonStyle.primary, row=1))

        elif self.page == "wars":
            war = await self.bot.factions.war_for_crew(self.guild_id, membership.crew.crew_id)
            can_war = await self.bot.factions.has_permission(self.guild_id, self.requester_id, "manage_wars")
            if war and war["status"] == "pending" and int(war["target_crew_id"]) == membership.crew.crew_id and can_war:
                async def accept(interaction):
                    try:
                        await self.bot.factions.accept_war(self.guild_id, interaction.user.id)
                    except ValueError as exc:
                        return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                    await self.refresh(interaction, "wars")
                async def decline(interaction):
                    try:
                        await self.bot.factions.decline_war(self.guild_id, interaction.user.id)
                    except ValueError as exc:
                        return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                    await self.refresh(interaction, "wars")
                self.add_item(_ActionButton(callback=accept, label="Elfogadás", emoji="✅", style=discord.ButtonStyle.success, row=1))
                self.add_item(_ActionButton(callback=decline, label="Elutasítás", emoji="❌", style=discord.ButtonStyle.danger, row=1))
            elif not war and can_war:
                opponents = [row for row in await self.bot.factions.leaderboard(self.guild_id, 25) if int(row["crew_id"]) != membership.crew.crew_id]
                if opponents:
                    options = [discord.SelectOption(label=str(row["name"])[:100], value=str(row["crew_id"]), emoji="⚔️", description=f"Frakció Lv. {row['faction_level']} • {row['member_count']} tag") for row in opponents[:25]]
                    async def select_opponent(interaction, select):
                        self.selected_opponent = int(select.values[0])
                        await self.refresh(interaction, "wars")
                    self.add_item(_ActionSelect(callback=select_opponent, placeholder="Ellenfél Frakció kiválasztása…", options=options, row=1))
                    async def challenge(interaction):
                        if self.selected_opponent is None:
                            return await interaction.response.send_message("❌ Válassz ellenfelet.", ephemeral=True)
                        try:
                            war_created = await self.bot.factions.create_war(self.guild_id, interaction.user.id, self.selected_opponent)
                        except ValueError as exc:
                            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                        self.selected_opponent = None
                        # Notify first: even if the interaction UI refresh later fails, the
                        # challenged Frakció leader should still receive the War alert.
                        await self._notify_war_challenge(interaction, war_created)
                        await self.refresh(interaction, "wars")
                    self.add_item(_ActionButton(callback=challenge, label="Kihívás", emoji="⚔️", style=discord.ButtonStyle.danger, row=2))
        return await self._embed()

    async def refresh(self, interaction: discord.Interaction, page: str | None = None) -> None:
        if page:
            self.page = page
        embed = await self.prepare()
        await interaction.response.edit_message(embed=embed, view=self)


class FactionSettingsModal(discord.ui.Modal, title="🌙 Frakció 2.0 • Tuning"):
    xp_multiplier = discord.ui.TextInput(label="Frakció XP szorzó (%)", min_length=2, max_length=3)

    def __init__(self, cog, owner_id: int, current: int) -> None:
        super().__init__()
        self.cog, self.owner_id = cog, owner_id
        self.xp_multiplier.default = str(current)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.factions.set_xp_multiplier_percent(interaction.guild_id, int(str(self.xp_multiplier.value)))
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class FactionCoreSettingsModal(discord.ui.Modal, title="Frakció • Alap szabályok"):
    create_cost = discord.ui.TextInput(label="Alapítási ár", placeholder="pl. 5m", max_length=30)
    invite_hours = discord.ui.TextInput(label="Meghívó lejárat (óra)", max_length=4)

    def __init__(self, cog, owner_id: int, create_cost: int, invite_hours: int) -> None:
        super().__init__(timeout=300)
        self.cog, self.owner_id = cog, owner_id
        self.create_cost.default = str(create_cost)
        self.invite_hours.default = str(invite_hours)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.set_core_settings(
                interaction.guild_id,
                create_cost=parse_amount(str(self.create_cost.value)),
                invite_hours=int(str(self.invite_hours.value)),
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class FactionContentSettingsModal(discord.ui.Modal, title="Frakció • Célok / XP"):
    daily = discord.ui.TextInput(label="Daily objective darab", max_length=3)
    weekly = discord.ui.TextInput(label="Weekly objective darab", max_length=3)
    deposit_per = discord.ui.TextInput(label="Deposit összeg / 1 XP", max_length=30)
    deposit_cap = discord.ui.TextInput(label="Deposit XP cap / esemény", max_length=12)
    activity_divisor = discord.ui.TextInput(label="Activity XP / 1 Frakció XP", max_length=12)

    def __init__(self,cog,owner_id:int,current:dict)->None:
        super().__init__(timeout=300);self.cog,self.owner_id=cog,owner_id
        self.daily.default=str(current["daily_objectives"]);self.weekly.default=str(current["weekly_objectives"])
        self.deposit_per.default=str(current["deposit_xp_per"]);self.deposit_cap.default=str(current["deposit_xp_cap"]);self.activity_divisor.default=str(current["activity_xp_divisor"])

    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            await self.cog.factions.set_tuning(interaction.guild_id,daily_objectives=int(str(self.daily.value)),weekly_objectives=int(str(self.weekly.value)),deposit_xp_per=parse_amount(str(self.deposit_per.value)),deposit_xp_cap=int(str(self.deposit_cap.value)),activity_xp_divisor=int(str(self.activity_divisor.value)))
        except ValueError as exc:return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await self.cog.show_settings(interaction,self.owner_id)


class FactionWarSettingsModal(discord.ui.Modal, title="Frakció • War balance"):
    challenge = discord.ui.TextInput(label="Kihívás elfogadási idő (óra)",max_length=5)
    duration = discord.ui.TextInput(label="War időtartam (óra)",max_length=5)
    win_reward = discord.ui.TextInput(label="Win reward: pénz, XP",placeholder="2500000, 1500",max_length=60)
    draw_reward = discord.ui.TextInput(label="Draw reward: pénz, XP",placeholder="500000, 300",max_length=60)

    def __init__(self,cog,owner_id:int,current:dict)->None:
        super().__init__(timeout=300);self.cog,self.owner_id=cog,owner_id
        self.challenge.default=str(current["challenge_hours"]);self.duration.default=str(current["war_hours"])
        self.win_reward.default=f"{current['win_bank']}, {current['win_xp']}";self.draw_reward.default=f"{current['draw_bank']}, {current['draw_xp']}"

    @staticmethod
    def _pair(raw:str)->tuple[int,int]:
        parts=[x.strip() for x in raw.replace(";",",").split(",") if x.strip()]
        if len(parts)!=2:raise ValueError("Reward formátum: pénz, XP")
        return parse_amount(parts[0]),int(parts[1])

    async def on_submit(self,interaction:discord.Interaction)->None:
        try:
            wb,wx=self._pair(str(self.win_reward.value));db,dx=self._pair(str(self.draw_reward.value))
            await self.cog.factions.set_tuning(interaction.guild_id,challenge_hours=int(str(self.challenge.value)),war_hours=int(str(self.duration.value)),win_bank=wb,win_xp=wx,draw_bank=db,draw_xp=dx)
        except ValueError as exc:return await interaction.response.send_message(f"❌ {exc}",ephemeral=True)
        await self.cog.show_settings(interaction,self.owner_id)


async def build_faction_settings_embed(cog, guild: discord.Guild) -> discord.Embed:
    enabled = await cog.factions.enabled(guild.id)
    objectives = await cog.factions.objectives_enabled(guild.id)
    wars = await cog.factions.wars_enabled(guild.id)
    xp = await cog.factions.xp_multiplier_percent(guild.id)
    tuning = await cog.factions.tuning(guild.id)
    create_cost = await cog.service.create_cost(guild.id)
    invite_hours = await cog.service.invite_hours(guild.id)
    embed = discord.Embed(title="🌙 Frakció 2.0 • Szerverbeállítások", color=BRAND)
    embed.description = "A Frakció rendszer globális viselkedése. A játékosok minden mást a `!crew` / `/crew` interaktív panelen kezelnek."
    embed.add_field(name="Rendszer", value="✅ ON" if enabled else "❌ OFF", inline=True)
    embed.add_field(name="Közös célok", value="✅ ON" if objectives else "❌ OFF", inline=True)
    embed.add_field(name="Frakció Wars", value="✅ ON" if wars else "❌ OFF", inline=True)
    embed.add_field(name="XP szorzó", value=f"**{xp}%**", inline=True)
    embed.add_field(name="🏗️ Alap szabályok", value=f"Alapítás **{money(create_cost)}** • meghívó **{invite_hours}h**", inline=False)
    embed.add_field(name="🎯 Célok / XP", value=f"Daily **{tuning['daily_objectives']}** • Weekly **{tuning['weekly_objectives']}**\nDeposit: **{money(tuning['deposit_xp_per'])}/XP**, cap **{tuning['deposit_xp_cap']} XP** • Activity **{tuning['activity_xp_divisor']}:1**", inline=False)
    embed.add_field(name="⚔️ War balance", value=f"Accept **{tuning['challenge_hours']}h** • duration **{tuning['war_hours']}h**\nWin **{money(tuning['win_bank'])} + {tuning['win_xp']} XP** • Draw **{money(tuning['draw_bank'])} + {tuning['draw_xp']} XP**", inline=False)
    embed.add_field(name="Milestone", value="Minden **5 Frakció Level** után 1 közös perk pont.", inline=True)
    embed.add_field(name="UI", value="Interaction-first • gombok • selectek • modalok • lapozható rendszerek", inline=True)
    embed.set_footer(text="Yoru • /settings → Frakció • DB Settings az elsődleges")
    return embed


class FactionSettingsView(discord.ui.View):
    def __init__(self, cog, owner_id: int) -> None:
        super().__init__(timeout=600)
        self.cog, self.owner_id = cog, owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a panelt nem te nyitottad meg.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True)
            return False
        return True

    async def _toggle(self, interaction, key: str, current: bool) -> None:
        await self.cog.factions.settings.set_bool(interaction.guild_id, key, not current)
        await self.cog.show_settings(interaction, self.owner_id)

    @discord.ui.button(label="Frakció ON/OFF", emoji="🌙", style=discord.ButtonStyle.primary, row=0)
    async def enabled(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.factions.enabled(interaction.guild_id)
        await self._toggle(interaction, cfg.FACTION_ENABLED_KEY, current)

    @discord.ui.button(label="Célok ON/OFF", emoji="🎯", style=discord.ButtonStyle.secondary, row=0)
    async def objectives(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.factions.objectives_enabled(interaction.guild_id)
        await self._toggle(interaction, cfg.FACTION_OBJECTIVES_ENABLED_KEY, current)

    @discord.ui.button(label="Wars ON/OFF", emoji="⚔️", style=discord.ButtonStyle.secondary, row=0)
    async def wars(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.factions.wars_enabled(interaction.guild_id)
        await self._toggle(interaction, cfg.FACTION_WARS_ENABLED_KEY, current)

    @discord.ui.button(label="XP tuning", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.factions.xp_multiplier_percent(interaction.guild_id)
        await interaction.response.send_modal(FactionSettingsModal(self.cog, self.owner_id, current))

    @discord.ui.button(label="Alap szabályok", emoji="🏗️", style=discord.ButtonStyle.primary, row=1)
    async def core_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(FactionCoreSettingsModal(
            self.cog, self.owner_id,
            await self.cog.service.create_cost(interaction.guild_id),
            await self.cog.service.invite_hours(interaction.guild_id),
        ))

    @discord.ui.button(label="Célok / XP", emoji="🎯", style=discord.ButtonStyle.primary, row=1)
    async def content_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(FactionContentSettingsModal(self.cog,self.owner_id,await self.cog.factions.tuning(interaction.guild_id)))

    @discord.ui.button(label="War balance", emoji="⚔️", style=discord.ButtonStyle.primary, row=1)
    async def war_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(FactionWarSettingsModal(self.cog,self.owner_id,await self.cog.factions.tuning(interaction.guild_id)))

    @discord.ui.button(label="Alap default", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def reset_core(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.reset_core_settings(interaction.guild_id)
        await self.cog.show_settings(interaction, self.owner_id)

    @discord.ui.button(label="Tuning default", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def reset_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.factions.reset_tuning(interaction.guild_id);await self.cog.show_settings(interaction,self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        settings_cog = self.cog.bot.get_cog("SettingsCog")
        if settings_cog is None:
            return await interaction.response.send_message("❌ Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, self.owner_id)
