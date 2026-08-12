from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands, tasks

from app import activity_config as cfg
from app.amounts import parse_amount
from app.cogs.settings import OwnedView, PagedGuildChannelSelect, PagedGuildRoleSelect
from app.database import Database
from app.services.activity import ActivityService, ActivityUpdate
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed, money, progress_bar

logger = logging.getLogger(__name__)


class ActivityLevelChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "ActivitySettingsView", guild: discord.Guild) -> None:
        super().__init__(
            view,
            guild,
            page_attr="channel_page",
            selection_key="levelup_channel",
            placeholder="Level-up értesítési csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=0,
        )


class ActivityMilestoneRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "ActivityMilestoneView", guild: discord.Guild) -> None:
        super().__init__(
            view,
            guild,
            page_attr="role_page",
            selection_key="milestone_role",
            placeholder=f"Lv. {view.level} milestone rang…",
            row=1,
        )


class ChatTuningModal(discord.ui.Modal, title="Activity • Chat beállítások"):
    xp_min = discord.ui.TextInput(label="Minimum XP / qualifying üzenet", max_length=4)
    xp_max = discord.ui.TextInput(label="Maximum XP / qualifying üzenet", max_length=4)
    cooldown = discord.ui.TextInput(label="XP cooldown (másodperc)", max_length=4)
    min_interval = discord.ui.TextInput(label="Message anti-farm idő (másodperc)", max_length=4)

    def __init__(self, view: "ActivitySettingsView", current: tuple[int, int, int, int]) -> None:
        super().__init__()
        self.parent_view = view
        values = [self.xp_min, self.xp_max, self.cooldown, self.min_interval]
        for item, value in zip(values, current, strict=True):
            item.default = str(value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.service.set_chat_tuning(
                interaction.guild_id,
                xp_min=int(str(self.xp_min.value)),
                xp_max=int(str(self.xp_max.value)),
                cooldown=int(str(self.cooldown.value)),
                min_interval=int(str(self.min_interval.value)),
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class VoiceTuningModal(discord.ui.Modal, title="Activity • Voice beállítások"):
    xp_per_minute = discord.ui.TextInput(label="Voice XP / qualifying perc", max_length=4)

    def __init__(self, view: "ActivitySettingsView", current: int) -> None:
        super().__init__()
        self.parent_view = view
        self.xp_per_minute.default = str(current)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.service.set_voice_tuning(
                interaction.guild_id,
                xp_per_minute=int(str(self.xp_per_minute.value)),
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


MILESTONE_LEVEL_PAGE_SIZE = 23
MILESTONE_NAV_PREV = "__milestone_prev__"
MILESTONE_NAV_NEXT = "__milestone_next__"


class AddMilestoneModal(discord.ui.Modal, title="Activity • Új milestone"):
    level = discord.ui.TextInput(label="Activity Level", placeholder="pl. 225", max_length=5)
    role_name = discord.ui.TextInput(label="Rang neve", placeholder="pl. Nagytőkés", max_length=100)
    hourly_income = discord.ui.TextInput(
        label="Role Income / óra (0 = kikapcsolva)",
        placeholder="0 / 150k / 2m",
        default="0",
        max_length=24,
    )

    def __init__(self, view: "ActivityMilestoneView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        guild = interaction.guild
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ Yoru-nak **Rangok kezelése** jogosultság kell az új milestone rang létrehozásához.", ephemeral=True)
        try:
            level = int(str(self.level.value).strip())
            name = str(self.role_name.value).strip()
            raw_income = str(self.hourly_income.value).strip().lower()
            income = 0 if raw_income in {"0", "off", "ki", "none", "nincs"} else parse_amount(raw_income)
            row = await self.parent_view.cog.service.add_milestone(
                guild.id,
                level,
                name,
                hourly_income=max(0, income),
                role_color=self.parent_view.cog.default_milestone_color(len(self.parent_view.levels)),
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

        # New milestones create their Discord role automatically when possible.
        role = await self.parent_view.cog.create_role_for_milestone(guild, row)
        if role is None:
            await self.parent_view.cog.service.delete_milestone(guild.id, level)
            return await interaction.response.send_message("❌ A Discord rang létrehozása nem sikerült, ezért a milestone-t sem mentettem el.", ephemeral=True)
        await self.parent_view.cog.db.set_role_income(guild.id, role.id, int(row["hourly_income"]))
        self.parent_view.level = level
        self.parent_view.milestone_page = await self.parent_view.cog.milestone_page_for_level(guild.id, level)
        self.parent_view.role_page = 0
        await self.parent_view.refresh(interaction)


class EditMilestoneModal(discord.ui.Modal, title="Activity • Milestone szerkesztése"):
    level = discord.ui.TextInput(label="Activity Level", max_length=5)
    role_name = discord.ui.TextInput(label="Rang neve", max_length=100)
    hourly_income = discord.ui.TextInput(label="Role Income / óra (0 = OFF)", max_length=24)

    def __init__(self, view: "ActivityMilestoneView", row: dict) -> None:
        super().__init__()
        self.parent_view = view
        self.level.default = str(row["level"])
        self.role_name.default = str(row["role_name"])
        self.hourly_income.default = str(int(row.get("hourly_income") or 0))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or self.parent_view.level is None:
            return
        guild = interaction.guild
        old_level = int(self.parent_view.level)
        try:
            new_level = int(str(self.level.value).strip())
            name = str(self.role_name.value).strip()
            raw_income = str(self.hourly_income.value).strip().lower()
            income = 0 if raw_income in {"0", "off", "ki", "none", "nincs"} else parse_amount(raw_income)
            if income < 0:
                raise ValueError("A Role Income nem lehet negatív.")
            rows = await self.parent_view.cog.service.get_milestones(guild.id)
            current = next((row for row in rows if int(row["level"]) == old_level), None)
            if current is None:
                raise ValueError("A milestone már nem létezik.")
            if not (1 <= new_level <= cfg.ACTIVITY_MAX_MILESTONE_LEVEL):
                raise ValueError(f"A milestone szint 1–{cfg.ACTIVITY_MAX_MILESTONE_LEVEL} között legyen.")
            if not name:
                raise ValueError("A rang neve nem lehet üres.")
            if any(int(row["level"]) != old_level and int(row["level"]) == new_level for row in rows):
                raise ValueError(f"Már létezik Lv. {new_level} milestone.")
            if any(int(row["level"]) != old_level and str(row["role_name"]).casefold() == name.casefold() for row in rows):
                raise ValueError("Már van milestone ezzel a rangnévvel.")
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

        role = guild.get_role(int(current["role_id"])) if current.get("role_id") else None
        if role is not None and role.name != name:
            if not self.parent_view.cog.can_manage_role(guild, role):
                return await interaction.response.send_message(
                    "❌ Ezt a rangot Yoru nem tudja átnevezni. Tedd Yoru legmagasabb rangja alá.",
                    ephemeral=True,
                )
            try:
                await role.edit(name=name, reason=f"Yoru Activity milestone edit • Lv. {new_level}")
            except (discord.Forbidden, discord.HTTPException) as exc:
                return await interaction.response.send_message(f"❌ Nem sikerült átnevezni a Discord rangot: `{exc}`", ephemeral=True)

        try:
            updated = await self.parent_view.cog.service.update_milestone(
                guild.id,
                old_level,
                new_level=new_level,
                role_name=(role.name if role is not None else name),
                hourly_income=income,
            )
        except (ValueError, TypeError) as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

        role_id = updated.get("role_id")
        if role_id:
            await self.parent_view.cog.db.set_role_income(guild.id, int(role_id), income)
            if role is not None:
                await self.parent_view.cog.capture_role_snapshot(role)
        self.parent_view.level = new_level
        self.parent_view.milestone_page = await self.parent_view.cog.milestone_page_for_level(guild.id, new_level)
        self.parent_view.role_page = 0
        await self.parent_view.refresh(interaction)


class MilestoneLevelSelect(discord.ui.Select):
    def __init__(self, view: "ActivityMilestoneView") -> None:
        self.parent_view = view
        levels = list(view.levels)
        page_count = max(1, (len(levels) + MILESTONE_LEVEL_PAGE_SIZE - 1) // MILESTONE_LEVEL_PAGE_SIZE)
        view.milestone_page = max(0, min(int(view.milestone_page), page_count - 1))
        start = view.milestone_page * MILESTONE_LEVEL_PAGE_SIZE
        visible = levels[start:start + MILESTONE_LEVEL_PAGE_SIZE]
        options = [
            discord.SelectOption(
                label=f"Activity Level {level}",
                value=f"milestone:{level}",
                emoji="🏅" if level < 50 else ("🏆" if level < 100 else "👑"),
                default=level == view.level,
            )
            for level in visible
        ]
        if view.milestone_page > 0:
            options.append(discord.SelectOption(label="Előző oldal", value=MILESTONE_NAV_PREV, emoji="⬅️"))
        if view.milestone_page < page_count - 1:
            options.append(discord.SelectOption(label="Következő oldal", value=MILESTONE_NAV_NEXT, emoji="➡️"))
        if not options:
            options.append(discord.SelectOption(label="Nincs milestone • adj hozzá egyet", value="__milestone_empty__"))
        self.page_count = page_count
        super().__init__(
            placeholder=(f"Milestone kiválasztása • {view.milestone_page + 1}/{page_count}. oldal" if page_count > 1 else "Milestone kiválasztása…"),
            min_values=1,
            max_values=1,
            options=options,
            disabled=not levels,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        if value == MILESTONE_NAV_PREV:
            self.parent_view.milestone_page = max(0, self.parent_view.milestone_page - 1)
            start = self.parent_view.milestone_page * MILESTONE_LEVEL_PAGE_SIZE
            self.parent_view.level = self.parent_view.levels[start] if self.parent_view.levels else None
            self.parent_view.role_page = 0
            return await self.parent_view.refresh(interaction)
        if value == MILESTONE_NAV_NEXT:
            self.parent_view.milestone_page = min(self.page_count - 1, self.parent_view.milestone_page + 1)
            start = self.parent_view.milestone_page * MILESTONE_LEVEL_PAGE_SIZE
            self.parent_view.level = self.parent_view.levels[start] if self.parent_view.levels else None
            self.parent_view.role_page = 0
            return await self.parent_view.refresh(interaction)
        if value.startswith("milestone:"):
            self.parent_view.level = int(value.split(":", 1)[1])
            self.parent_view.role_page = 0
            await self.parent_view.refresh(interaction)


class ActivitySettingsView(OwnedView):
    def __init__(
        self,
        cog: "ActivityCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        channel_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.channel_page = channel_page
        self.add_item(ActivityLevelChannelSelect(self, guild))

    async def handle_channel_selection(self, interaction: discord.Interaction, selection_key: str, channels: list[discord.abc.GuildChannel]) -> None:
        if selection_key == "levelup_channel":
            await self.cog.service.settings.set_int(interaction.guild_id, cfg.ACTIVITY_LEVELUP_CHANNEL_KEY, channels[0].id)
        await self.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, existing=self)

    @discord.ui.button(label="Activity", emoji="🌙", style=discord.ButtonStyle.success, row=1)
    async def toggle_activity(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.service.is_enabled(interaction.guild_id)
        await self.cog.service.settings.set_bool(interaction.guild_id, cfg.ACTIVITY_ENABLED_KEY, not current)
        await self.refresh(interaction)

    @discord.ui.button(label="Chat XP", emoji="💬", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_chat(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.service.chat_enabled(interaction.guild_id)
        await self.cog.service.settings.set_bool(interaction.guild_id, cfg.ACTIVITY_CHAT_ENABLED_KEY, not current)
        await self.refresh(interaction)

    @discord.ui.button(label="Voice XP", emoji="🎙️", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_voice(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.service.voice_enabled(interaction.guild_id)
        await self.cog.service.settings.set_bool(interaction.guild_id, cfg.ACTIVITY_VOICE_ENABLED_KEY, not current)
        await self.refresh(interaction)

    @discord.ui.button(label="Self-deaf kizárás", emoji="🔇", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_self_deaf(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.service.exclude_self_deaf(interaction.guild_id)
        await self.cog.service.settings.set_bool(interaction.guild_id, cfg.ACTIVITY_EXCLUDE_SELF_DEAF_KEY, not current)
        await self.refresh(interaction)

    @discord.ui.button(label="Chat tuning", emoji="⚙️", style=discord.ButtonStyle.secondary, row=2)
    async def chat_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        low, high = await self.cog.service.chat_xp_range(interaction.guild_id)
        cooldown = await self.cog.service.chat_cooldown(interaction.guild_id)
        interval = await self.cog.service.message_min_interval(interaction.guild_id)
        await interaction.response.send_modal(ChatTuningModal(self, (low, high, cooldown, interval)))

    @discord.ui.button(label="Voice tuning", emoji="🎚️", style=discord.ButtonStyle.secondary, row=2)
    async def voice_tuning(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.service.voice_xp_per_minute(interaction.guild_id)
        await interaction.response.send_modal(VoiceTuningModal(self, current))

    @discord.ui.button(label="Milestone rangok", emoji="🏆", style=discord.ButtonStyle.primary, row=2)
    async def milestones(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        levels = await self.cog.service.get_milestone_levels(interaction.guild_id)
        await self.cog.show_milestones(interaction, self.owner_id, levels[0] if levels else None)

    @discord.ui.button(label="Csatorna törlése", emoji="🧹", style=discord.ButtonStyle.secondary, row=2)
    async def clear_channel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.settings.set_int(interaction.guild_id, cfg.ACTIVITY_LEVELUP_CHANNEL_KEY, None)
        await self.refresh(interaction)

    @discord.ui.button(label="Vissza", emoji="↩️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.back_to_settings(interaction, self.owner_id)


class ActivityMilestoneView(OwnedView):
    def __init__(
        self,
        cog: "ActivityCog",
        owner_id: int,
        guild: discord.Guild,
        level: int | None,
        *,
        levels: list[int],
        role_page: int = 0,
        milestone_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.levels = sorted(set(int(value) for value in levels))
        self.level = int(level) if level is not None and int(level) in self.levels else (self.levels[0] if self.levels else None)
        self.role_page = role_page
        if self.level is not None and milestone_page == 0:
            try:
                milestone_page = self.levels.index(self.level) // MILESTONE_LEVEL_PAGE_SIZE
            except ValueError:
                milestone_page = 0
        self.milestone_page = milestone_page
        self.add_item(MilestoneLevelSelect(self))
        if self.level is not None:
            self.add_item(ActivityMilestoneRoleSelect(self, guild))

    async def handle_role_selection(self, interaction: discord.Interaction, selection_key: str, roles: list[discord.Role]) -> None:
        if selection_key != "milestone_role" or self.level is None:
            return
        role = roles[0]
        if role.managed:
            return await interaction.response.send_message("❌ Managed/integrációs rang nem használható milestone rangként.", ephemeral=True)
        if not self.cog.can_manage_role(interaction.guild, role):
            return await interaction.response.send_message(
                "❌ Ezt a rangot Yoru nem tudja kiosztani. Válassz Yoru legmagasabb rangja alatti rangot.",
                ephemeral=True,
            )
        current_rows = await self.cog.service.get_milestones(interaction.guild_id)
        if any(int(row.get("role_id") or 0) == role.id and int(row["level"]) != self.level for row in current_rows):
            return await interaction.response.send_message("❌ Ez a Discord rang már másik Activity milestone-hoz van kötve.", ephemeral=True)
        current = next(row for row in current_rows if int(row["level"]) == self.level)
        old_role_id = int(current["role_id"]) if current.get("role_id") else None
        incomes = dict(await self.cog.db.get_role_incomes(interaction.guild_id))
        income = int(current.get("hourly_income") or 0)
        if income <= 0:
            income = int(incomes.get(role.id, 0))
        if old_role_id and old_role_id != role.id:
            await self.cog.service.retire_role(interaction.guild_id, old_role_id)
            await self.cog.db.set_role_income(interaction.guild_id, old_role_id, 0)
        await self.cog.service.set_milestone(
            interaction.guild_id,
            self.level,
            role_id=role.id,
            role_name=role.name,
            hourly_income=income,
            role_color=role.colour.value,
            role_hoist=role.hoist,
            role_mentionable=role.mentionable,
        )
        if income > 0:
            await self.cog.db.set_role_income(interaction.guild_id, role.id, income)
        await self.cog.capture_role_snapshot(role)
        await self.refresh(interaction)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_milestones(interaction, self.owner_id, self.level, existing=self)

    @discord.ui.button(label="Új milestone", emoji="➕", style=discord.ButtonStyle.success, row=2)
    async def add_milestone(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(AddMilestoneModal(self))

    @discord.ui.button(label="Szerkesztés", emoji="✏️", style=discord.ButtonStyle.primary, row=2)
    async def edit_milestone(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.level is None:
            return await interaction.response.send_message("❌ Előbb adj hozzá egy milestone-t.", ephemeral=True)
        rows = await self.cog.service.get_milestones(interaction.guild_id)
        row = next(item for item in rows if int(item["level"]) == self.level)
        await interaction.response.send_modal(EditMilestoneModal(self, row))

    @discord.ui.button(label="Role leválasztása", emoji="🔗", style=discord.ButtonStyle.secondary, row=2)
    async def unlink_role(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.level is None:
            return await interaction.response.send_message("❌ Nincs kiválasztott milestone.", ephemeral=True)
        rows = await self.cog.service.get_milestones(interaction.guild_id)
        current = next(row for row in rows if int(row["level"]) == self.level)
        old_role_id = int(current["role_id"]) if current.get("role_id") else None
        if old_role_id:
            await self.cog.service.retire_role(interaction.guild_id, old_role_id)
            await self.cog.db.set_role_income(interaction.guild_id, old_role_id, 0)
        await self.cog.service.set_milestone(interaction.guild_id, self.level, role_id=None)
        if interaction.guild is not None:
            asyncio.create_task(self.cog.reconcile_guild(interaction.guild, ensure_roles=False))
        await self.refresh(interaction)

    @discord.ui.button(label="Milestone törlése", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def delete_milestone(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.level is None:
            return await interaction.response.send_message("❌ Nincs kiválasztott milestone.", ephemeral=True)
        deleted = await self.cog.service.delete_milestone(interaction.guild_id, self.level)
        if deleted.get("role_id"):
            await self.cog.db.set_role_income(interaction.guild_id, int(deleted["role_id"]), 0)
        levels = await self.cog.service.get_milestone_levels(interaction.guild_id)
        self.levels = levels
        if levels:
            next_level = min(levels, key=lambda value: abs(value - int(deleted["level"])))
            self.level = next_level
            self.milestone_page = levels.index(next_level) // MILESTONE_LEVEL_PAGE_SIZE
        else:
            self.level = None
            self.milestone_page = 0
        self.role_page = 0
        if interaction.guild is not None:
            asyncio.create_task(self.cog.reconcile_guild(interaction.guild, ensure_roles=False))
        await self.refresh(interaction)

    @discord.ui.button(label="Rangok szinkronizálása", emoji="🔄", style=discord.ButtonStyle.success, row=4)
    async def reconcile(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        changed, skipped, failed = await self.cog.reconcile_guild(interaction.guild)
        await interaction.followup.send(
            f"✅ Activity rang sync kész. **{changed}** módosítás • **{skipped}** változatlan • **{failed}** hiba/role hierarchy.",
            ephemeral=True,
        )

    @discord.ui.button(label="Activity beállítások", emoji="↩️", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_settings(interaction, self.owner_id)


class ActivityCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database, service: ActivityService) -> None:
        self.bot = bot
        self.db = db
        self.service = service
        # A member is rewarded only after being qualifying across two consecutive
        # voice ticks. Voice-state changes clear the affected channel's priming,
        # so join/leave/deaf timing cannot turn a few seconds into a full minute.
        self._voice_primed: set[tuple[int, int]] = set()
        self._milestone_bootstrap_done: set[int] = set()

    async def cog_load(self) -> None:
        if not self.voice_tick.is_running():
            self.voice_tick.start()

    async def cog_unload(self) -> None:
        if self.voice_tick.is_running():
            self.voice_tick.cancel()

    async def home_status(self, guild: discord.Guild) -> str:
        if not await self.service.is_enabled(guild.id):
            return "🔴 Kikapcsolva"
        chat = await self.service.chat_enabled(guild.id)
        voice = await self.service.voice_enabled(guild.id)
        return f"🟢 Chat {'ON' if chat else 'OFF'} • Voice {'ON' if voice else 'OFF'}"

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.service.is_enabled(guild.id)
        chat = await self.service.chat_enabled(guild.id)
        voice = await self.service.voice_enabled(guild.id)
        self_deaf = await self.service.exclude_self_deaf(guild.id)
        low, high = await self.service.chat_xp_range(guild.id)
        cooldown = await self.service.chat_cooldown(guild.id)
        interval = await self.service.message_min_interval(guild.id)
        voice_xp = await self.service.voice_xp_per_minute(guild.id)
        channel_id = await self.service.get_levelup_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        milestones = await self.service.get_milestones(guild.id)
        configured = sum(1 for row in milestones if row.get("role_id"))

        embed = base_embed(
            "🌙 Yoru • Activity",
            "Külön Discord-aktivitási progression. Nem az economy/progression Level: chat + voice aktivitásból épül, anti-farm szabályokkal.",
            SUCCESS if enabled else DANGER,
        )
        embed.add_field(name="Globális állapot", value="✅ ON" if enabled else "❌ OFF", inline=True)
        embed.add_field(name="💬 Chat XP", value=f"{'✅' if chat else '❌'} **{low}–{high} XP** • {cooldown} mp XP cooldown", inline=True)
        embed.add_field(name="🎙️ Voice XP", value=f"{'✅' if voice else '❌'} **{voice_xp} XP/perc**", inline=True)
        embed.add_field(name="🛡️ Chat anti-farm", value=f"{interval} mp message gate • 5 perc duplicate védelem • prefix parancs nem számít", inline=False)
        embed.add_field(
            name="🔊 Voice anti-farm",
            value=f"Minimum 2 qualifying real user • AFK/Stage audience kizárva • server-deaf kizárva • self-deaf: **{'kizárva' if self_deaf else 'engedélyezve'}**",
            inline=False,
        )
        embed.add_field(name="📣 Level-up csatorna", value=channel.mention if isinstance(channel, discord.abc.GuildChannel) else "Nincs • nincs automatikus értesítés", inline=True)
        embed.add_field(name="🏆 Milestone rangok", value=f"**{configured}/{len(milestones)}** beállítva", inline=True)
        embed.add_field(name="📈 XP görbe", value=f"Lv. 40 ≈ **{cfg.xp_for_level(40):,} XP** • Lv. 100 ≈ **{cfg.xp_for_level(100):,} XP**".replace(",", " "), inline=True)
        embed.set_footer(text="Yoru • Settings • Activity Level külön rendszer")
        return embed

    async def milestone_embed(self, guild: discord.Guild, level: int | None, *, page: int = 0) -> discord.Embed:
        milestones = await self.service.get_milestones(guild.id)
        page_count = max(1, (len(milestones) + MILESTONE_LEVEL_PAGE_SIZE - 1) // MILESTONE_LEVEL_PAGE_SIZE)
        page = max(0, min(int(page), page_count - 1))
        start = page * MILESTONE_LEVEL_PAGE_SIZE
        visible = milestones[start:start + MILESTONE_LEVEL_PAGE_SIZE]

        if not milestones:
            embed = base_embed(
                "🏆 Activity • Milestone rangok",
                "Még nincs Activity milestone ezen a szerveren. Nyomd meg az **Új milestone** gombot, add meg a szintet és a rang nevét; Yoru létrehozza a Discord rangot is.",
                GOLD,
            )
            embed.add_field(
                name="🔄 Discord ↔ DB sync",
                value="Ha később Discordon átnevezed/színezed/hoistolod a hozzákötött rangot, Yoru automatikusan frissíti a DB-ben tárolt állapotot.",
                inline=False,
            )
            return embed

        current = next((row for row in milestones if int(row["level"]) == int(level or -1)), milestones[0])
        role = guild.get_role(int(current["role_id"])) if current.get("role_id") else None
        lines = []
        for row in visible:
            configured_role = guild.get_role(int(row["role_id"])) if row.get("role_id") else None
            mark = "➡️" if int(row["level"]) == int(current["level"]) else ("✅" if configured_role else "⚪")
            role_text = configured_role.mention if configured_role else f"**{row['role_name']}**"
            income = int(row["hourly_income"])
            lines.append(
                f"{mark} **Lv. {row['level']}** • {role_text} • {money(income)}/óra"
                if income else f"{mark} **Lv. {row['level']}** • {role_text} • income OFF"
            )
        embed = base_embed("🏆 Activity • Milestone rangok", "\n".join(lines), GOLD)
        selected_income = int(current["hourly_income"])
        selected_income_text = f"**{money(selected_income)}/óra**" if selected_income else "**OFF**"
        color_value = role.colour.value if role is not None else int(current.get("role_color") or 0)
        embed.add_field(
            name=f"Kiválasztva • Level {current['level']}",
            value=(
                f"Rang: {role.mention if role else '**nincs hozzárendelve**'}\n"
                f"Név: **{current['role_name']}**\n"
                f"Role Income: {selected_income_text}\n"
                f"Szín: `#{color_value:06X}` • Hoist: **{'ON' if (role.hoist if role else current.get('role_hoist')) else 'OFF'}** • "
                f"Mentionable: **{'ON' if (role.mentionable if role else current.get('role_mentionable')) else 'OFF'}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔄 Discord a kinézet forrása",
            value=(
                "A hozzákötött rang nevét, színét, hoist/mentionable állapotát kézzel is módosíthatod Discordon; "
                "Yoru ezt visszaírja a DB-be. A milestone szintet és Role Income-ot a panel kezeli."
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️ Biztonság",
            value="Yoru előbb hozzáadja az új, magasabb milestone rangot, és csak siker után szedi le a régebbit. A Yoru fölötti rangokat nem piszkálja.",
            inline=False,
        )
        embed.set_footer(text=f"Yoru • Activity • {len(milestones)} milestone • {page + 1}/{page_count}. oldal")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, existing: ActivitySettingsView | None = None) -> None:
        view = ActivitySettingsView(
            self,
            owner_id,
            interaction.guild,
            channel_page=existing.channel_page if existing else 0,
        )
        await interaction.response.edit_message(embed=await self.settings_embed(interaction.guild), view=view)

    async def milestone_page_for_level(self, guild_id: int, level: int) -> int:
        levels = await self.service.get_milestone_levels(guild_id)
        try:
            return levels.index(int(level)) // MILESTONE_LEVEL_PAGE_SIZE
        except ValueError:
            return 0

    async def show_milestones(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        level: int | None,
        existing: ActivityMilestoneView | None = None,
    ) -> None:
        levels = await self.service.get_milestone_levels(interaction.guild_id)
        selected = int(level) if level is not None and int(level) in levels else (levels[0] if levels else None)
        page = existing.milestone_page if existing else (await self.milestone_page_for_level(interaction.guild_id, selected) if selected is not None else 0)
        view = ActivityMilestoneView(
            self,
            owner_id,
            interaction.guild,
            selected,
            levels=levels,
            role_page=existing.role_page if existing else 0,
            milestone_page=page,
        )
        await interaction.response.edit_message(
            embed=await self.milestone_embed(interaction.guild, selected, page=view.milestone_page),
            view=view,
        )

    async def back_to_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings_cog = self.bot.get_cog("SettingsCog")
        if settings_cog is None or not hasattr(settings_cog, "show_home"):
            return await interaction.response.send_message("❌ A Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, owner_id)

    def can_manage_role(self, guild: discord.Guild, role: discord.Role) -> bool:
        me = guild.me
        return bool(me and me.guild_permissions.manage_roles and not role.managed and role < me.top_role)

    @staticmethod
    def default_milestone_color(index: int) -> int:
        palette = (
            0x6B7280, 0x64748B, 0x71717A, 0x78716C, 0x475569,
            0x0EA5E9, 0x10B981, 0x22C55E, 0xF97316, 0xEF4444,
            0x8B5CF6, 0xBE123C, 0xEAB308, 0x14B8A6, 0xD100D1,
        )
        return palette[max(0, int(index)) % len(palette)]

    async def capture_role_snapshot(self, role: discord.Role) -> dict | None:
        return await self.service.sync_role_snapshot(
            role.guild.id,
            role.id,
            role_name=role.name,
            role_color=role.colour.value,
            role_hoist=role.hoist,
            role_mentionable=role.mentionable,
        )

    async def create_role_for_milestone(self, guild: discord.Guild, row: dict) -> discord.Role | None:
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return None
        try:
            role = await guild.create_role(
                name=str(row["role_name"]),
                permissions=discord.Permissions.none(),
                colour=discord.Colour(int(row.get("role_color") or cfg.ACTIVITY_DEFAULT_ROLE_COLOR)),
                hoist=bool(row.get("role_hoist", False)),
                mentionable=bool(row.get("role_mentionable", False)),
                reason=f"Yoru Activity milestone • Lv. {row['level']}",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None
        await self.service.set_milestone(
            guild.id,
            int(row["level"]),
            role_id=role.id,
            role_name=role.name,
            role_color=role.colour.value,
            role_hoist=role.hoist,
            role_mentionable=role.mentionable,
            hourly_income=int(row.get("hourly_income") or 0),
        )
        return role

    async def ensure_milestone_roles(self, guild: discord.Guild, *, create_missing: bool = True) -> tuple[int, int, int]:
        """Keep mappings alive without overwriting Discord-side appearance.

        Existing role ID wins. If that role still exists, its name/color/hoist/
        mentionable state is copied Discord -> DB. If it is missing, Yoru first
        tries exact-name binding and only then recreates from the last DB snapshot.
        """
        rows = await self.service.get_milestones(guild.id)
        bound = created = failed = 0
        for index, row in enumerate(rows):
            role_id = row.get("role_id")
            role = guild.get_role(int(role_id)) if role_id else None
            if role is not None:
                await self.capture_role_snapshot(role)
            else:
                desired_name = str(row["role_name"])
                role = next(
                    (
                        candidate for candidate in reversed(guild.roles)
                        if not candidate.managed and candidate.name.casefold() == desired_name.casefold()
                    ),
                    None,
                )
                if role is not None:
                    # Do not steal a role already bound to another milestone.
                    used = {
                        int(other.get("role_id") or 0)
                        for other in rows
                        if int(other["level"]) != int(row["level"])
                    }
                    if role.id in used:
                        role = None
                    else:
                        bound += 1
                        await self.service.set_milestone(guild.id, int(row["level"]), role_id=role.id)
                        await self.capture_role_snapshot(role)
            if role is None and create_missing:
                # For old rows without an appearance snapshot, give each newly
                # created role a sensible distinct fallback color.
                if int(row.get("role_color") or 0) == cfg.ACTIVITY_DEFAULT_ROLE_COLOR:
                    row = dict(row)
                    row["role_color"] = self.default_milestone_color(index)
                role = await self.create_role_for_milestone(guild, row)
                if role is not None:
                    created += 1
            if role is None:
                failed += 1
                continue
            income = int(row.get("hourly_income") or 0)
            if income > 0:
                await self.db.set_role_income(guild.id, role.id, income)
        return bound, created, failed

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # One-time migration/reconcile for servers that already used Activity.
        # Brand-new servers do not get a full default ladder just by adding the
        # bot; opening/configuring Activity initializes the server-owned layout.
        for guild in self.bot.guilds:
            if guild.id in self._milestone_bootstrap_done:
                continue
            raw = await self.service.settings.get_list(guild.id, cfg.ACTIVITY_MILESTONES_KEY, [])
            known_names = {str(row["role_name"]).casefold() for row in cfg.default_milestone_layout()}
            has_named_roles = any(role.name.casefold() in known_names for role in guild.roles)
            if raw or has_named_roles:
                try:
                    await self.ensure_milestone_roles(guild, create_missing=True)
                    await self.reconcile_guild(guild, ensure_roles=False)
                except Exception:
                    logger.exception("Activity milestone bootstrap failed for guild %s", guild.id)
            self._milestone_bootstrap_done.add(guild.id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        # Discord is authoritative for Activity role appearance. Manual edits
        # are immediately mirrored back to the persistent guild DB.
        if (
            before.name == after.name
            and before.colour.value == after.colour.value
            and before.hoist == after.hoist
            and before.mentionable == after.mentionable
        ):
            return
        try:
            await self.capture_role_snapshot(after)
        except Exception:
            logger.exception("Activity role snapshot sync failed for role %s", after.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        # Deleting a bound Activity role directly in Discord is treated as an
        # accidental deletion: keep the milestone config and recreate the role
        # from the last safe DB snapshot. To intentionally remove a milestone,
        # use /settings -> Activity -> Milestone rangok -> Milestone törlése.
        try:
            target = await self.service.mark_role_deleted(role.guild.id, role.id)
            if target is None:
                return
            await asyncio.sleep(0.5)
            current = await self.service.get_milestones(role.guild.id)
            target = next((row for row in current if int(row["level"]) == int(target["level"])), None)
            if target is None or target.get("role_id"):
                return
            await self.ensure_milestone_roles(role.guild, create_missing=True)
            await self.reconcile_guild(role.guild, ensure_roles=False)
        except Exception:
            logger.exception("Activity deleted-role recovery failed for role %s", role.id)

    async def reconcile_member(self, member: discord.Member) -> tuple[bool, str]:
        if member.bot:
            return False, "bot"
        profile = await self.service.profile(member.guild.id, member.id)
        milestones = await self.service.get_milestones(member.guild.id)
        configured: list[tuple[int, discord.Role]] = []
        for row in milestones:
            role_id = row.get("role_id")
            role = member.guild.get_role(int(role_id)) if role_id else None
            if role is not None:
                configured.append((int(row["level"]), role))

        eligible = [(level, role) for level, role in configured if level <= profile.level]
        target = max(eligible, key=lambda item: item[0])[1] if eligible else None
        retired_ids = await self.service.get_retired_role_ids(member.guild.id)
        retired_roles = [member.guild.get_role(role_id) for role_id in retired_ids]
        old_roles = [role for _, role in configured if role in member.roles and role != target]
        old_roles.extend(role for role in retired_roles if role is not None and role in member.roles and role != target and role not in old_roles)
        changed = False

        if target is not None and target not in member.roles:
            if not self.can_manage_role(member.guild, target):
                return False, "hierarchy"
            try:
                await member.add_roles(target, reason=f"Yoru Activity Level {profile.level}")
                changed = True
            except (discord.Forbidden, discord.HTTPException):
                return False, "add_failed"

        # Crucial safety: old roles are removed only after the target is already on
        # the member (or when there is no eligible target at all).
        if target is not None and target not in member.roles and not changed:
            return False, "target_missing"

        removable = [role for role in old_roles if self.can_manage_role(member.guild, role)]
        if removable:
            try:
                await member.remove_roles(*removable, reason=f"Yoru Activity milestone sync • Level {profile.level}")
                changed = True
            except (discord.Forbidden, discord.HTTPException):
                return changed, "remove_failed"
        return changed, "ok"

    async def reconcile_guild(self, guild: discord.Guild, *, ensure_roles: bool = True) -> tuple[int, int, int]:
        if ensure_roles:
            await self.ensure_milestone_roles(guild, create_missing=True)
        changed = skipped = failed = 0
        user_ids = await self.db.list_activity_user_ids(guild.id)
        for index, user_id in enumerate(user_ids, 1):
            member = guild.get_member(user_id)
            if member is None or member.bot:
                skipped += 1
                continue
            did_change, status = await self.reconcile_member(member)
            if did_change:
                changed += 1
            elif status in {"ok", "bot"}:
                skipped += 1
            else:
                failed += 1
            if index % 20 == 0:
                await asyncio.sleep(0.25)
        return changed, skipped, failed

    async def handle_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        update = await self.service.record_message(message.guild.id, message.author.id, message.content)
        if update and update.xp_awarded > 0 and hasattr(self.bot, "factions"):
            await self.bot.factions.record_activity_xp(message.guild.id, message.author.id, update.xp_awarded)
        if update and update.leveled_up and isinstance(message.author, discord.Member):
            await self._handle_level_up(message.author, update)

    async def _handle_level_up(self, member: discord.Member, update: ActivityUpdate) -> None:
        await self.reconcile_member(member)
        channel_id = await self.service.get_levelup_channel_id(member.guild.id)
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return
        level, current, needed, percent = cfg.level_progress(update.profile.total_xp)
        embed = base_embed(
            "🌙 Activity Level Up!",
            f"{member.mention} elérte az **Activity Level {level}** szintet!",
            SUCCESS,
        )
        embed.add_field(name="✨ Activity XP", value=f"**{update.profile.total_xp:,} XP**".replace(",", " "), inline=True)
        embed.add_field(name="💬 Üzenetek", value=f"**{update.profile.message_count:,}**".replace(",", " "), inline=True)
        embed.add_field(name="🎙️ Voice", value=f"**{self.service.voice_time_text(update.profile.voice_seconds)}**", inline=True)
        embed.add_field(name="Következő szint", value=f"`{progress_bar(current, needed, 14)}` **{percent}%**", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Yoru • Activity Level")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    def _voice_eligible(self, member: discord.Member, *, exclude_self_deaf: bool) -> bool:
        if member.bot or member.voice is None or member.voice.channel is None:
            return False
        state = member.voice
        if state.deaf:
            return False
        if exclude_self_deaf and state.self_deaf:
            return False
        if state.suppress:
            return False
        return True

    def _reset_voice_priming_for_channel(self, guild_id: int, channel: discord.abc.GuildChannel | None) -> None:
        if channel is None:
            return
        member_ids = {member.id for member in getattr(channel, "members", []) if isinstance(member, discord.Member)}
        if not member_ids:
            return
        self._voice_primed.difference_update((guild_id, user_id) for user_id in member_ids)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # Any relevant state change breaks the continuous qualifying interval for
        # the changed member and both affected channels. This is deliberately
        # conservative and blocks join-before-tick / quick rejoin farming.
        self._voice_primed.discard((member.guild.id, member.id))
        self._reset_voice_priming_for_channel(member.guild.id, before.channel)
        if after.channel is not before.channel:
            self._reset_voice_priming_for_channel(member.guild.id, after.channel)

    @tasks.loop(seconds=cfg.ACTIVITY_VOICE_TICK_SECONDS)
    async def voice_tick(self) -> None:
        for guild in list(self.bot.guilds):
            guild_keys = {key for key in self._voice_primed if key[0] == guild.id}
            if not await self.service.is_enabled(guild.id) or not await self.service.voice_enabled(guild.id):
                self._voice_primed.difference_update(guild_keys)
                continue

            exclude_self_deaf = await self.service.exclude_self_deaf(guild.id)
            current_eligible: set[tuple[int, int]] = set()
            channels: list[discord.abc.Connectable] = [*guild.voice_channels, *guild.stage_channels]
            for channel in channels:
                if guild.afk_channel is not None and channel.id == guild.afk_channel.id:
                    continue
                members = [
                    member for member in getattr(channel, "members", [])
                    if isinstance(member, discord.Member) and self._voice_eligible(member, exclude_self_deaf=exclude_self_deaf)
                ]
                # At least two qualifying real members must be present. A deaf/
                # self-deaf second account cannot make a solo farmer eligible.
                if len(members) < 2:
                    continue
                for member in members:
                    key = (guild.id, member.id)
                    current_eligible.add(key)
                    # First qualifying tick only primes the member. A complete
                    # uninterrupted interval is required before one minute pays.
                    if key not in self._voice_primed:
                        continue
                    update = await self.service.record_voice_minute(guild.id, member.id)
                    if update and update.xp_awarded > 0 and hasattr(self.bot, "factions"):
                        await self.bot.factions.record_activity_xp(guild.id, member.id, update.xp_awarded)
                    if update and update.leveled_up:
                        await self._handle_level_up(member, update)

            self._voice_primed.difference_update(guild_keys)
            self._voice_primed.update(current_eligible)

    @voice_tick.before_loop
    async def before_voice_tick(self) -> None:
        await self.bot.wait_until_ready()
