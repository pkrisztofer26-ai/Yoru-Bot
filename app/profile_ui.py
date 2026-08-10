from __future__ import annotations

from datetime import datetime

import discord

from app.ui import BRAND, DANGER, GOLD, SUCCESS, money, progress_bar
from app.services.progression import ACHIEVEMENTS, BADGES, TITLE_REQUIREMENTS
from app.progression_config import ACHIEVEMENT_DEFINITIONS
from app.crew_ui import build_crew_embed
from app.progression_math import progress_for_xp

RARITY_META = {
    "common": ("⚪", "Common"),
    "rare": ("🔵", "Rare"),
    "epic": ("🟣", "Epic"),
    "legendary": ("🟡", "Legendary"),
    "mythic": ("🔴", "Mythic"),
}
CATEGORY_META = {
    "game": ("🎮", "Játék"),
    "market": ("📈", "Piac"),
    "lootbox": ("📦", "Láda"),
    "booster": ("⚡", "Booster"),
    "utility": ("🧰", "Utility"),
    "reward": ("🎁", "Jutalom"),
}

GAME_LABELS = {
    "blackjack": "🃏 Blackjack",
    "coinflip": "🪙 Coinflip",
    "roulette": "🎡 Roulette",
    "slots": "🎰 Slots",
    "dice": "🎲 Dice",
    "highlow": "🃏 High/Low",
    "rps": "✂️ RPS",
    "chickenfight": "🐔 Chicken Fight",
}


def compact_number(value: int) -> str:
    value = int(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000_000_000:
        return f"{sign}{value / 1_000_000_000_000_000:.2f}Q"
    if value >= 1_000_000_000_000:
        return f"{sign}{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{sign}{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{sign}{value / 1_000:.1f}K"
    return f"{sign}{value}"


def _level_progress(xp_points: int) -> tuple[int, int, int, int]:
    return progress_for_xp(xp_points)


def _favorite_game(stats: dict[str, int]) -> str:
    best = (0, "—")
    for game_id, label in GAME_LABELS.items():
        plays = int(stats.get(f"gambling.{game_id}.plays", 0))
        if plays > best[0]:
            best = (plays, label)
    return best[1]


async def build_overview_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    data = await bot.economy.profile(guild_id, target.id)
    stats = data.get("statistics", {}) if isinstance(data.get("statistics", {}), dict) else {}
    unlocked_ach = await bot.progression.achievements(guild_id, target.id)
    unlocked_badges = await bot.database.get_badges(guild_id, target.id)

    wallet = int(data["wallet"])
    bank = int(data["bank"])
    wealth = wallet + bank
    xp_points = int(data.get("xp_points", 0))
    level, current, needed, percent = _level_progress(xp_points)
    title = str(data.get("selected_title", "Kezdő"))
    favorite = _favorite_game(stats)
    prestige_state = await bot.prestige.state(guild_id, target.id)
    crew_membership = await bot.crew.get_membership(guild_id, target.id)

    embed = discord.Embed(color=BRAND)
    embed.set_author(name=f"{target.display_name} • Yoru profil", icon_url=target.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)
    prestige_line = f"🌌 **Prestige {prestige_state.rank}** • +{round(prestige_state.income_bonus * 100)}% income\n" if prestige_state.rank else ""
    embed.description = (
        f"🎖️ **{title}**\n"
        f"{prestige_line}"
        f"⭐ **Level {level}**  `{progress_bar(current, needed, 14)}`  **{percent}%**\n"
        f"-# {current:,} / {needed:,} progression XP".replace(",", " ")
    )

    embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
    embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
    embed.add_field(name="💎 Vagyon", value=f"**{money(wealth)}**", inline=True)

    earned = int(stats.get("economy.earned", data.get("money_earned", 0)))
    lost = int(stats.get("economy.lost", data.get("money_lost", 0)))
    streak = int(data.get("daily_streak", 0))
    best_streak = int(data.get("best_daily_streak", 0))
    embed.add_field(
        name="📈 Áttekintés",
        value=(
            f"🎮 Kedvenc játék: **{favorite}**\n"
            f"🏆 Achievement: **{len(unlocked_ach)}/{len(ACHIEVEMENTS)}**\n"
            f"💠 Badge: **{len(unlocked_badges)}/{len(BADGES)}**\n"
            f"🌌 Prestige: **{prestige_state.rank}** • bónusz: **+{round(prestige_state.income_bonus * 100)}%**\n"
            f"👥 Crew: **{crew_membership.crew.name if crew_membership else '—'}**"
            + (f" • Level **{crew_membership.crew.level}** • **+{crew_membership.crew.income_bonus * 100:g}%**" if crew_membership else "")
            + f"\n🔥 Daily streak: **{streak}** • rekord: **{best_streak}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="💹 Pénzmozgás",
        value=f"Kereset: **${compact_number(earned)}**\nVeszteség: **${compact_number(lost)}**",
        inline=True,
    )

    jail = await bot.economy.jail_status(guild_id, target.id)
    if jail:
        embed.add_field(name="🚔 Börtön", value=f"Szabadulás: <t:{int(jail.timestamp())}:R>", inline=True)

    created = datetime.fromisoformat(str(data["created_at"]))
    embed.set_footer(text=f"Yoru • Economy kezdete: {created:%Y-%m-%d}")
    return embed


async def build_statistics_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    data = await bot.economy.profile(guild_id, target.id)
    stats = data.get("statistics", {}) if isinstance(data.get("statistics", {}), dict) else {}

    def s(key: str, fallback: int = 0) -> int:
        return int(stats.get(key, fallback))

    embed = discord.Embed(title="📊 Statisztikák", color=discord.Color.blurple())
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)

    earned = s("economy.earned", int(data.get("money_earned", 0)))
    lost = s("economy.lost", int(data.get("money_lost", 0)))
    embed.add_field(
        name="💰 Economy",
        value=(
            f"Kereset: **${compact_number(earned)}**\n"
            f"Veszteség: **${compact_number(lost)}**\n"
            f"Befizetve: **${compact_number(s('economy.deposited'))}**\n"
            f"Kivéve: **${compact_number(s('economy.withdrawn'))}**"
        ),
        inline=True,
    )

    embed.add_field(
        name="🛠️ Aktivitás",
        value=(
            f"Work: **{s('work.count', int(data.get('work_count', 0))):,}**\n"
            f"Search: **{s('search.count', int(data.get('search_count', 0))):,}**\n"
            f"Beg: **{s('beg.count', int(data.get('beg_count', 0))):,}**\n"
            f"Slut: **{s('slut.count'):,}**"
        ).replace(",", " "),
        inline=True,
    )

    embed.add_field(
        name="🕵️ Crime & Rob",
        value=(
            f"Crime: **{s('crime.success', int(data.get('crime_success', 0)))}W / {s('crime.fail', int(data.get('crime_failed', 0)))}L**\n"
            f"Rablás: **{s('rob.success', int(data.get('rob_success', 0)))}W / {s('rob.fail', int(data.get('rob_failed', 0)))}L**\n"
            f"Rob profit: **${compact_number(s('rob.profit', int(data.get('rob_profit', 0))))}**"
        ),
        inline=True,
    )

    gamble_plays = s("gambling.plays")
    gamble_wins = s("gambling.wins", int(data.get("game_wins", 0)))
    gamble_losses = s("gambling.losses")
    gamble_profit = s("gambling.profit", int(data.get("gambling_profit", 0)))
    embed.add_field(
        name="🎰 Gambling",
        value=(
            f"Játékok: **{gamble_plays:,}**\n"
            f"Eredmény: **{gamble_wins}W / {gamble_losses}L**\n"
            f"Profit: **${compact_number(gamble_profit)}**\n"
            f"Kedvenc: **{_favorite_game(stats)}**"
        ).replace(",", " "),
        inline=True,
    )

    embed.add_field(
        name="🎁 Community",
        value=(
            f"Jackpot win: **{s('community.jackpot.wins', int(data.get('jackpot_wins', 0)))}**\n"
            f"Lottery win: **{s('community.lottery.wins', int(data.get('lottery_wins', 0)))}**\n"
            f"Kincses Láda: **{s('community.treasure_chest.participations')}**\n"
            f"Hirtelen Halál win: **{s('community.sudden_death.wins')}**"
        ),
        inline=True,
    )

    embed.add_field(
        name="📈 Egyéb",
        value=(
            f"Befektetés profit: **${compact_number(s('investment.profit', int(data.get('investment_profit', 0))))}**\n"
            f"Sorsjegy: **{s('scratch.count', int(data.get('scratch_count', 0)))}**\n"
            f"Weekly / Monthly: **{s('weekly.count', int(data.get('weekly_count', 0)))} / {s('monthly.count', int(data.get('monthly_count', 0)))}**"
        ),
        inline=True,
    )

    prestige_state = await bot.prestige.state(guild_id, target.id)
    embed.add_field(
        name="🌌 Prestige",
        value=(
            f"Rang: **P{prestige_state.rank}**\n"
            f"Income bónusz: **+{round(prestige_state.income_bonus * 100)}%**\n"
            f"Feláldozott vagyon: **${compact_number(s('prestige.wealth_sacrificed'))}**\n"
            f"Extra income: **${compact_number(s('prestige.bonus_earned'))}**"
        ),
        inline=True,
    )

    crew_membership = await bot.crew.get_membership(guild_id, target.id)
    embed.add_field(
        name="👥 Crew",
        value=(
            f"Crew: **{crew_membership.crew.name if crew_membership else '—'}**\n"
            f"Befizetve: **${compact_number(s('crew.contributed'))}**\n"
            f"Crew bónusz: **${compact_number(s('crew.bonus_earned'))}**\n"
            f"Csatlakozások: **{s('crew.joined')}**"
        ),
        inline=True,
    )

    embed.set_footer(text="Yoru • Részletes statisztika")
    return embed


async def build_inventory_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    items = await bot.shop.inventory_detailed(guild_id, target.id)
    embed = discord.Embed(title="🎒 Inventory", color=discord.Color.teal())
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)

    if not items:
        embed.description = "*Az inventory üres.*"
        embed.set_footer(text="Yoru • Inventory")
        return embed

    rarity_order = ["mythic", "legendary", "epic", "rare", "common"]
    grouped: dict[str, list[tuple]] = {key: [] for key in rarity_order}
    for row in items:
        item_id, name, emoji, quantity, rarity, category = row
        grouped.setdefault(rarity, []).append(row)

    for rarity in rarity_order:
        rows = grouped.get(rarity, [])
        if not rows:
            continue
        r_emoji, r_name = RARITY_META.get(rarity, ("⚪", rarity.title()))
        lines = []
        for item_id, name, emoji, quantity, _rarity, category in rows:
            c_emoji, c_name = CATEGORY_META.get(category, ("📦", category.title()))
            lines.append(f"{emoji} **{name}** × **{quantity}**\n-# {c_emoji} {c_name} • `{item_id}`")
        embed.add_field(name=f"{r_emoji} {r_name}", value="\n".join(lines), inline=False)

    total_qty = sum(int(row[3]) for row in items)
    embed.set_footer(text=f"Yoru • {len(items)} item típus • {total_qty} tárgy")
    return embed


async def build_achievements_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    unlocked_order = await bot.progression.achievements(guild_id, target.id)
    unlocked = set(unlocked_order)
    stats = await bot.statistics.get_many(guild_id, target.id)
    profile = await bot.economy.profile(guild_id, target.id)
    wealth = int(profile["wallet"]) + int(profile["bank"])

    embed = discord.Embed(title="🏆 Achievementek", color=GOLD)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)

    category_names = {
        "activity": "🛠️ Aktivitás",
        "crime": "🕵️ Crime & Rob",
        "gambling": "🎰 Gambling",
        "wealth": "💎 Vagyon",
        "community": "🎁 Community",
        "inventory": "📦 Inventory",
        "market": "📈 Market",
        "prestige": "🌌 Prestige",
        "social": "👥 Social / Crew",
        "general": "⭐ Egyéb",
    }
    category_counts: dict[str, list[int]] = {}
    for achievement_id, definition in ACHIEVEMENT_DEFINITIONS.items():
        counts = category_counts.setdefault(definition.category, [0, 0])
        counts[1] += 1
        if achievement_id in unlocked:
            counts[0] += 1

    summary = []
    for category, (done, total) in category_counts.items():
        summary.append(f"{category_names.get(category, category.title())}: **{done}/{total}**")
    embed.add_field(name="📚 Haladás", value="\n".join(summary), inline=False)

    if unlocked_order:
        recent = []
        for achievement_id in unlocked_order[-6:][::-1]:
            definition = ACHIEVEMENT_DEFINITIONS.get(achievement_id)
            if definition:
                recent.append(f"✅ **{definition.name}**")
        if recent:
            embed.add_field(name="🆕 Legutóbbi feloldások", value="\n".join(recent), inline=False)

    next_goals: list[tuple[float, str]] = []
    for achievement_id, definition in ACHIEVEMENT_DEFINITIONS.items():
        if achievement_id in unlocked:
            continue
        if definition.wealth_target is not None:
            current = wealth
            target_value = definition.wealth_target
        elif definition.stat is not None:
            current = int(stats.get(definition.stat, 0))
            target_value = definition.target
        else:
            continue
        ratio = min(1.0, current / max(1, target_value))
        line = (
            f"🔒 **{definition.name}**\n"
            f"-# `{progress_bar(current, target_value, 8)}` {min(current, target_value):,}/{target_value:,}".replace(",", " ")
        )
        next_goals.append((ratio, line))
    next_goals.sort(key=lambda pair: pair[0], reverse=True)
    if next_goals:
        embed.add_field(name="🎯 Következő célok", value="\n".join(line for _, line in next_goals[:5]), inline=False)

    embed.set_footer(text=f"Yoru • Feloldva: {len(unlocked)}/{len(ACHIEVEMENT_DEFINITIONS)}")
    return embed


async def build_titles_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    available = await bot.progression.titles(guild_id, target.id)
    data = await bot.economy.profile(guild_id, target.id)
    selected = str(data.get("selected_title", "Kezdő"))
    embed = discord.Embed(title="🎖️ Címek", color=discord.Color.purple())
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.add_field(name="Aktív cím", value=f"**{selected}**", inline=False)
    embed.add_field(name="Feloldva", value=" • ".join(f"`{x}`" for x in available) or "—", inline=False)
    embed.set_footer(text="Yoru • Saját cím: !title <név> vagy /title")
    return embed


async def build_badges_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    unlocked = set(await bot.progression.badges(guild_id, target.id))
    embed = discord.Embed(title="💠 Badge-ek", color=discord.Color.blue())
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    lines = []
    for badge_id, (emoji, name, description, _requirement) in BADGES.items():
        mark = "✅" if badge_id in unlocked else "🔒"
        lines.append(f"{mark} {emoji} **{name}**\n-# {description}")
    embed.description = "\n".join(lines) if lines else "Még nincsenek badge-ek."
    embed.set_footer(text=f"Yoru • Feloldva: {len(unlocked)}/{len(BADGES)}")
    return embed


async def build_quests_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    daily = await bot.quests.get_quests(guild_id, target.id, "daily")
    weekly = await bot.quests.get_quests(guild_id, target.id, "weekly")
    embed = discord.Embed(title="🎯 Questek", color=BRAND)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)

    def summarize(rows) -> str:
        lines = []
        for quest in rows:
            if quest.claimed:
                status = "✅ átvéve"
            elif quest.completed:
                status = "🎁 kész"
            else:
                status = f"{quest.progress}/{quest.target}"
            lines.append(f"{quest.definition.emoji} **{quest.definition.title}** • {status}")
        return "\n".join(lines) or "—"

    embed.add_field(name="☀️ Napi", value=summarize(daily), inline=False)
    embed.add_field(name="📅 Heti", value=summarize(weekly), inline=False)
    embed.description = "A jutalmakat a `!quests` vagy `/quests` panelen tudod átvenni."
    embed.set_footer(text="Yoru • Quest rendszer")
    return embed


async def build_crew_profile_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    embed = await build_crew_embed(bot, guild_id, target)
    embed.set_footer(text="Yoru • Crew kezelés: !crew vagy /crew")
    return embed


async def build_prestige_profile_embed(bot, guild_id: int, target: discord.abc.User) -> discord.Embed:
    state = await bot.prestige.state(guild_id, target.id)
    embed = discord.Embed(title="🌌 Prestige", color=GOLD if state.eligible else BRAND)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.description = (
        f"**Prestige rang:** P{state.rank}\n"
        f"**Állandó income bónusz:** +{round(state.income_bonus * 100)}%\n"
        f"**Lifetime feláldozott vagyon:** {money(state.total_wealth_sacrificed)}"
    )
    embed.add_field(
        name=f"🌠 Következő: Prestige {state.rank + 1}",
        value=(
            f"⭐ Level: `{progress_bar(state.current_level, state.required_level, 10)}` "
            f"**{state.current_level}/{state.required_level}**\n"
            f"💎 Vagyon: `{progress_bar(state.current_wealth, state.required_wealth, 10)}` "
            f"**{money(state.current_wealth)} / {money(state.required_wealth)}**\n"
            f"🚀 Következő bónusz: **+{round(state.next_income_bonus * 100)}%**"
        ),
        inline=False,
    )
    embed.add_field(
        name="♻️ Prestige reset",
        value="Tárca, bank, level, normál inventory és boosterek nullázódnak. Lifetime statok, achievementek, badge-ek, címek és prémium reward itemek megmaradnak.",
        inline=False,
    )
    embed.set_footer(text="Yoru • Végrehajtás: !prestige vagy /prestige")
    return embed


class ProfileView(discord.ui.View):
    def __init__(self, bot, guild_id: int, target: discord.abc.User, requester_id: int, *, initial_page: str = "overview") -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.target = target
        self.requester_id = requester_id
        self.page = initial_page
        self._sync_button_styles()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("❌ Ezt a profilpanelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    def _sync_button_styles(self) -> None:
        page_by_custom = {
            "yoru_profile_overview": "overview",
            "yoru_profile_stats": "stats",
            "yoru_profile_inventory": "inventory",
            "yoru_profile_achievements": "achievements",
            "yoru_profile_titles": "titles",
            "yoru_profile_badges": "badges",
            "yoru_profile_quests": "quests",
            "yoru_profile_crew": "crew",
            "yoru_profile_prestige": "prestige",
        }
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.style = discord.ButtonStyle.primary if page_by_custom.get(item.custom_id) == self.page else discord.ButtonStyle.secondary

    async def build_current_embed(self) -> discord.Embed:
        builders = {
            "overview": build_overview_embed,
            "stats": build_statistics_embed,
            "inventory": build_inventory_embed,
            "achievements": build_achievements_embed,
            "titles": build_titles_embed,
            "badges": build_badges_embed,
            "quests": build_quests_embed,
            "crew": build_crew_profile_embed,
            "prestige": build_prestige_profile_embed,
        }
        return await builders[self.page](self.bot, self.guild_id, self.target)

    async def _switch(self, interaction: discord.Interaction, page: str) -> None:
        self.page = page
        self._sync_button_styles()
        await interaction.response.edit_message(embed=await self.build_current_embed(), view=self)

    @discord.ui.button(label="Profil", emoji="👤", style=discord.ButtonStyle.primary, custom_id="yoru_profile_overview", row=0)
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "overview")

    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_stats", row=0)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "stats")

    @discord.ui.button(label="Inventory", emoji="🎒", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_inventory", row=0)
    async def inventory(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "inventory")

    @discord.ui.button(label="Achievement", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_achievements", row=1)
    async def achievements(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "achievements")

    @discord.ui.button(label="Címek", emoji="🎖️", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_titles", row=1)
    async def titles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "titles")

    @discord.ui.button(label="Badge-ek", emoji="💠", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_badges", row=1)
    async def badges(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "badges")

    @discord.ui.button(label="Questek", emoji="🎯", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_quests", row=2)
    async def quests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "quests")

    @discord.ui.button(label="Crew", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_crew", row=2)
    async def crew(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "crew")

    @discord.ui.button(label="Prestige", emoji="🌌", style=discord.ButtonStyle.secondary, custom_id="yoru_profile_prestige", row=2)
    async def prestige(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._switch(interaction, "prestige")


async def make_profile_view(bot, guild_id: int, target: discord.abc.User, requester_id: int, *, initial_page: str = "overview") -> tuple[discord.Embed, ProfileView]:
    view = ProfileView(bot, guild_id, target, requester_id, initial_page=initial_page)
    return await view.build_current_embed(), view
