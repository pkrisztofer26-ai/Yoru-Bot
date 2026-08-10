from __future__ import annotations

from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from app import moderation_config as modcfg
from app import member_config as membercfg
from app import community_config as communitycfg
from app.database import Database
from app.services.server_settings import PRESET_LABELS, ServerSettingsService
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed


RULE_ORDER = ["invite", "links", "spam", "duplicate", "mentions", "caps", "emoji", "words", "zalgo"]
LOG_LABELS = {
    "message_delete": "🗑️ Törölt üzenetek",
    "deleted_attachments": "🖼️ Törölt képek/fájlok",
    "message_edit": "✏️ Szerkesztett üzenetek",
    "join_leave": "📥 Join / Leave",
    "ban_kick": "🔨 Ban / Kick",
    "timeout": "🔇 Timeout / Untimeout",
    "role_nick": "🎭 Rang / Becenév",
    "moderation_actions": "🛡️ Egyéb mod műveletek",
    "automod": "🤖 AutoMod",
    "voice": "🎙️ Voice activity",
}
ACTION_LABELS = {"delete": "🗑️ Delete", "warn": "⚠️ Warn", "timeout": "🔇 Timeout"}


def _domain(raw: str) -> str:
    value = raw.strip().lower().rstrip("./")
    if not value:
        raise ValueError("Adj meg egy domaint.")
    if "://" not in value:
        value = "https://" + value
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or " " in host:
        raise ValueError("Érvénytelen domain.")
    return host



CHANNEL_SELECT_PAGE_SIZE = 23
CHANNEL_NAV_PREV = "__page_prev__"
CHANNEL_NAV_NEXT = "__page_next__"


def _channel_type_name(channel: discord.abc.GuildChannel) -> str:
    if channel.type == discord.ChannelType.category:
        return "Kategória"
    if channel.type == discord.ChannelType.news:
        return "Hírcsatorna"
    return "Szöveges csatorna"


def _paged_channel_options(
    guild: discord.Guild,
    channel_types: tuple[discord.ChannelType, ...],
    page: int,
) -> tuple[list[discord.SelectOption], int, int]:
    channels = [channel for channel in guild.channels if channel.type in channel_types]
    page_count = max(1, (len(channels) + CHANNEL_SELECT_PAGE_SIZE - 1) // CHANNEL_SELECT_PAGE_SIZE)
    page = max(0, min(page, page_count - 1))
    start = page * CHANNEL_SELECT_PAGE_SIZE
    visible = channels[start:start + CHANNEL_SELECT_PAGE_SIZE]

    options: list[discord.SelectOption] = []
    for channel in visible:
        parent = getattr(channel, "category", None)
        description = _channel_type_name(channel)
        if parent is not None and channel.type != discord.ChannelType.category:
            description += f" • {parent.name}"
        options.append(
            discord.SelectOption(
                label=(f"# {channel.name}" if channel.type != discord.ChannelType.category else f"📁 {channel.name}")[:100],
                value=f"channel:{channel.id}",
                description=description[:100],
            )
        )

    if page > 0:
        options.append(discord.SelectOption(label="Előző oldal", value=CHANNEL_NAV_PREV, emoji="⬅️", description=f"{page}/{page_count}. oldal"))
    if page < page_count - 1:
        options.append(discord.SelectOption(label="Következő oldal", value=CHANNEL_NAV_NEXT, emoji="➡️", description=f"{page + 2}/{page_count}. oldal"))

    if not options:
        options.append(discord.SelectOption(label="Nincs elérhető csatorna", value="__empty__", description="Ehhez a típushoz nincs választható csatorna."))
    return options, page, page_count


class PagedGuildChannelSelect(discord.ui.Select):
    def __init__(
        self,
        view: "OwnedView",
        guild: discord.Guild,
        *,
        page_attr: str,
        selection_key: str,
        placeholder: str,
        channel_types: tuple[discord.ChannelType, ...],
        row: int,
        max_values: int = 1,
    ) -> None:
        self.parent_view = view
        self.page_attr = page_attr
        self.selection_key = selection_key
        self.channel_types = channel_types
        options, page, page_count = _paged_channel_options(guild, channel_types, int(getattr(view, page_attr, 0)))
        setattr(view, page_attr, page)
        self.page_count = page_count
        actual_count = sum(1 for option in options if option.value.startswith("channel:"))
        disabled = actual_count == 0
        safe_max = 1 if disabled else min(max_values, actual_count)
        page_suffix = f" • {page + 1}/{page_count}. oldal" if page_count > 1 else ""
        super().__init__(
            placeholder=(placeholder + page_suffix)[:150],
            min_values=1,
            max_values=max(1, safe_max),
            options=options,
            disabled=disabled,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        values = list(self.values)
        if CHANNEL_NAV_PREV in values:
            setattr(self.parent_view, self.page_attr, max(0, int(getattr(self.parent_view, self.page_attr, 0)) - 1))
            return await self.parent_view.refresh(interaction)
        if CHANNEL_NAV_NEXT in values:
            setattr(self.parent_view, self.page_attr, min(self.page_count - 1, int(getattr(self.parent_view, self.page_attr, 0)) + 1))
            return await self.parent_view.refresh(interaction)
        if "__empty__" in values or interaction.guild is None:
            return

        channels: list[discord.abc.GuildChannel] = []
        for value in values:
            if not value.startswith("channel:"):
                continue
            try:
                channel_id = int(value.split(":", 1)[1])
            except ValueError:
                continue
            channel = interaction.guild.get_channel(channel_id)
            if channel is not None and channel.type in self.channel_types:
                channels.append(channel)
        if channels:
            await self.parent_view.handle_channel_selection(interaction, self.selection_key, channels)

ROLE_SELECT_PAGE_SIZE = 23
ROLE_NAV_PREV = "__role_page_prev__"
ROLE_NAV_NEXT = "__role_page_next__"


def _paged_role_options(guild: discord.Guild, page: int) -> tuple[list[discord.SelectOption], int, int]:
    roles = [role for role in reversed(guild.roles) if not role.is_default()]
    page_count = max(1, (len(roles) + ROLE_SELECT_PAGE_SIZE - 1) // ROLE_SELECT_PAGE_SIZE)
    page = max(0, min(page, page_count - 1))
    start = page * ROLE_SELECT_PAGE_SIZE
    visible = roles[start:start + ROLE_SELECT_PAGE_SIZE]
    options = [
        discord.SelectOption(
            label=(f"@ {role.name}")[:100],
            value=f"role:{role.id}",
            description=("Managed" if role.managed else f"Pozíció: {role.position}")[:100],
        )
        for role in visible
    ]
    if page > 0:
        options.append(discord.SelectOption(label="Előző oldal", value=ROLE_NAV_PREV, emoji="⬅️", description=f"{page}/{page_count}. oldal"))
    if page < page_count - 1:
        options.append(discord.SelectOption(label="Következő oldal", value=ROLE_NAV_NEXT, emoji="➡️", description=f"{page + 2}/{page_count}. oldal"))
    if not options:
        options.append(discord.SelectOption(label="Nincs elérhető rang", value="__role_empty__"))
    return options, page, page_count


class PagedGuildRoleSelect(discord.ui.Select):
    def __init__(
        self,
        view: "OwnedView",
        guild: discord.Guild,
        *,
        page_attr: str,
        selection_key: str,
        placeholder: str,
        row: int,
        max_values: int = 1,
    ) -> None:
        self.parent_view = view
        self.page_attr = page_attr
        self.selection_key = selection_key
        options, page, page_count = _paged_role_options(guild, int(getattr(view, page_attr, 0)))
        setattr(view, page_attr, page)
        self.page_count = page_count
        actual_count = sum(1 for option in options if option.value.startswith("role:"))
        disabled = actual_count == 0
        safe_max = 1 if disabled else min(max_values, actual_count)
        page_suffix = f" • {page + 1}/{page_count}. oldal" if page_count > 1 else ""
        super().__init__(
            placeholder=(placeholder + page_suffix)[:150],
            min_values=1,
            max_values=max(1, safe_max),
            options=options,
            disabled=disabled,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        values = list(self.values)
        if ROLE_NAV_PREV in values:
            setattr(self.parent_view, self.page_attr, max(0, int(getattr(self.parent_view, self.page_attr, 0)) - 1))
            return await self.parent_view.refresh(interaction)
        if ROLE_NAV_NEXT in values:
            setattr(self.parent_view, self.page_attr, min(self.page_count - 1, int(getattr(self.parent_view, self.page_attr, 0)) + 1))
            return await self.parent_view.refresh(interaction)
        if "__role_empty__" in values or interaction.guild is None:
            return
        roles: list[discord.Role] = []
        for value in values:
            if not value.startswith("role:"):
                continue
            try:
                role_id = int(value.split(":", 1)[1])
            except ValueError:
                continue
            role = interaction.guild.get_role(role_id)
            if role is not None:
                roles.append(role)
        if roles:
            await self.parent_view.handle_role_selection(interaction, self.selection_key, roles)


class OwnedView(discord.ui.View):
    def __init__(self, cog: "SettingsCog", owner_id: int, *, timeout: float = 600) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a beállítópanelt nem te nyitottad meg.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True)
            return False
        return True


class HomeView(OwnedView):
    @discord.ui.button(label="AutoMod", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def automod(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_automod(interaction, self.owner_id)

    @discord.ui.button(label="Moderáció", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def moderation(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_moderation(interaction, self.owner_id)

    @discord.ui.button(label="Logok", emoji="📝", style=discord.ButtonStyle.secondary, row=0)
    async def logs(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_logs(interaction, self.owner_id)

    @discord.ui.button(label="Gyors setup", emoji="✨", style=discord.ButtonStyle.success, row=0)
    async def setup(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_setup(interaction, self.owner_id)

    @discord.ui.button(label="Welcome", emoji="👋", style=discord.ButtonStyle.secondary, row=1)
    async def welcome(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_welcome(interaction, self.owner_id)

    @discord.ui.button(label="Roles", emoji="🎭", style=discord.ButtonStyle.secondary, row=1)
    async def roles(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_roles(interaction, self.owner_id)

    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def tickets(self, *_args) -> None:  # pragma: no cover - disabled
        pass

    @discord.ui.button(label="Music", emoji="🎵", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def music(self, *_args) -> None:  # pragma: no cover - disabled
        pass

    @discord.ui.button(label="Fun", emoji="🎉", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def fun(self, *_args) -> None:  # pragma: no cover - disabled
        pass

    @discord.ui.button(label="Economy", emoji="💰", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def economy(self, *_args) -> None:  # pragma: no cover - disabled
        pass

    @discord.ui.button(label="Events", emoji="🎁", style=discord.ButtonStyle.secondary, disabled=True, row=2)
    async def events(self, *_args) -> None:  # pragma: no cover - disabled
        pass

    @discord.ui.button(label="Community", emoji="🌙", style=discord.ButtonStyle.secondary, row=2)
    async def community(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_community(interaction, self.owner_id)


class RuleSelect(discord.ui.Select):
    def __init__(self, view: "AutomodView") -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(label=modcfg.AUTOMOD_RULE_LABELS[rule], value=rule, emoji={
                "invite": "🔗", "links": "🌐", "spam": "💬", "duplicate": "🔁", "mentions": "📣",
                "caps": "🔠", "emoji": "😂", "words": "🚫", "zalgo": "🌀",
            }[rule])
            for rule in RULE_ORDER
        ]
        super().__init__(placeholder="Válassz AutoMod szabályt…", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.show_rule(interaction, self.parent_view.owner_id, self.values[0])


class PresetSelect(discord.ui.Select):
    def __init__(self, view: "AutomodView") -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(label="Basic", value="basic", emoji="🟢", description="Lazább alapvédelem."),
            discord.SelectOption(label="Recommended", value="recommended", emoji="🔵", description="Yoru ajánlott alapbeállítás."),
            discord.SelectOption(label="Strict", value="strict", emoji="🔴", description="Szigorúbb spam/link védelem."),
        ]
        super().__init__(placeholder="AutoMod preset alkalmazása…", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await self.parent_view.cog.settings.apply_preset(interaction.guild.id, self.values[0])
        await interaction.response.edit_message(
            embed=await self.parent_view.cog.automod_embed(interaction.guild),
            view=AutomodView(self.parent_view.cog, self.parent_view.owner_id, True),
        )


class AutomodView(OwnedView):
    def __init__(self, cog: "SettingsCog", owner_id: int, enabled: bool) -> None:
        super().__init__(cog, owner_id)
        self.enabled = enabled
        self.add_item(RuleSelect(self))
        self.add_item(PresetSelect(self))
        self.toggle.label = "AutoMod: ON" if enabled else "AutoMod: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger

    @discord.ui.button(label="AutoMod", emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None:
            return
        enabled = not self.enabled
        await self.cog.settings.set_automod_enabled(interaction.guild.id, enabled)
        await interaction.response.edit_message(
            embed=await self.cog.automod_embed(interaction.guild),
            view=AutomodView(self.cog, self.owner_id, enabled),
        )

    @discord.ui.button(label="Kivételek", emoji="🎯", style=discord.ButtonStyle.secondary, row=0)
    async def exemptions(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_exemptions(interaction, self.owner_id, "all")

    @discord.ui.button(label="Domainek", emoji="🌐", style=discord.ButtonStyle.secondary, row=0)
    async def domains(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_domains(interaction, self.owner_id)

    @discord.ui.button(label="Szófilter", emoji="🚫", style=discord.ButtonStyle.secondary, row=0)
    async def words(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_words(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_home(interaction, self.owner_id)


class ActionSelect(discord.ui.Select):
    def __init__(self, view: "RuleView", current: str) -> None:
        self.parent_view = view
        super().__init__(
            placeholder=f"Művelet: {ACTION_LABELS.get(current, current)}",
            options=[
                discord.SelectOption(label="Delete", value="delete", emoji="🗑️", default=current == "delete"),
                discord.SelectOption(label="Warn", value="warn", emoji="⚠️", default=current == "warn"),
                discord.SelectOption(label="Timeout", value="timeout", emoji="🔇", default=current == "timeout"),
            ],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await self.parent_view.cog.settings.set_rule(interaction.guild.id, self.parent_view.rule, action=self.values[0])
        await self.parent_view.cog.show_rule(interaction, self.parent_view.owner_id, self.parent_view.rule)


class ThresholdModal(discord.ui.Modal, title="AutoMod threshold"):
    threshold = discord.ui.TextInput(label="Limit / threshold", placeholder="pl. 6", min_length=1, max_length=3)
    window = discord.ui.TextInput(
        label="Időablak másodpercben (ha van)",
        placeholder="Spam: pl. 5 • Duplicate: pl. 20",
        required=False,
        max_length=6,
    )

    def __init__(self, view: "RuleView") -> None:
        super().__init__()
        self.parent_view = view
        self.threshold.default = str(view.threshold)
        if view.window_seconds is not None:
            self.window.default = f"{view.window_seconds:g}"
        else:
            self.window.placeholder = "Ehhez a szabályhoz nincs időablak"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            threshold = int(str(self.threshold.value).strip())
            if threshold < 1 or threshold > 100:
                raise ValueError("A threshold 1–100 között legyen.")
            await self.parent_view.cog.settings.set_rule(interaction.guild_id, self.parent_view.rule, threshold=threshold)
            if self.parent_view.window_seconds is not None and str(self.window.value).strip():
                await self.parent_view.cog.settings.set_rule_window(
                    interaction.guild_id, self.parent_view.rule, float(str(self.window.value).strip().replace(",", "."))
                )
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await self.parent_view.cog.show_rule(interaction, self.parent_view.owner_id, self.parent_view.rule)


class TimeoutModal(discord.ui.Modal, title="AutoMod timeout"):
    minutes = discord.ui.TextInput(label="Timeout perc", placeholder="10", min_length=1, max_length=6)

    def __init__(self, view: "RuleView") -> None:
        super().__init__()
        self.parent_view = view
        self.minutes.default = str(max(1, view.timeout_seconds // 60))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minutes = int(str(self.minutes.value).strip())
            if minutes < 1 or minutes > 28 * 24 * 60:
                raise ValueError("1 perc és 28 nap között legyen.")
            await self.parent_view.cog.settings.set_rule(
                interaction.guild_id, self.parent_view.rule, timeout_seconds=minutes * 60
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await self.parent_view.cog.show_rule(interaction, self.parent_view.owner_id, self.parent_view.rule)


class RuleView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        rule: str,
        *,
        enabled: bool,
        action: str,
        threshold: int,
        timeout_seconds: int,
        window_seconds: float | None,
    ) -> None:
        super().__init__(cog, owner_id)
        self.rule = rule
        self.enabled = enabled
        self.threshold = threshold
        self.timeout_seconds = timeout_seconds
        self.window_seconds = window_seconds
        self.toggle.label = "Szabály: ON" if enabled else "Szabály: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        self.add_item(ActionSelect(self, action))

    @discord.ui.button(label="Szabály", emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_rule(interaction.guild_id, self.rule, enabled=not self.enabled)
        await self.cog.show_rule(interaction, self.owner_id, self.rule)

    @discord.ui.button(label="Limit / időablak", emoji="📏", style=discord.ButtonStyle.secondary, row=0)
    async def threshold_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ThresholdModal(self))

    @discord.ui.button(label="Timeout idő", emoji="⏱️", style=discord.ButtonStyle.secondary, row=0)
    async def timeout_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TimeoutModal(self))

    @discord.ui.button(label="Kivételek", emoji="🎯", style=discord.ButtonStyle.secondary, row=0)
    async def exemptions(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_exemptions(interaction, self.owner_id, self.rule)

    @discord.ui.button(label="AutoMod", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_automod(interaction, self.owner_id)


class ExemptionChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "ExemptionsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="channel",
            placeholder="Csatornák hozzáadása/törlése…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=1,
            max_values=5,
        )


class ExemptionCategorySelect(PagedGuildChannelSelect):
    def __init__(self, view: "ExemptionsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="category_page",
            selection_key="category",
            placeholder="Kategóriák hozzáadása/törlése…",
            channel_types=(discord.ChannelType.category,),
            row=2,
            max_values=5,
        )


class ExemptionRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "ExemptionsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="role_page",
            selection_key="exemption_role",
            placeholder="Rangok hozzáadása/törlése…",
            row=3,
            max_values=5,
        )


class ExemptionsView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        rule: str,
        remove_mode: bool = False,
        *,
        channel_page: int = 0,
        category_page: int = 0,
        role_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.rule = rule
        self.remove_mode = remove_mode
        self.channel_page = channel_page
        self.category_page = category_page
        self.role_page = role_page
        self.mode.label = "Mód: TÖRLÉS" if remove_mode else "Mód: HOZZÁADÁS"
        self.mode.style = discord.ButtonStyle.danger if remove_mode else discord.ButtonStyle.success
        self.add_item(ExemptionChannelSelect(self))
        self.add_item(ExemptionCategorySelect(self))
        self.add_item(ExemptionRoleSelect(self))

    async def apply(self, guild_id: int, scope_type: str, scope_id: int) -> None:
        if self.remove_mode:
            await self.cog.settings.remove_exemption(guild_id, self.rule, scope_type, scope_id)
        else:
            await self.cog.settings.add_exemption(guild_id, self.rule, scope_type, scope_id)

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        scope_type = "category" if selection_key == "category" else "channel"
        for channel in channels:
            await self.apply(interaction.guild_id, scope_type, channel.id)
        await self.cog.show_exemptions(interaction, self.owner_id, self.rule, self.remove_mode, self)

    async def handle_role_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        roles: list[discord.Role],
    ) -> None:
        if selection_key == "exemption_role":
            for role in roles:
                await self.apply(interaction.guild_id, "role", role.id)
        await self.cog.show_exemptions(interaction, self.owner_id, self.rule, self.remove_mode, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_exemptions(interaction, self.owner_id, self.rule, self.remove_mode, self)

    @discord.ui.button(label="Mód", emoji="🔄", style=discord.ButtonStyle.success, row=0)
    async def mode(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_exemptions(interaction, self.owner_id, self.rule, not self.remove_mode)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.rule == "all":
            await self.cog.show_automod(interaction, self.owner_id)
        else:
            await self.cog.show_rule(interaction, self.owner_id, self.rule)


class DomainModal(discord.ui.Modal):
    domain_input = discord.ui.TextInput(label="Domain", placeholder="example.com", min_length=3, max_length=200)

    def __init__(self, view: "DomainsView", mode: str) -> None:
        title = {"allow": "Domain engedélyezése", "block": "Domain tiltása", "remove": "Domain törlése"}[mode]
        super().__init__(title=title)
        self.parent_view = view
        self.mode = mode

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            domain = _domain(str(self.domain_input.value))
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if self.mode == "remove":
            await self.parent_view.cog.settings.remove_domain(interaction.guild_id, domain)
        else:
            await self.parent_view.cog.settings.add_domain(interaction.guild_id, self.mode, domain)
        await self.parent_view.cog.show_domains(interaction, self.parent_view.owner_id)


class DomainsView(OwnedView):
    @discord.ui.button(label="Allow", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def allow(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DomainModal(self, "allow"))

    @discord.ui.button(label="Block", emoji="⛔", style=discord.ButtonStyle.danger, row=0)
    async def block(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DomainModal(self, "block"))

    @discord.ui.button(label="Törlés", emoji="🗑️", style=discord.ButtonStyle.secondary, row=0)
    async def remove(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DomainModal(self, "remove"))

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_automod(interaction, self.owner_id)


class WordModal(discord.ui.Modal):
    word_input = discord.ui.TextInput(label="Szó / kifejezés", placeholder="Tiltott kifejezés", min_length=1, max_length=100)

    def __init__(self, view: "WordsView", remove: bool) -> None:
        super().__init__(title="Tiltott szó törlése" if remove else "Tiltott szó hozzáadása")
        self.parent_view = view
        self.remove = remove

    async def on_submit(self, interaction: discord.Interaction) -> None:
        word = str(self.word_input.value).strip().casefold()
        if self.remove:
            await self.parent_view.cog.settings.remove_word(interaction.guild_id, word)
        else:
            await self.parent_view.cog.settings.add_word(interaction.guild_id, word)
        await self.parent_view.cog.show_words(interaction, self.parent_view.owner_id)


class WordsView(OwnedView):
    @discord.ui.button(label="Hozzáadás", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(WordModal(self, False))

    @discord.ui.button(label="Törlés", emoji="➖", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(WordModal(self, True))

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_automod(interaction, self.owner_id)


class LogChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "LogsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="log",
            placeholder="Moderációs log csatorna kiválasztása…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=3,
            max_values=1,
        )


class LogToggleSelect(discord.ui.Select):
    def __init__(self, view: "LogsView", states: dict[str, bool]) -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(
                label=LOG_LABELS[key],
                value=key,
                emoji="✅" if states[key] else "❌",
                description="Bekapcsolva" if states[key] else "Kikapcsolva",
            )
            for key in LOG_LABELS
        ]
        super().__init__(placeholder="Válassz log típust a ki-/bekapcsoláshoz…", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        key = self.values[0]
        current = await self.parent_view.cog.settings.get_log_enabled(interaction.guild_id, key)
        await self.parent_view.cog.settings.set_log_enabled(interaction.guild_id, key, not current)
        await self.parent_view.cog.show_logs(interaction, self.parent_view.owner_id)


class LogsView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        states: dict[str, bool],
        guild: discord.Guild,
        *,
        channel_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.channel_page = channel_page
        self.add_item(LogToggleSelect(self, states))
        self.add_item(LogChannelSelect(self))

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if selection_key != "log" or not channels:
            return
        await self.cog.settings.set_log_channel_id(interaction.guild_id, channels[0].id)
        await self.cog.show_logs(interaction, self.owner_id, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_logs(interaction, self.owner_id, self)

    @discord.ui.button(label="Logok kikapcsolása", emoji="🛑", style=discord.ButtonStyle.danger, row=0)
    async def disable(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_log_channel_id(interaction.guild_id, None)
        await self.cog.show_logs(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_home(interaction, self.owner_id)


class ModerationView(OwnedView):
    @discord.ui.button(label="Log beállítások", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def logs(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_logs(interaction, self.owner_id)

    @discord.ui.button(label="AutoMod", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
    async def automod(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_automod(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_home(interaction, self.owner_id)


class SetupPresetSelect(discord.ui.Select):
    def __init__(self, view: "SetupView") -> None:
        self.parent_view = view
        super().__init__(
            placeholder="1. Válassz AutoMod presetet…",
            options=[
                discord.SelectOption(label="Basic", value="basic", emoji="🟢", description="Enyhébb védelem."),
                discord.SelectOption(label="Recommended", value="recommended", emoji="🔵", description="Ajánlott általános beállítás."),
                discord.SelectOption(label="Strict", value="strict", emoji="🔴", description="Szigorúbb aktív szerverekhez."),
            ],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.settings.apply_preset(interaction.guild_id, self.values[0])
        self.parent_view.preset = self.values[0]
        await self.parent_view.cog.show_setup(interaction, self.parent_view.owner_id, self.parent_view)


class SetupLogChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "SetupView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="log_channel_page",
            selection_key="log",
            placeholder="2. Válassz modlog csatornát…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=1,
            max_values=1,
        )


class SetupPartnerSelect(PagedGuildChannelSelect):
    def __init__(self, view: "SetupView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="partner_channel_page",
            selection_key="partner",
            placeholder="3. Partner/reklám csatornák (opcionális)…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=2,
            max_values=5,
        )


class SetupTicketCategorySelect(PagedGuildChannelSelect):
    def __init__(self, view: "SetupView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="ticket_category_page",
            selection_key="ticket",
            placeholder="4. Ticket kategóriák (opcionális)…",
            channel_types=(discord.ChannelType.category,),
            row=3,
            max_values=5,
        )


class SetupStaffRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "SetupView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="staff_role_page",
            selection_key="setup_staff",
            placeholder="5. Staff rangok (opcionális)…",
            row=4,
            max_values=5,
        )


class SetupView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        preset: str | None = None,
        log_channel_id: int | None = None,
        partner_count: int = 0,
        ticket_count: int = 0,
        staff_count: int = 0,
        log_channel_page: int = 0,
        partner_channel_page: int = 0,
        ticket_category_page: int = 0,
        staff_role_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.preset = preset
        self.log_channel_id = log_channel_id
        self.partner_count = partner_count
        self.ticket_count = ticket_count
        self.staff_count = staff_count
        self.log_channel_page = log_channel_page
        self.partner_channel_page = partner_channel_page
        self.ticket_category_page = ticket_category_page
        self.staff_role_page = staff_role_page
        self.add_item(SetupPresetSelect(self))
        self.add_item(SetupLogChannelSelect(self))
        self.add_item(SetupPartnerSelect(self))
        self.add_item(SetupTicketCategorySelect(self))
        self.add_item(SetupStaffRoleSelect(self))

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if selection_key == "log":
            channel = channels[0]
            await self.cog.settings.set_log_channel_id(interaction.guild_id, channel.id)
            self.log_channel_id = channel.id
        elif selection_key == "partner":
            for channel in channels:
                await self.cog.settings.add_exemption(interaction.guild_id, "invite", "channel", channel.id)
            self.partner_count += len(channels)
        elif selection_key == "ticket":
            for category in channels:
                await self.cog.settings.add_exemption(interaction.guild_id, "invite", "category", category.id)
                await self.cog.settings.add_exemption(interaction.guild_id, "links", "category", category.id)
            self.ticket_count += len(channels)
        await self.cog.show_setup(interaction, self.owner_id, self)

    async def handle_role_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        roles: list[discord.Role],
    ) -> None:
        if selection_key == "setup_staff":
            for role in roles:
                await self.cog.settings.add_exemption(interaction.guild_id, "all", "role", role.id)
            self.staff_count += len(roles)
        await self.cog.show_setup(interaction, self.owner_id, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_setup(interaction, self.owner_id, self)


# -------------------- Yoru v3.7 Welcome UI --------------------

class WelcomeChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "WelcomeView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="welcome",
            placeholder="Welcome csatorna kiválasztása…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=2,
            max_values=1,
        )


class WelcomeMessageModal(discord.ui.Modal, title="Welcome üzenet"):
    embed_title = discord.ui.TextInput(label="Embed cím", required=False, max_length=256)
    message = discord.ui.TextInput(
        label="Üzenet / első sablon",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        placeholder="Szia {user}! Üdv a {server} szerveren!",
    )

    def __init__(self, view: "WelcomeView", current_title: str, current_message: str) -> None:
        super().__init__()
        self.parent_view = view
        self.embed_title.default = current_title
        self.message.default = current_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.settings.set_welcome_title(interaction.guild_id, str(self.embed_title.value))
        templates = await self.parent_view.cog.settings.get_welcome_templates(interaction.guild_id)
        templates[0] = str(self.message.value).strip()
        await self.parent_view.cog.settings.set_welcome_templates(interaction.guild_id, templates)
        await self.parent_view.cog.show_welcome(interaction, self.parent_view.owner_id)


class WelcomeDMModal(discord.ui.Modal, title="Welcome DM"):
    message = discord.ui.TextInput(
        label="Privát üdvözlő üzenet",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        placeholder="Szia {username}! Üdv a {server} szerveren!",
    )

    def __init__(self, view: "WelcomeView", current: str) -> None:
        super().__init__()
        self.parent_view = view
        self.message.default = current

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.settings.set_welcome_dm_template(interaction.guild_id, str(self.message.value))
        await self.parent_view.cog.show_welcome(interaction, self.parent_view.owner_id)


class WelcomeVariantModal(discord.ui.Modal, title="Új random welcome sablon"):
    message = discord.ui.TextInput(
        label="Új sablon",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        placeholder="Megérkezett {user}! 🌙",
    )

    def __init__(self, view: "WelcomeVariantsView") -> None:
        super().__init__()
        self.parent_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        templates = await self.parent_view.cog.settings.get_welcome_templates(interaction.guild_id)
        if len(templates) >= 10:
            return await interaction.response.send_message("❌ Maximum 10 welcome sablon lehet.", ephemeral=True)
        templates.append(str(self.message.value).strip())
        await self.parent_view.cog.settings.set_welcome_templates(interaction.guild_id, templates)
        await self.parent_view.cog.show_welcome_variants(interaction, self.parent_view.owner_id)


class WelcomeVariantsView(OwnedView):
    @discord.ui.button(label="Sablon hozzáadása", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(WelcomeVariantModal(self))

    @discord.ui.button(label="Alap sablonok", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def defaults(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_welcome_templates(interaction.guild_id, list(membercfg.WELCOME_DEFAULT_TEMPLATES))
        await self.cog.show_welcome_variants(interaction, self.owner_id)

    @discord.ui.button(label="Csak első sablon", emoji="🧹", style=discord.ButtonStyle.danger, row=0)
    async def clear_extra(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        templates = await self.cog.settings.get_welcome_templates(interaction.guild_id)
        await self.cog.settings.set_welcome_templates(interaction.guild_id, templates[:1])
        await self.cog.show_welcome_variants(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_welcome(interaction, self.owner_id)


class WelcomeView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        enabled: bool,
        embed_enabled: bool,
        random_enabled: bool,
        dm_enabled: bool,
        channel_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.enabled = enabled
        self.embed_enabled = embed_enabled
        self.random_enabled = random_enabled
        self.dm_enabled = dm_enabled
        self.channel_page = channel_page
        self.add_item(WelcomeChannelSelect(self))
        self.toggle.label = "Welcome: ON" if enabled else "Welcome: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        self.embed_toggle.label = "Embed: ON" if embed_enabled else "Embed: OFF"
        self.random_toggle.label = "Random: ON" if random_enabled else "Random: OFF"
        self.dm_toggle.label = "DM: ON" if dm_enabled else "DM: OFF"

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if selection_key == "welcome" and channels:
            await self.cog.settings.set_welcome_channel_id(interaction.guild_id, channels[0].id)
        await self.cog.show_welcome(interaction, self.owner_id, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_welcome(interaction, self.owner_id, self)

    @discord.ui.button(label="Welcome", emoji="👋", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_welcome_enabled(interaction.guild_id, not self.enabled)
        await self.cog.show_welcome(interaction, self.owner_id)

    @discord.ui.button(label="Embed", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def embed_toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_welcome_embed(interaction.guild_id, not self.embed_enabled)
        await self.cog.show_welcome(interaction, self.owner_id)

    @discord.ui.button(label="Random", emoji="🎲", style=discord.ButtonStyle.secondary, row=0)
    async def random_toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_welcome_random(interaction.guild_id, not self.random_enabled)
        await self.cog.show_welcome(interaction, self.owner_id)

    @discord.ui.button(label="DM", emoji="✉️", style=discord.ButtonStyle.secondary, row=0)
    async def dm_toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_welcome_dm_enabled(interaction.guild_id, not self.dm_enabled)
        await self.cog.show_welcome(interaction, self.owner_id)

    @discord.ui.button(label="Üzenet", emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def message(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        title = await self.cog.settings.get_welcome_title(interaction.guild_id)
        templates = await self.cog.settings.get_welcome_templates(interaction.guild_id)
        await interaction.response.send_modal(WelcomeMessageModal(self, title, templates[0]))

    @discord.ui.button(label="Sablonok", emoji="🗂️", style=discord.ButtonStyle.secondary, row=1)
    async def templates(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_welcome_variants(interaction, self.owner_id)

    @discord.ui.button(label="DM szöveg", emoji="📝", style=discord.ButtonStyle.secondary, row=1)
    async def dm_message(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        current = await self.cog.settings.get_welcome_dm_template(interaction.guild_id)
        await interaction.response.send_modal(WelcomeDMModal(self, current))

    @discord.ui.button(label="Teszt", emoji="🧪", style=discord.ButtonStyle.success, row=1)
    async def test(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.send_welcome_preview(interaction)

    @discord.ui.button(label="Goodbye", emoji="👋", style=discord.ButtonStyle.secondary, row=3)
    async def goodbye(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_goodbye(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_home(interaction, self.owner_id)


class GoodbyeChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "GoodbyeView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="goodbye",
            placeholder="Goodbye csatorna kiválasztása…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=2,
            max_values=1,
        )


class GoodbyeMessageModal(discord.ui.Modal, title="Goodbye üzenet"):
    embed_title = discord.ui.TextInput(label="Embed cím", required=False, max_length=256)
    message = discord.ui.TextInput(label="Üzenet", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, view: "GoodbyeView", current_title: str, current_message: str) -> None:
        super().__init__()
        self.parent_view = view
        self.embed_title.default = current_title
        self.message.default = current_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.parent_view.cog.settings.set_goodbye_title(interaction.guild_id, str(self.embed_title.value))
        await self.parent_view.cog.settings.set_goodbye_template(interaction.guild_id, str(self.message.value))
        await self.parent_view.cog.show_goodbye(interaction, self.parent_view.owner_id)


class GoodbyeView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        enabled: bool,
        embed_enabled: bool,
        channel_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.enabled = enabled
        self.embed_enabled = embed_enabled
        self.channel_page = channel_page
        self.add_item(GoodbyeChannelSelect(self))
        self.toggle.label = "Goodbye: ON" if enabled else "Goodbye: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        self.embed_toggle.label = "Embed: ON" if embed_enabled else "Embed: OFF"

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if selection_key == "goodbye" and channels:
            await self.cog.settings.set_goodbye_channel_id(interaction.guild_id, channels[0].id)
        await self.cog.show_goodbye(interaction, self.owner_id, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_goodbye(interaction, self.owner_id, self)

    @discord.ui.button(label="Goodbye", emoji="👋", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_goodbye_enabled(interaction.guild_id, not self.enabled)
        await self.cog.show_goodbye(interaction, self.owner_id)

    @discord.ui.button(label="Embed", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def embed_toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_goodbye_embed(interaction.guild_id, not self.embed_enabled)
        await self.cog.show_goodbye(interaction, self.owner_id)

    @discord.ui.button(label="Üzenet", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def message(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        title = await self.cog.settings.get_goodbye_title(interaction.guild_id)
        text = await self.cog.settings.get_goodbye_template(interaction.guild_id)
        await interaction.response.send_modal(GoodbyeMessageModal(self, title, text))

    @discord.ui.button(label="Teszt", emoji="🧪", style=discord.ButtonStyle.success, row=0)
    async def test(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.send_goodbye_preview(interaction)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_welcome(interaction, self.owner_id)


# -------------------- Yoru v3.7 Roles UI --------------------

class AutoroleHumanSelect(PagedGuildRoleSelect):
    def __init__(self, view: "AutorolesView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="human_role_page",
            selection_key="autorole_human",
            placeholder="Emberi autorole hozzáadása (max 10)…",
            row=0,
            max_values=10,
        )


class AutoroleBotSelect(PagedGuildRoleSelect):
    def __init__(self, view: "AutorolesView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="bot_role_page",
            selection_key="autorole_bot",
            placeholder="Bot autorole hozzáadása (max 10)…",
            row=1,
            max_values=10,
        )


class AutorolesView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        human_role_page: int = 0,
        bot_role_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.human_role_page = human_role_page
        self.bot_role_page = bot_role_page
        self.add_item(AutoroleHumanSelect(self))
        self.add_item(AutoroleBotSelect(self))

    async def handle_role_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        roles: list[discord.Role],
    ) -> None:
        valid, skipped = self.cog.validate_config_roles(interaction.guild, roles)
        if selection_key == "autorole_human":
            existing = await self.cog.settings.get_human_autoroles(interaction.guild_id)
            merged = list(dict.fromkeys([*existing, *[r.id for r in valid]]))[:membercfg.AUTOROLE_MAX_ROLES]
            await self.cog.settings.set_human_autoroles(interaction.guild_id, merged)
        elif selection_key == "autorole_bot":
            existing = await self.cog.settings.get_bot_autoroles(interaction.guild_id)
            merged = list(dict.fromkeys([*existing, *[r.id for r in valid]]))[:membercfg.AUTOROLE_MAX_ROLES]
            await self.cog.settings.set_bot_autoroles(interaction.guild_id, merged)
        await self.cog.show_autoroles(interaction, self.owner_id, self)
        if skipped:
            await interaction.followup.send(
                "⚠️ Néhány rang kimaradt, mert Yoru nem kezelheti őket: " + ", ".join(skipped[:8]),
                ephemeral=True,
            )

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_autoroles(interaction, self.owner_id, self)

    @discord.ui.button(label="Emberi autorole törlése", emoji="🧹", style=discord.ButtonStyle.danger, row=2)
    async def clear_human(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_human_autoroles(interaction.guild_id, [])
        await self.cog.show_autoroles(interaction, self.owner_id)

    @discord.ui.button(label="Bot autorole törlése", emoji="🧹", style=discord.ButtonStyle.danger, row=2)
    async def clear_bot(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_bot_autoroles(interaction.guild_id, [])
        await self.cog.show_autoroles(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_roles(interaction, self.owner_id)


class RolePanelChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "RolePanelBuilderView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="role_panel",
            placeholder="1. Hova kerüljön a self-role panel?",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=0,
            max_values=1,
        )


class RolePanelRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "RolePanelBuilderView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="role_page",
            selection_key="role_panel_roles",
            placeholder="2. Kiosztható rangok hozzáadása (max 10)…",
            row=1,
            max_values=10,
        )


class RolePanelModeSelect(discord.ui.Select):
    def __init__(self, view: "RolePanelBuilderView") -> None:
        self.parent_view = view
        super().__init__(
            placeholder="3. Panel mód…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Több rang választható", value="toggle", emoji="🎛️", description="Minden gomb külön ki/be kapcsol egy rangot."),
                discord.SelectOption(label="Egyetlen választás", value="single", emoji="1️⃣", description="Új választás leveszi a panel többi rangját."),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.mode = self.values[0]
        await self.parent_view.cog.show_role_builder(interaction, self.parent_view.owner_id, self.parent_view)


class RolePanelTextModal(discord.ui.Modal, title="Self-role panel szöveg"):
    panel_title = discord.ui.TextInput(label="Cím", max_length=256)
    body = discord.ui.TextInput(label="Leírás", style=discord.TextStyle.paragraph, max_length=2000, required=False)

    def __init__(self, view: "RolePanelBuilderView") -> None:
        super().__init__()
        self.parent_view = view
        self.panel_title.default = view.title
        self.body.default = view.description

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.parent_view.title = str(self.panel_title.value).strip() or "🎭 Válassz rangot"
        self.parent_view.description = str(self.body.value).strip()
        await self.parent_view.cog.show_role_builder(interaction, self.parent_view.owner_id, self.parent_view)


class RolePanelBuilderView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        channel_id: int | None = None,
        role_ids: list[int] | None = None,
        mode: str = "toggle",
        title: str = "🎭 Válassz rangot",
        description: str = "Az alábbi gombokkal kezelheted a saját rangjaidat.",
        channel_page: int = 0,
        role_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.channel_id = channel_id
        self.role_ids = list(role_ids or [])
        self.mode = mode
        self.title = title
        self.description = description
        self.channel_page = channel_page
        self.role_page = role_page
        self.add_item(RolePanelChannelSelect(self))
        self.add_item(RolePanelRoleSelect(self))
        self.add_item(RolePanelModeSelect(self))

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if selection_key == "role_panel" and channels:
            self.channel_id = channels[0].id
        await self.cog.show_role_builder(interaction, self.owner_id, self)

    async def handle_role_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        roles: list[discord.Role],
    ) -> None:
        skipped: list[str] = []
        if selection_key == "role_panel_roles":
            valid, skipped = self.cog.validate_config_roles(interaction.guild, roles)
            self.role_ids = list(dict.fromkeys([*self.role_ids, *[r.id for r in valid]]))[:membercfg.SELF_ROLE_PANEL_MAX_ROLES]
        await self.cog.show_role_builder(interaction, self.owner_id, self)
        if skipped:
            await interaction.followup.send(
                "⚠️ Ezeket Yoru nem tudja kiosztani: " + ", ".join(skipped[:8]),
                ephemeral=True,
            )

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_role_builder(interaction, self.owner_id, self)

    @discord.ui.button(label="Szöveg", emoji="✏️", style=discord.ButtonStyle.secondary, row=3)
    async def text(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RolePanelTextModal(self))

    @discord.ui.button(label="Rangok törlése", emoji="🧹", style=discord.ButtonStyle.secondary, row=3)
    async def clear_roles(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.role_ids = []
        await self.cog.show_role_builder(interaction, self.owner_id, self)

    @discord.ui.button(label="Panel létrehozása", emoji="🚀", style=discord.ButtonStyle.success, row=3)
    async def create(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None or self.channel_id is None or not self.role_ids:
            return await interaction.response.send_message("❌ Válassz csatornát és legalább egy rangot.", ephemeral=True)
        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ A kiválasztott csatorna már nem elérhető.", ephemeral=True)
        roles = [r for rid in self.role_ids if (r := interaction.guild.get_role(rid)) is not None]
        runtime = self.cog.bot.get_cog("WelcomeRolesCog")
        if runtime is None:
            return await interaction.response.send_message("❌ A Welcome/Roles modul nincs betöltve.", ephemeral=True)
        try:
            panel_id = await runtime.post_role_panel(
                interaction.guild, channel, interaction.user.id, roles, self.title, self.description, self.mode
            )
        except (ValueError, discord.Forbidden, discord.HTTPException) as exc:
            return await interaction.response.send_message(f"❌ Nem sikerült létrehozni a panelt: {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ Self-role panel létrehozva: **#{panel_id}** • {channel.mention}", ephemeral=True)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_roles(interaction, self.owner_id)


class RolePanelManagerSelect(discord.ui.Select):
    def __init__(self, view: "RolePanelManagerView", panels: list[dict]) -> None:
        self.parent_view = view
        options = []
        for panel in panels[:25]:
            options.append(discord.SelectOption(
                label=f"#{panel['panel_id']} • {panel['title'][:70]}",
                value=str(panel["panel_id"]),
                description=f"{len(panel['items'])} rang • {'single' if panel['mode']=='single' else 'multi'}",
            ))
        super().__init__(placeholder="Aktív panel kiválasztása…", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_panel_id = int(self.values[0])
        await self.parent_view.cog.show_role_panels(interaction, self.parent_view.owner_id, self.parent_view.selected_panel_id)


class RolePanelManagerView(OwnedView):
    def __init__(self, cog: "SettingsCog", owner_id: int, panels: list[dict], selected_panel_id: int | None = None) -> None:
        super().__init__(cog, owner_id)
        self.panels = panels
        self.selected_panel_id = selected_panel_id
        if panels:
            self.add_item(RolePanelManagerSelect(self, panels))

    @discord.ui.button(label="Panel deaktiválása", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def deactivate(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if self.selected_panel_id is None:
            return await interaction.response.send_message("❌ Előbb válassz ki egy panelt.", ephemeral=True)
        runtime = self.cog.bot.get_cog("WelcomeRolesCog")
        if runtime is None or interaction.guild is None:
            return await interaction.response.send_message("❌ A Roles modul nem elérhető.", ephemeral=True)
        await runtime.deactivate_role_panel(interaction.guild, self.selected_panel_id, delete_message=True)
        await self.cog.show_role_panels(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_roles(interaction, self.owner_id)


class VerificationChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "VerificationSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="channel_page",
            selection_key="verification",
            placeholder="1. Ellenőrzőpanel csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=0,
            max_values=1,
        )


class VerificationGiveRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "VerificationSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="give_role_page",
            selection_key="verification_give",
            placeholder="2. Elfogadáskor kiosztott rang…",
            row=1,
            max_values=1,
        )


class VerificationRemoveRoleSelect(PagedGuildRoleSelect):
    def __init__(self, view: "VerificationSettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="remove_role_page",
            selection_key="verification_remove",
            placeholder="3. Opcionális: eltávolítandó rang…",
            row=2,
            max_values=1,
        )


class VerificationTextModal(discord.ui.Modal, title="Verification panel"):
    panel_title = discord.ui.TextInput(label="Cím", max_length=256)
    body = discord.ui.TextInput(label="Leírás", style=discord.TextStyle.paragraph, max_length=2000)
    button_label = discord.ui.TextInput(label="Gomb felirata", max_length=80)

    def __init__(self, view: "VerificationSettingsView") -> None:
        super().__init__()
        self.parent_view = view
        self.panel_title.default = view.title
        self.body.default = view.body
        self.button_label.default = view.button_label

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.parent_view.title = str(self.panel_title.value).strip() or membercfg.VERIFICATION_DEFAULT_TITLE
        self.parent_view.body = str(self.body.value).strip() or membercfg.VERIFICATION_DEFAULT_BODY
        self.parent_view.button_label = str(self.button_label.value).strip() or membercfg.VERIFICATION_DEFAULT_BUTTON
        await self.parent_view.cog.show_verification(interaction, self.parent_view.owner_id, self.parent_view)


class VerificationSettingsView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        *,
        channel_id: int | None = None,
        role_id: int | None = None,
        remove_role_id: int | None = None,
        title: str = membercfg.VERIFICATION_DEFAULT_TITLE,
        body: str = membercfg.VERIFICATION_DEFAULT_BODY,
        button_label: str = membercfg.VERIFICATION_DEFAULT_BUTTON,
        channel_page: int = 0,
        give_role_page: int = 0,
        remove_role_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.channel_id = channel_id
        self.role_id = role_id
        self.remove_role_id = remove_role_id
        self.title = title
        self.body = body
        self.button_label = button_label
        self.channel_page = channel_page
        self.give_role_page = give_role_page
        self.remove_role_page = remove_role_page
        self.add_item(VerificationChannelSelect(self))
        self.add_item(VerificationGiveRoleSelect(self))
        self.add_item(VerificationRemoveRoleSelect(self))

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if selection_key == "verification" and channels:
            self.channel_id = channels[0].id
        await self.cog.show_verification(interaction, self.owner_id, self)

    async def handle_role_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        roles: list[discord.Role],
    ) -> None:
        valid, _skipped = self.cog.validate_config_roles(interaction.guild, roles)
        if not valid:
            return await interaction.response.send_message("❌ Ezt a rangot Yoru nem tudja kezelni.", ephemeral=True)
        if selection_key == "verification_give":
            self.role_id = valid[0].id
        elif selection_key == "verification_remove":
            self.remove_role_id = valid[0].id
        await self.cog.show_verification(interaction, self.owner_id, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_verification(interaction, self.owner_id, self)

    @discord.ui.button(label="Szöveg", emoji="✏️", style=discord.ButtonStyle.secondary, row=3)
    async def text(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(VerificationTextModal(self))

    @discord.ui.button(label="Eltávolítandó rang törlése", emoji="🧹", style=discord.ButtonStyle.secondary, row=3)
    async def clear_remove(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.remove_role_id = None
        await self.cog.show_verification(interaction, self.owner_id, self)

    @discord.ui.button(label="Panel kiküldése", emoji="🚀", style=discord.ButtonStyle.success, row=3)
    async def post(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None or self.channel_id is None or self.role_id is None:
            return await interaction.response.send_message("❌ Csatorna és kiosztandó rang szükséges.", ephemeral=True)
        channel = interaction.guild.get_channel(self.channel_id)
        role = interaction.guild.get_role(self.role_id)
        remove_role = interaction.guild.get_role(self.remove_role_id) if self.remove_role_id else None
        if not isinstance(channel, discord.TextChannel) or role is None:
            return await interaction.response.send_message("❌ A kiválasztott csatorna/rang már nem létezik.", ephemeral=True)
        runtime = self.cog.bot.get_cog("WelcomeRolesCog")
        if runtime is None:
            return await interaction.response.send_message("❌ A Roles modul nincs betöltve.", ephemeral=True)
        try:
            await runtime.post_verification_panel(interaction.guild, channel, role, remove_role, self.title, self.body, self.button_label)
        except (ValueError, discord.Forbidden, discord.HTTPException) as exc:
            return await interaction.response.send_message(f"❌ Nem sikerült kiküldeni: {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ Verification panel kiküldve ide: {channel.mention}", ephemeral=True)

    @discord.ui.button(label="Aktív panel letiltása", emoji="🛑", style=discord.ButtonStyle.danger, row=4)
    async def disable(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        runtime = self.cog.bot.get_cog("WelcomeRolesCog")
        if runtime is None or interaction.guild is None:
            return await interaction.response.send_message("❌ A Roles modul nem elérhető.", ephemeral=True)
        changed = await runtime.deactivate_verification_panel(interaction.guild, delete_message=True)
        if not changed:
            return await interaction.response.send_message("ℹ️ Nincs aktív verification panel.", ephemeral=True)
        await self.cog.show_verification(interaction, self.owner_id, self)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_roles(interaction, self.owner_id)


class RolesView(OwnedView):
    def __init__(self, cog: "SettingsCog", owner_id: int, restore_enabled: bool) -> None:
        super().__init__(cog, owner_id)
        self.restore_enabled = restore_enabled
        self.restore.label = "Role restore: ON" if restore_enabled else "Role restore: OFF"
        self.restore.style = discord.ButtonStyle.success if restore_enabled else discord.ButtonStyle.secondary

    @discord.ui.button(label="Autoroles", emoji="🤖", style=discord.ButtonStyle.primary, row=0)
    async def autoroles(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_autoroles(interaction, self.owner_id)

    @discord.ui.button(label="Role restore", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def restore(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.settings.set_role_restore_enabled(interaction.guild_id, not self.restore_enabled)
        await self.cog.show_roles(interaction, self.owner_id)

    @discord.ui.button(label="Self-role panel", emoji="🎛️", style=discord.ButtonStyle.secondary, row=0)
    async def selfroles(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_role_builder(interaction, self.owner_id)

    @discord.ui.button(label="Verification", emoji="✅", style=discord.ButtonStyle.secondary, row=0)
    async def verification(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_verification(interaction, self.owner_id)

    @discord.ui.button(label="Panelek kezelése", emoji="🗂️", style=discord.ButtonStyle.secondary, row=1)
    async def manage(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_role_panels(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_home(interaction, self.owner_id)



class CommunitySuggestionChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "CommunitySettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="suggestion_channel_page",
            selection_key="suggestions",
            placeholder="Suggestion csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=2,
            max_values=1,
        )


class CommunityStarboardChannelSelect(PagedGuildChannelSelect):
    def __init__(self, view: "CommunitySettingsView") -> None:
        super().__init__(
            view,
            view.guild,
            page_attr="starboard_channel_page",
            selection_key="starboard",
            placeholder="Starboard csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=3,
            max_values=1,
        )


class CommunityTuneModal(discord.ui.Modal, title="Community finomhangolás"):
    starboard_threshold = discord.ui.TextInput(
        label="Starboard küszöb",
        required=True,
        max_length=2,
        placeholder="3",
    )
    poll_minutes = discord.ui.TextInput(
        label="Poll alap idő (perc)",
        required=True,
        max_length=6,
        placeholder="60",
    )
    giveaway_minutes = discord.ui.TextInput(
        label="Giveaway alap idő (perc)",
        required=True,
        max_length=7,
        placeholder="60",
    )
    sticky_every = discord.ui.TextInput(
        label="Sticky újraküldés ennyi üzenetenként",
        required=True,
        max_length=3,
        placeholder="8",
    )

    def __init__(self, view: "CommunitySettingsView", values: dict[str, int]) -> None:
        super().__init__()
        self.parent_view = view
        self.starboard_threshold.default = str(values["starboard_threshold"])
        self.poll_minutes.default = str(values["poll_minutes"])
        self.giveaway_minutes.default = str(values["giveaway_minutes"])
        self.sticky_every.default = str(values["sticky_every"])

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            threshold = int(str(self.starboard_threshold.value))
            poll_minutes = int(str(self.poll_minutes.value))
            giveaway_minutes = int(str(self.giveaway_minutes.value))
            sticky_every = int(str(self.sticky_every.value))
        except ValueError:
            return await interaction.response.send_message("❌ Minden mezőbe számot adj meg.", ephemeral=True)

        if not communitycfg.STARBOARD_MIN_THRESHOLD <= threshold <= communitycfg.STARBOARD_MAX_THRESHOLD:
            return await interaction.response.send_message(
                f"❌ Starboard küszöb: {communitycfg.STARBOARD_MIN_THRESHOLD}–{communitycfg.STARBOARD_MAX_THRESHOLD}.", ephemeral=True
            )
        if not communitycfg.POLLS_MIN_DURATION_MINUTES <= poll_minutes <= communitycfg.POLLS_MAX_DURATION_MINUTES:
            return await interaction.response.send_message("❌ Érvénytelen Poll alap idő.", ephemeral=True)
        if not communitycfg.GIVEAWAYS_MIN_DURATION_MINUTES <= giveaway_minutes <= communitycfg.GIVEAWAYS_MAX_DURATION_MINUTES:
            return await interaction.response.send_message("❌ Érvénytelen Giveaway alap idő.", ephemeral=True)
        if not communitycfg.STICKY_MIN_EVERY_MESSAGES <= sticky_every <= communitycfg.STICKY_MAX_EVERY_MESSAGES:
            return await interaction.response.send_message(
                f"❌ Sticky üzenetszám: {communitycfg.STICKY_MIN_EVERY_MESSAGES}–{communitycfg.STICKY_MAX_EVERY_MESSAGES}.", ephemeral=True
            )

        settings = self.parent_view.cog.settings
        gid = interaction.guild_id
        await settings.set_starboard_threshold(gid, threshold)
        await settings.set_poll_default_duration_minutes(gid, poll_minutes)
        await settings.set_giveaway_default_duration_minutes(gid, giveaway_minutes)
        await settings.set_sticky_every_messages(gid, sticky_every)
        await self.parent_view.cog.show_community(interaction, self.parent_view.owner_id, self.parent_view)


class CommunitySettingsView(OwnedView):
    def __init__(
        self,
        cog: "SettingsCog",
        owner_id: int,
        guild: discord.Guild,
        states: dict[str, bool],
        *,
        suggestion_channel_page: int = 0,
        starboard_channel_page: int = 0,
    ) -> None:
        super().__init__(cog, owner_id)
        self.guild = guild
        self.states = states
        self.suggestion_channel_page = suggestion_channel_page
        self.starboard_channel_page = starboard_channel_page
        self._style_toggle(self.suggestions, states["suggestions"], "Suggestions")
        self._style_toggle(self.polls, states["polls"], "Polls")
        self._style_toggle(self.giveaways, states["giveaways"], "Giveaways")
        self._style_toggle(self.starboard, states["starboard"], "Starboard")
        self._style_toggle(self.afk, states["afk"], "AFK")
        self._style_toggle(self.sticky, states["sticky"], "Sticky")
        self._style_toggle(self.anonymous, states["anonymous"], "Anonymous")
        self._style_toggle(self.poll_staff, states["poll_staff"], "Poll staff-only")
        self.add_item(CommunitySuggestionChannelSelect(self))
        self.add_item(CommunityStarboardChannelSelect(self))

    @staticmethod
    def _style_toggle(button: discord.ui.Button, enabled: bool, name: str) -> None:
        button.label = f"{name}: {'ON' if enabled else 'OFF'}"
        button.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary

    async def _toggle(self, interaction: discord.Interaction, key: str) -> None:
        current = self.states[key]
        service = self.cog.settings
        setters = {
            "suggestions": service.set_suggestions_enabled,
            "polls": service.set_polls_enabled,
            "giveaways": service.set_giveaways_enabled,
            "starboard": service.set_starboard_enabled,
            "afk": service.set_afk_enabled,
            "sticky": service.set_sticky_enabled,
            "anonymous": service.set_suggestions_anonymous,
            "poll_staff": service.set_polls_staff_only,
        }
        await setters[key](interaction.guild_id, not current)
        await self.cog.show_community(interaction, self.owner_id, self)

    async def handle_channel_selection(
        self,
        interaction: discord.Interaction,
        selection_key: str,
        channels: list[discord.abc.GuildChannel],
    ) -> None:
        if not channels:
            return
        channel = channels[0]
        if selection_key == "suggestions":
            await self.cog.settings.set_suggestion_channel_id(interaction.guild_id, channel.id)
        elif selection_key == "starboard":
            await self.cog.settings.set_starboard_channel_id(interaction.guild_id, channel.id)
        await self.cog.show_community(interaction, self.owner_id, self)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_community(interaction, self.owner_id, self)

    @discord.ui.button(label="Suggestions", emoji="💡", style=discord.ButtonStyle.secondary, row=0)
    async def suggestions(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "suggestions")

    @discord.ui.button(label="Polls", emoji="📊", style=discord.ButtonStyle.secondary, row=0)
    async def polls(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "polls")

    @discord.ui.button(label="Giveaways", emoji="🎉", style=discord.ButtonStyle.secondary, row=0)
    async def giveaways(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "giveaways")

    @discord.ui.button(label="Starboard", emoji="⭐", style=discord.ButtonStyle.secondary, row=0)
    async def starboard(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "starboard")

    @discord.ui.button(label="AFK", emoji="💤", style=discord.ButtonStyle.secondary, row=0)
    async def afk(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "afk")

    @discord.ui.button(label="Sticky", emoji="📌", style=discord.ButtonStyle.secondary, row=1)
    async def sticky(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "sticky")

    @discord.ui.button(label="Anonymous", emoji="🕵️", style=discord.ButtonStyle.secondary, row=1)
    async def anonymous(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "anonymous")

    @discord.ui.button(label="Poll staff-only", emoji="🛡️", style=discord.ButtonStyle.secondary, row=1)
    async def poll_staff(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._toggle(interaction, "poll_staff")

    @discord.ui.button(label="Finomhangolás", emoji="🎚️", style=discord.ButtonStyle.primary, row=1)
    async def tune(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        values = {
            "starboard_threshold": await self.cog.settings.get_starboard_threshold(interaction.guild_id),
            "poll_minutes": await self.cog.settings.get_poll_default_duration_minutes(interaction.guild_id),
            "giveaway_minutes": await self.cog.settings.get_giveaway_default_duration_minutes(interaction.guild_id),
            "sticky_every": await self.cog.settings.get_sticky_every_messages(interaction.guild_id),
        }
        await interaction.response.send_modal(CommunityTuneModal(self, values))

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.show_home(interaction, self.owner_id)


class SettingsCog(commands.Cog):
    """Interactive per-guild configuration UI. Backend is dashboard-ready."""

    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.settings = ServerSettingsService(db)

    async def home_embed(self, guild: discord.Guild) -> discord.Embed:
        automod = await self.settings.get_automod_enabled(guild.id)
        log_id = await self.settings.get_log_channel_id(guild.id)
        log_channel = guild.get_channel(log_id) if log_id else None
        welcome_enabled = await self.settings.get_welcome_enabled(guild.id)
        human_roles = await self.settings.get_human_autoroles(guild.id)
        bot_roles = await self.settings.get_bot_autoroles(guild.id)
        role_panels = await self.db.list_role_panels(guild.id, active_only=True)
        community_enabled = sum([
            await self.settings.get_suggestions_enabled(guild.id),
            await self.settings.get_polls_enabled(guild.id),
            await self.settings.get_giveaways_enabled(guild.id),
            await self.settings.get_starboard_enabled(guild.id),
            await self.settings.get_afk_enabled(guild.id),
            await self.settings.get_sticky_enabled(guild.id),
        ])
        embed = base_embed(
            "⚙️ Yoru • Szerver beállítások",
            "Innen lehet a Yoru szerverfunkcióit interaktívan konfigurálni. A beállítások szerverenként az adatbázisban maradnak meg.",
        )
        embed.add_field(name="🛡️ AutoMod", value="🟢 Bekapcsolva" if automod else "🔴 Kikapcsolva", inline=True)
        embed.add_field(name="📝 Moderációs log", value=log_channel.mention if isinstance(log_channel, discord.abc.GuildChannel) else "Nincs beállítva", inline=True)
        embed.add_field(name="📋 Moderáció", value="Aktív", inline=True)
        embed.add_field(name="👋 Welcome", value="🟢 Aktív" if welcome_enabled else "⚪ Kikapcsolva", inline=True)
        embed.add_field(name="🎭 Roles", value=f"{len(human_roles)} human • {len(bot_roles)} bot autorole • {len(role_panels)} panel", inline=True)
        embed.add_field(name="🌙 Community", value=f"{community_enabled}/6 modul aktív", inline=True)
        embed.add_field(name="🔜 Következő modulok", value="🎫 Tickets • 🎵 Music • 🎉 Fun", inline=True)
        embed.set_footer(text="Yoru • Settings • Csak Manage Server jogosultsággal")
        return embed

    async def community_embed(self, guild: discord.Guild) -> tuple[discord.Embed, dict[str, bool]]:
        states = {
            "suggestions": await self.settings.get_suggestions_enabled(guild.id),
            "polls": await self.settings.get_polls_enabled(guild.id),
            "giveaways": await self.settings.get_giveaways_enabled(guild.id),
            "starboard": await self.settings.get_starboard_enabled(guild.id),
            "afk": await self.settings.get_afk_enabled(guild.id),
            "sticky": await self.settings.get_sticky_enabled(guild.id),
            "anonymous": await self.settings.get_suggestions_anonymous(guild.id),
            "poll_staff": await self.settings.get_polls_staff_only(guild.id),
        }
        suggestion_id = await self.settings.get_suggestion_channel_id(guild.id)
        starboard_id = await self.settings.get_starboard_channel_id(guild.id)
        suggestion_channel = guild.get_channel(suggestion_id) if suggestion_id else None
        starboard_channel = guild.get_channel(starboard_id) if starboard_id else None
        threshold = await self.settings.get_starboard_threshold(guild.id)
        poll_minutes = await self.settings.get_poll_default_duration_minutes(guild.id)
        giveaway_minutes = await self.settings.get_giveaway_default_duration_minutes(guild.id)
        sticky_every = await self.settings.get_sticky_every_messages(guild.id)
        stickies = await self.db.list_community_stickies(guild.id, active_only=True)

        embed = base_embed(
            "🌙 Community Management",
            "Suggestions, Poll, Giveaway, Starboard, AFK és Sticky egy helyen. Minden kapcsoló és csatorna szerverenként mentődik.",
        )
        embed.add_field(
            name="💡 Suggestions",
            value=(
                f"{'✅ ON' if states['suggestions'] else '❌ OFF'} • "
                f"{suggestion_channel.mention if hasattr(suggestion_channel, 'mention') else 'nincs csatorna'} • "
                f"{'névtelen' if states['anonymous'] else 'névvel'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Polls",
            value=f"{'✅ ON' if states['polls'] else '❌ OFF'} • alap {poll_minutes} perc • {'csak staff' if states['poll_staff'] else 'mindenki'}",
            inline=True,
        )
        embed.add_field(
            name="🎉 Giveaways",
            value=f"{'✅ ON' if states['giveaways'] else '❌ OFF'} • alap {giveaway_minutes} perc",
            inline=True,
        )
        embed.add_field(
            name="⭐ Starboard",
            value=(
                f"{'✅ ON' if states['starboard'] else '❌ OFF'} • "
                f"{starboard_channel.mention if hasattr(starboard_channel, 'mention') else 'nincs csatorna'} • {threshold} ⭐"
            ),
            inline=True,
        )
        embed.add_field(name="💤 AFK", value="✅ ON" if states["afk"] else "❌ OFF", inline=True)
        embed.add_field(
            name="📌 Sticky",
            value=f"{'✅ ON' if states['sticky'] else '❌ OFF'} • {sticky_every} üzenetenként • {len(stickies)} aktív",
            inline=True,
        )
        embed.add_field(
            name="Parancsok",
            value="`/community suggest` • `/community poll` • `/community giveaway` • `/community afk` • `/community sticky`",
            inline=False,
        )
        embed.set_footer(text="Yoru • Community Settings • A csatornaválasztók lapozhatók nagy szervereken is")
        return embed, states

    async def automod_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.settings.get_automod_enabled(guild.id)
        lines = []
        for rule in RULE_ORDER:
            state = await self.settings.get_rule(guild.id, rule)
            extra = ""
            window = await self.settings.get_rule_window(guild.id, rule)
            if window is not None:
                extra = f" • {state.threshold}/{window:g}mp"
            elif rule not in {"invite", "links", "words"}:
                extra = f" • limit {state.threshold}"
            lines.append(
                f"{'✅' if state.enabled else '❌'} **{modcfg.AUTOMOD_RULE_LABELS[rule]}** — {ACTION_LABELS.get(state.action, state.action)}{extra}"
            )
        domains = await self.settings.list_domains(guild.id)
        words = await self.settings.list_words(guild.id)
        embed = base_embed("🛡️ AutoMod beállítások", "\n".join(lines), SUCCESS if enabled else DANGER)
        embed.add_field(name="⚡ Globális állapot", value="ON" if enabled else "OFF", inline=True)
        embed.add_field(name="🌐 Saját domain szabály", value=str(len(domains)), inline=True)
        embed.add_field(name="🚫 Tiltott szó/kifejezés", value=str(len(words)), inline=True)
        embed.set_footer(text="Yoru • Settings • Válassz szabályt a részletes konfigurációhoz")
        return embed

    async def rule_embed(self, guild: discord.Guild, rule: str) -> tuple[discord.Embed, dict]:
        state = await self.settings.get_rule(guild.id, rule)
        window = await self.settings.get_rule_window(guild.id, rule)
        rows = await self.settings.list_exemptions(guild.id, rule)
        own_rows = [row for row in rows if row[0] == rule]
        embed = base_embed(f"🛡️ {modcfg.AUTOMOD_RULE_LABELS[rule]}", color=SUCCESS if state.enabled else DANGER)
        embed.add_field(name="Állapot", value="✅ ON" if state.enabled else "❌ OFF", inline=True)
        embed.add_field(name="Művelet", value=ACTION_LABELS.get(state.action, state.action), inline=True)
        embed.add_field(name="Threshold", value=str(state.threshold), inline=True)
        if window is not None:
            embed.add_field(name="Időablak", value=f"{window:g} mp", inline=True)
        embed.add_field(name="Timeout", value=f"{max(1, state.timeout_seconds // 60)} perc", inline=True)
        embed.add_field(name="Saját kivételek", value=str(len(own_rows)), inline=True)
        if rule == "caps":
            embed.add_field(name="Megjegyzés", value=f"Legalább {modcfg.CAPS_MIN_LETTERS} betű után vizsgálja a CAPS arányt.", inline=False)
        embed.set_footer(text="Yoru • Settings • A globális 'all' kivételek is érvényesek")
        return embed, {
            "enabled": state.enabled,
            "action": state.action,
            "threshold": state.threshold,
            "timeout_seconds": state.timeout_seconds,
            "window_seconds": window,
        }

    async def exemptions_embed(self, guild: discord.Guild, rule: str, remove_mode: bool) -> discord.Embed:
        rows = await self.settings.list_exemptions(guild.id, None if rule == "all" else rule)
        rows = [r for r in rows if r[0] == rule] if rule == "all" else rows
        channels, categories, roles = [], [], []
        for stored_rule, scope_type, scope_id in rows:
            suffix = " *(globális)*" if stored_rule == "all" and rule != "all" else ""
            if scope_type == "role":
                obj = guild.get_role(scope_id)
                roles.append((obj.mention if obj else f"`{scope_id}`") + suffix)
            else:
                obj = guild.get_channel(scope_id)
                text = (obj.mention if hasattr(obj, "mention") else f"`{scope_id}`") + suffix
                (categories if scope_type == "category" else channels).append(text)
        label = "Minden AutoMod szabály" if rule == "all" else modcfg.AUTOMOD_RULE_LABELS[rule]
        embed = base_embed(f"🎯 Kivételek • {label}", f"Aktuális mód: **{'TÖRLÉS' if remove_mode else 'HOZZÁADÁS'}**")
        embed.add_field(name="💬 Csatornák", value="\n".join(channels[:15]) or "—", inline=False)
        embed.add_field(name="📁 Kategóriák", value="\n".join(categories[:15]) or "—", inline=False)
        embed.add_field(name="🎭 Rangok", value="\n".join(roles[:15]) or "—", inline=False)
        embed.set_footer(text="Yoru • Settings • A mód gombbal válthatsz hozzáadás és törlés között")
        return embed

    async def domains_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = await self.settings.list_domains(guild.id)
        allowed = [domain for mode, domain in rows if mode == "allow"]
        blocked = [domain for mode, domain in rows if mode == "block"]
        embed = base_embed("🌐 AutoMod domain szabályok")
        embed.add_field(name="✅ Allowlist", value="\n".join(f"`{x}`" for x in allowed[:20]) or "—", inline=False)
        embed.add_field(name="⛔ Blocklist", value="\n".join(f"`{x}`" for x in blocked[:20]) or "—", inline=False)
        embed.add_field(name="ℹ️ Prioritás", value="A blocklist erősebb a normál csatorna/rang kivételeknél. A szervertulajdonos az egyetlen teljes bypass.", inline=False)
        return embed

    async def words_embed(self, guild: discord.Guild) -> discord.Embed:
        words = await self.settings.list_words(guild.id)
        embed = base_embed("🚫 Tiltott szavak / kifejezések")
        embed.description = "\n".join(f"• `{word}`" for word in words[:30]) if words else "Még nincs saját tiltott szó vagy kifejezés."
        if len(words) > 30:
            embed.set_footer(text=f"Yoru • Settings • +{len(words) - 30} további elem")
        return embed

    async def logs_embed(self, guild: discord.Guild) -> tuple[discord.Embed, dict[str, bool]]:
        channel_id = await self.settings.get_log_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        states = {key: await self.settings.get_log_enabled(guild.id, key) for key in LOG_LABELS}
        embed = base_embed("📝 Moderációs logok")
        embed.add_field(name="📍 Log csatorna", value=channel.mention if hasattr(channel, "mention") else "Nincs beállítva", inline=False)
        embed.add_field(
            name="Log típusok",
            value="\n".join(f"{'✅' if states[key] else '❌'} {label}" for key, label in LOG_LABELS.items()),
            inline=False,
        )
        embed.add_field(name="🖼️ Attachment cache", value=f"max {modcfg.ATTACHMENT_CACHE_FILE_MAX_BYTES // 1024 // 1024} MB/fájl • {modcfg.ATTACHMENT_CACHE_TTL_SECONDS // 60} perc", inline=False)
        embed.set_footer(text="Yoru • Settings • A dropdown kiválasztott logtípust azonnal átkapcsolja")
        return embed, states

    async def moderation_embed(self, guild: discord.Guild) -> discord.Embed:
        channel_id = await self.settings.get_log_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        me = guild.me
        perms = me.guild_permissions if me else None
        embed = base_embed("📋 Moderáció • Állapot")
        embed.add_field(name="📝 Modlog", value=channel.mention if hasattr(channel, "mention") else "Nincs beállítva", inline=False)
        if perms:
            checks = [
                ("View Audit Log", perms.view_audit_log),
                ("Manage Messages", perms.manage_messages),
                ("Moderate Members", perms.moderate_members),
                ("Ban Members", perms.ban_members),
                ("Kick Members", perms.kick_members),
                ("Manage Roles", perms.manage_roles),
            ]
            embed.add_field(name="🔐 Yoru permissionök", value="\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks), inline=False)
        embed.add_field(name="🧾 Esetek", value="`!case <id>` / `/case` • `!modlog @user`", inline=False)
        embed.set_footer(text="Yoru • Settings • A Discord UI-ból végzett moderációhoz View Audit Log szükséges")
        return embed

    def validate_config_roles(self, guild: discord.Guild, roles: list[discord.Role]) -> tuple[list[discord.Role], list[str]]:
        me = guild.me
        valid: list[discord.Role] = []
        skipped: list[str] = []
        for role in roles:
            perms = role.permissions
            dangerous = any(bool(getattr(perms, name, False)) for name in (
                "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
                "ban_members", "kick_members", "moderate_members", "manage_messages",
            ))
            assignable = (
                me is not None
                and me.guild_permissions.manage_roles
                and not role.is_default()
                and not role.managed
                and not dangerous
                and me.top_role > role
            )
            if assignable:
                valid.append(role)
            else:
                skipped.append(role.name)
        return valid, skipped

    async def welcome_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.settings.get_welcome_enabled(guild.id)
        channel_id = await self.settings.get_welcome_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        templates = await self.settings.get_welcome_templates(guild.id)
        embed_enabled = await self.settings.get_welcome_embed(guild.id)
        random_enabled = await self.settings.get_welcome_random(guild.id)
        dm_enabled = await self.settings.get_welcome_dm_enabled(guild.id)
        goodbye_enabled = await self.settings.get_goodbye_enabled(guild.id)
        embed = base_embed("👋 Welcome / Goodbye")
        embed.add_field(name="Welcome", value="✅ ON" if enabled else "❌ OFF", inline=True)
        embed.add_field(name="Csatorna", value=channel.mention if hasattr(channel, "mention") else "Nincs beállítva", inline=True)
        embed.add_field(name="Megjelenés", value="Embed" if embed_enabled else "Sima szöveg", inline=True)
        embed.add_field(name="Random sablon", value=f"{'✅ ON' if random_enabled else '❌ OFF'} • {len(templates)} sablon", inline=True)
        embed.add_field(name="Privát DM", value="✅ ON" if dm_enabled else "❌ OFF", inline=True)
        embed.add_field(name="Goodbye", value="✅ ON" if goodbye_enabled else "❌ OFF", inline=True)
        embed.add_field(
            name="Használható változók",
            value="`{user}` `{username}` `{display_name}` `{server}` `{membercount}` `{account_age}`",
            inline=False,
        )
        embed.set_footer(text="Yoru • Welcome • A Teszt gomb csak neked mutat előnézetet")
        return embed

    async def welcome_variants_embed(self, guild: discord.Guild) -> discord.Embed:
        templates = await self.settings.get_welcome_templates(guild.id)
        embed = base_embed("🗂️ Random welcome sablonok", "Random módnál Yoru ezek közül választ minden belépőnél.")
        for index, template in enumerate(templates[:10], start=1):
            preview = template.replace("\n", " ")
            if len(preview) > 180:
                preview = preview[:177] + "..."
            embed.add_field(name=f"#{index}", value=preview, inline=False)
        embed.set_footer(text=f"Yoru • Welcome • {len(templates)}/10 sablon")
        return embed

    async def goodbye_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self.settings.get_goodbye_enabled(guild.id)
        channel_id = await self.settings.get_goodbye_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        use_embed = await self.settings.get_goodbye_embed(guild.id)
        embed = base_embed("👋 Goodbye beállítások")
        embed.add_field(name="Állapot", value="✅ ON" if enabled else "❌ OFF", inline=True)
        embed.add_field(name="Csatorna", value=channel.mention if hasattr(channel, "mention") else "Nincs beállítva", inline=True)
        embed.add_field(name="Megjelenés", value="Embed" if use_embed else "Sima szöveg", inline=True)
        embed.add_field(name="Üzenet", value=(await self.settings.get_goodbye_template(guild.id))[:900], inline=False)
        embed.set_footer(text="Yoru • Goodbye")
        return embed

    async def roles_embed(self, guild: discord.Guild) -> discord.Embed:
        humans = await self.settings.get_human_autoroles(guild.id)
        bots = await self.settings.get_bot_autoroles(guild.id)
        restore = await self.settings.get_role_restore_enabled(guild.id)
        panels = await self.db.list_role_panels(guild.id, active_only=True)
        verification = await self.db.get_verification_panel(guild.id)

        def render_roles(ids: list[int]) -> str:
            values = []
            for role_id in ids:
                role = guild.get_role(role_id)
                values.append(role.mention if role else f"`{role_id}` *(hiányzik)*")
            return ", ".join(values) or "—"

        embed = base_embed("🎭 Roles & Verification")
        embed.add_field(name="👤 Emberi autoroles", value=render_roles(humans), inline=False)
        embed.add_field(name="🤖 Bot autoroles", value=render_roles(bots), inline=False)
        embed.add_field(name="♻️ Role restore", value="✅ ON" if restore else "❌ OFF", inline=True)
        embed.add_field(name="🎛️ Aktív self-role panelek", value=str(len(panels)), inline=True)
        embed.add_field(name="✅ Verification", value="Aktív" if verification and verification["active"] else "Nincs aktív panel", inline=True)
        embed.add_field(name="ℹ️ Ranghierarchia", value="Yoru csak a saját legmagasabb rangja alatt lévő, nem managed rangokat tudja kiosztani.", inline=False)
        embed.set_footer(text="Yoru • Roles • Minden panel persistent, restart után is működik")
        return embed

    async def autoroles_embed(self, guild: discord.Guild) -> discord.Embed:
        humans = await self.settings.get_human_autoroles(guild.id)
        bots = await self.settings.get_bot_autoroles(guild.id)
        human_text = "\n".join(guild.get_role(r).mention if guild.get_role(r) else f"`{r}`" for r in humans) or "—"
        bot_text = "\n".join(guild.get_role(r).mention if guild.get_role(r) else f"`{r}`" for r in bots) or "—"
        embed = base_embed("🤖 Autorole beállítások")
        embed.add_field(name="👤 Belépő emberek", value=human_text, inline=True)
        embed.add_field(name="🤖 Belépő botok", value=bot_text, inline=True)
        embed.set_footer(text="Yoru • Autoroles • Új kiválasztás felülírja az adott listát")
        return embed

    async def role_builder_embed(self, guild: discord.Guild, view: RolePanelBuilderView) -> discord.Embed:
        channel = guild.get_channel(view.channel_id) if view.channel_id else None
        roles = [guild.get_role(role_id) for role_id in view.role_ids]
        role_text = ", ".join(role.mention for role in roles if role is not None) or "Nincs kiválasztva"
        embed = base_embed("🎛️ Self-role panel készítő")
        embed.add_field(name="1️⃣ Csatorna", value=channel.mention if hasattr(channel, "mention") else "Nincs kiválasztva", inline=False)
        embed.add_field(name="2️⃣ Rangok", value=role_text, inline=False)
        embed.add_field(name="3️⃣ Mód", value="Egy választás" if view.mode == "single" else "Több rang választható", inline=True)
        embed.add_field(name="Cím", value=view.title, inline=True)
        embed.add_field(name="Leírás", value=view.description or "—", inline=False)
        embed.set_footer(text="Yoru • Self Roles • max. 10 rang/panel")
        return embed

    async def role_panels_embed(self, guild: discord.Guild, panels: list[dict], selected_panel_id: int | None) -> discord.Embed:
        embed = base_embed("🗂️ Self-role panelek kezelése")
        if not panels:
            embed.description = "Nincs aktív self-role panel ezen a szerveren."
            return embed
        lines = []
        for panel in panels[:20]:
            channel = guild.get_channel(panel["channel_id"])
            marker = "👉 " if panel["panel_id"] == selected_panel_id else ""
            lines.append(f"{marker}**#{panel['panel_id']}** • {panel['title']} • {getattr(channel, 'mention', '#hiányzik')} • {len(panel['items'])} rang")
        embed.description = "\n".join(lines)
        embed.set_footer(text="Yoru • Self Roles • Deaktiválás törli a panel üzenetét is")
        return embed

    async def verification_embed(self, guild: discord.Guild, view: VerificationSettingsView) -> discord.Embed:
        channel = guild.get_channel(view.channel_id) if view.channel_id else None
        role = guild.get_role(view.role_id) if view.role_id else None
        remove_role = guild.get_role(view.remove_role_id) if view.remove_role_id else None
        active = await self.db.get_verification_panel(guild.id)
        embed = base_embed("✅ Verification / Rules acceptance")
        embed.add_field(name="Csatorna", value=channel.mention if hasattr(channel, "mention") else "Nincs kiválasztva", inline=False)
        embed.add_field(name="Elfogadáskor kapja", value=role.mention if role else "Nincs kiválasztva", inline=True)
        embed.add_field(name="Opcionálisan leveszi", value=remove_role.mention if remove_role else "—", inline=True)
        embed.add_field(name="Aktív panel", value="✅ Igen" if active and active["active"] else "❌ Nincs", inline=True)
        embed.add_field(name="Cím", value=view.title, inline=False)
        embed.add_field(name="Szöveg", value=view.body, inline=False)
        embed.add_field(name="Gomb", value=view.button_label, inline=True)
        embed.set_footer(text="Yoru • Verification • Új kiküldés lecseréli a korábbi aktív panelt")
        return embed

    async def send_welcome_preview(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        from app.cogs.welcome_roles import render_member_template
        templates = await self.settings.get_welcome_templates(interaction.guild_id)
        text = render_member_template(templates[0], interaction.user)
        if await self.settings.get_welcome_embed(interaction.guild_id):
            title = render_member_template(await self.settings.get_welcome_title(interaction.guild_id), interaction.user)
            embed = base_embed(title, text, SUCCESS)
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def send_goodbye_preview(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        from app.cogs.welcome_roles import render_member_template
        text = render_member_template(await self.settings.get_goodbye_template(interaction.guild_id), interaction.user)
        if await self.settings.get_goodbye_embed(interaction.guild_id):
            title = render_member_template(await self.settings.get_goodbye_title(interaction.guild_id), interaction.user)
            embed = base_embed(title, text)
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def setup_embed(self, guild: discord.Guild, view: SetupView | None = None) -> discord.Embed:
        enabled = await self.settings.get_automod_enabled(guild.id)
        channel_id = await self.settings.get_log_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        embed = base_embed(
            "✨ Yoru • Gyors szerver setup",
            "A mezőket felülről lefelé állítsd be. Minden választás azonnal mentődik, nincs külön Save gomb.",
        )
        embed.add_field(name="1️⃣ AutoMod", value=(PRESET_LABELS.get(view.preset, "✅ Már konfigurálva") if view and view.preset else ("✅ Aktív" if enabled else "⚪ Válassz presetet")), inline=False)
        embed.add_field(name="2️⃣ Modlog", value=channel.mention if hasattr(channel, "mention") else "⚪ Nincs kiválasztva", inline=False)
        embed.add_field(name="3️⃣ Partner csatornák", value=f"✅ {view.partner_count} hozzáadva" if view and view.partner_count else "Opcionális • Discord invite engedélyezés", inline=False)
        embed.add_field(name="4️⃣ Ticket kategóriák", value=f"✅ {view.ticket_count} hozzáadva" if view and view.ticket_count else "Opcionális • Invite + link kivétel", inline=False)
        embed.add_field(name="5️⃣ Staff rangok", value=f"✅ {view.staff_count} hozzáadva" if view and view.staff_count else "Opcionális • globális AutoMod kivétel", inline=False)
        embed.set_footer(text="Yoru • Setup • Finomhangolás: /settings")
        return embed

    async def show_welcome(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: WelcomeView | None = None,
    ) -> None:
        channel_page = existing.channel_page if existing is not None else 0
        view = WelcomeView(
            self,
            owner_id,
            interaction.guild,
            enabled=await self.settings.get_welcome_enabled(interaction.guild_id),
            embed_enabled=await self.settings.get_welcome_embed(interaction.guild_id),
            random_enabled=await self.settings.get_welcome_random(interaction.guild_id),
            dm_enabled=await self.settings.get_welcome_dm_enabled(interaction.guild_id),
            channel_page=channel_page,
        )
        await interaction.response.edit_message(embed=await self.welcome_embed(interaction.guild), view=view)

    async def show_welcome_variants(self, interaction: discord.Interaction, owner_id: int) -> None:
        await interaction.response.edit_message(embed=await self.welcome_variants_embed(interaction.guild), view=WelcomeVariantsView(self, owner_id))

    async def show_goodbye(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: GoodbyeView | None = None,
    ) -> None:
        channel_page = existing.channel_page if existing is not None else 0
        view = GoodbyeView(
            self,
            owner_id,
            interaction.guild,
            enabled=await self.settings.get_goodbye_enabled(interaction.guild_id),
            embed_enabled=await self.settings.get_goodbye_embed(interaction.guild_id),
            channel_page=channel_page,
        )
        await interaction.response.edit_message(embed=await self.goodbye_embed(interaction.guild), view=view)

    async def show_roles(self, interaction: discord.Interaction, owner_id: int) -> None:
        restore = await self.settings.get_role_restore_enabled(interaction.guild_id)
        await interaction.response.edit_message(embed=await self.roles_embed(interaction.guild), view=RolesView(self, owner_id, restore))

    async def show_autoroles(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: AutorolesView | None = None,
    ) -> None:
        view = AutorolesView(
            self,
            owner_id,
            interaction.guild,
            human_role_page=existing.human_role_page if existing else 0,
            bot_role_page=existing.bot_role_page if existing else 0,
        )
        await interaction.response.edit_message(embed=await self.autoroles_embed(interaction.guild), view=view)

    async def show_role_builder(self, interaction: discord.Interaction, owner_id: int, existing: RolePanelBuilderView | None = None) -> None:
        if existing is None:
            view = RolePanelBuilderView(self, owner_id, interaction.guild)
        else:
            view = RolePanelBuilderView(
                self,
                owner_id,
                interaction.guild,
                channel_id=existing.channel_id,
                role_ids=existing.role_ids,
                mode=existing.mode,
                title=existing.title,
                description=existing.description,
                channel_page=existing.channel_page,
                role_page=existing.role_page,
            )
        await interaction.response.edit_message(embed=await self.role_builder_embed(interaction.guild, view), view=view)

    async def show_role_panels(self, interaction: discord.Interaction, owner_id: int, selected_panel_id: int | None = None) -> None:
        panels = await self.db.list_role_panels(interaction.guild_id, active_only=True)
        view = RolePanelManagerView(self, owner_id, panels, selected_panel_id)
        await interaction.response.edit_message(embed=await self.role_panels_embed(interaction.guild, panels, selected_panel_id), view=view)

    async def show_verification(self, interaction: discord.Interaction, owner_id: int, existing: VerificationSettingsView | None = None) -> None:
        if existing is None:
            panel = await self.db.get_verification_panel(interaction.guild_id)
            if panel:
                view = VerificationSettingsView(
                    self,
                    owner_id,
                    interaction.guild,
                    channel_id=panel["channel_id"],
                    role_id=panel["role_id"],
                    remove_role_id=panel["remove_role_id"],
                    title=panel["title"],
                    body=panel["body"],
                    button_label=panel["button_label"],
                )
            else:
                view = VerificationSettingsView(self, owner_id, interaction.guild)
        else:
            view = VerificationSettingsView(
                self,
                owner_id,
                interaction.guild,
                channel_id=existing.channel_id,
                role_id=existing.role_id,
                remove_role_id=existing.remove_role_id,
                title=existing.title,
                body=existing.body,
                button_label=existing.button_label,
                channel_page=existing.channel_page,
                give_role_page=existing.give_role_page,
                remove_role_page=existing.remove_role_page,
            )
        await interaction.response.edit_message(embed=await self.verification_embed(interaction.guild, view), view=view)

    async def show_community(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: CommunitySettingsView | None = None,
    ) -> None:
        embed, states = await self.community_embed(interaction.guild)
        view = CommunitySettingsView(
            self,
            owner_id,
            interaction.guild,
            states,
            suggestion_channel_page=existing.suggestion_channel_page if existing else 0,
            starboard_channel_page=existing.starboard_channel_page if existing else 0,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_home(self, interaction: discord.Interaction, owner_id: int) -> None:
        await interaction.response.edit_message(embed=await self.home_embed(interaction.guild), view=HomeView(self, owner_id))

    async def show_automod(self, interaction: discord.Interaction, owner_id: int) -> None:
        enabled = await self.settings.get_automod_enabled(interaction.guild_id)
        await interaction.response.edit_message(embed=await self.automod_embed(interaction.guild), view=AutomodView(self, owner_id, enabled))

    async def show_rule(self, interaction: discord.Interaction, owner_id: int, rule: str) -> None:
        embed, state = await self.rule_embed(interaction.guild, rule)
        await interaction.response.edit_message(embed=embed, view=RuleView(self, owner_id, rule, **state))

    async def show_exemptions(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        rule: str,
        remove_mode: bool = False,
        existing: ExemptionsView | None = None,
    ) -> None:
        view = ExemptionsView(
            self,
            owner_id,
            interaction.guild,
            rule,
            remove_mode,
            channel_page=existing.channel_page if existing else 0,
            category_page=existing.category_page if existing else 0,
            role_page=existing.role_page if existing else 0,
        )
        await interaction.response.edit_message(
            embed=await self.exemptions_embed(interaction.guild, rule, remove_mode),
            view=view,
        )

    async def show_domains(self, interaction: discord.Interaction, owner_id: int) -> None:
        await interaction.response.edit_message(embed=await self.domains_embed(interaction.guild), view=DomainsView(self, owner_id))

    async def show_words(self, interaction: discord.Interaction, owner_id: int) -> None:
        await interaction.response.edit_message(embed=await self.words_embed(interaction.guild), view=WordsView(self, owner_id))

    async def show_logs(
        self,
        interaction: discord.Interaction,
        owner_id: int,
        existing: LogsView | None = None,
    ) -> None:
        embed, states = await self.logs_embed(interaction.guild)
        view = LogsView(
            self,
            owner_id,
            states,
            interaction.guild,
            channel_page=existing.channel_page if existing else 0,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_moderation(self, interaction: discord.Interaction, owner_id: int) -> None:
        await interaction.response.edit_message(embed=await self.moderation_embed(interaction.guild), view=ModerationView(self, owner_id))

    async def show_setup(self, interaction: discord.Interaction, owner_id: int, existing: SetupView | None = None) -> None:
        if existing is None:
            view = SetupView(self, owner_id, interaction.guild)
        else:
            view = SetupView(
                self,
                owner_id,
                interaction.guild,
                preset=existing.preset,
                log_channel_id=existing.log_channel_id,
                partner_count=existing.partner_count,
                ticket_count=existing.ticket_count,
                staff_count=existing.staff_count,
                log_channel_page=existing.log_channel_page,
                partner_channel_page=existing.partner_channel_page,
                ticket_category_page=existing.ticket_category_page,
                staff_role_page=existing.staff_role_page,
            )
        await interaction.response.edit_message(embed=await self.setup_embed(interaction.guild, view), view=view)

    @app_commands.command(name="settings", description="Interaktív Yoru szerverbeállítások.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.send_message(embed=await self.home_embed(interaction.guild), view=HomeView(self, interaction.user.id), ephemeral=True)

    @commands.command(name="settings", aliases=["configpanel", "panel"])
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def settings_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await self.home_embed(ctx.guild), view=HomeView(self, ctx.author.id), delete_after=600)

    @app_commands.command(name="setup", description="Yoru gyors interaktív szerver setup.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        view = SetupView(self, interaction.user.id, interaction.guild)
        await interaction.response.send_message(embed=await self.setup_embed(interaction.guild, view), view=view, ephemeral=True)

    @commands.command(name="setup", aliases=["yorusetup"])
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setup_prefix(self, ctx: commands.Context) -> None:
        view = SetupView(self, ctx.author.id, ctx.guild)
        await ctx.send(embed=await self.setup_embed(ctx.guild, view), view=view, delete_after=600)
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "⛔ Ehhez **Szerver kezelése** jogosultság kell."
        else:
            raise error
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

