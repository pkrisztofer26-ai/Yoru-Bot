from __future__ import annotations

from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from app import heist_config as cfg
from app.cogs.access_utils import handle_wrong_economy_channel
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed, error_embed, money


def _ts(value: datetime | str | None, style: str = "R") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return "—"
    return f"<t:{int(value.timestamp())}:{style}>"


def _target_label(target: cfg.HeistTarget) -> str:
    return f"{target.emoji} {target.name}"


class TargetSelect(discord.ui.Select):
    def __init__(self, view: "HeistPlayerView") -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(
                label=target.name[:100], value=target.key, emoji=target.emoji,
                description=f"{target.location} • {target.min_party}-{target.max_party} fő • {money(target.reward_min)}+"[:100],
                default=target.key == view.selected_target,
            )
            for target in cfg.HEIST_TARGETS
        ]
        super().__init__(placeholder="Válassz Nagy Meló célpontot…", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_target = self.values[0]
        await self.parent_view.refresh(interaction)


class InviteSelect(discord.ui.Select):
    def __init__(self, view: "HeistPlayerView", invites: list[dict[str, Any]]) -> None:
        self.parent_view = view
        options = []
        for item in invites[:25]:
            target = cfg.TARGET_BY_KEY.get(str(item["target_key"]))
            options.append(discord.SelectOption(
                label=(target.name if target else str(item["target_key"]))[:100],
                value=str(item["lobby_id"]),
                emoji=(target.emoji if target else "🎯"),
                description=f"Leader: {item['leader_id']} • lejár {_ts(item['expires_at'])}"[:100],
                default=int(item["lobby_id"]) == (view.selected_invite_id or -1),
            ))
        super().__init__(placeholder="Válassz meghívót…", options=options, min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_invite_id = int(self.values[0])
        await self.parent_view.refresh(interaction)


class LobbyMemberSelect(discord.ui.Select):
    def __init__(self, view: "HeistPlayerView", members: list[dict[str, Any]]) -> None:
        self.parent_view = view
        options = [
            discord.SelectOption(
                label=f"User {int(m['user_id'])}", value=str(int(m["user_id"])),
                description=f"{m['cut_percent']}% • {m['role_key']} • {'elfogadva' if m['cut_accepted'] else 'nincs elfogadva'}"[:100],
                default=int(m["user_id"]) == (view.selected_member_id or -1),
            )
            for m in members if m["status"] == "accepted"
        ][:25]
        super().__init__(placeholder="Tag kiválasztása részesedéshez…", options=options, min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_member_id = int(self.values[0])
        await self.parent_view.refresh(interaction)


class RoleSelect(discord.ui.Select):
    def __init__(self, view: "HeistPlayerView", current: str) -> None:
        self.parent_view = view
        options = [discord.SelectOption(
            label=role.name, value=role.key, emoji=role.emoji,
            description=f"Prep +{role.prep_bonus} • Exec +{role.execution_bonus} • Escape +{role.escape_bonus}"[:100],
            default=role.key == current,
        ) for role in cfg.HEIST_ROLES]
        super().__init__(placeholder="Saját szerepköröd…", options=options, min_values=1, max_values=1, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.service.set_role(interaction.guild_id, self.parent_view.lobby_id, interaction.user.id, self.values[0])
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class LoadoutSelect(discord.ui.Select):
    def __init__(self, view: "HeistPlayerView", inventory: dict[str, int], current: str | None) -> None:
        self.parent_view = view
        options = [discord.SelectOption(label="Nincs gear", value="none", emoji="➖", default=current is None)]
        for gear in cfg.HEIST_GEAR:
            quantity = inventory.get(gear.key, 0)
            if quantity <= 0:
                continue
            options.append(discord.SelectOption(
                label=f"{gear.name} ×{quantity}"[:100], value=gear.key, emoji=gear.emoji,
                description=gear.description[:100], default=current == gear.key,
            ))
        super().__init__(placeholder="Saját loadout…", options=options[:25], min_values=1, max_values=1, row=3)

    async def callback(self, interaction: discord.Interaction) -> None:
        key = None if self.values[0] == "none" else self.values[0]
        try:
            await self.parent_view.cog.service.set_gear(interaction.guild_id, self.parent_view.lobby_id, interaction.user.id, key)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class GearShopSelect(discord.ui.Select):
    def __init__(self, view: "HeistPlayerView") -> None:
        self.parent_view = view
        options = [discord.SelectOption(
            label=gear.name, value=gear.key, emoji=gear.emoji,
            description=f"{money(gear.price)} • {gear.description}"[:100],
            default=gear.key == view.selected_gear,
        ) for gear in cfg.HEIST_GEAR]
        super().__init__(placeholder="Válassz felszerelést…", options=options, min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_gear = self.values[0]
        await self.parent_view.refresh(interaction)


class CutModal(discord.ui.Modal, title="Nagy Meló • Részesedés"):
    percent = discord.ui.TextInput(label="Részesedés %", placeholder="pl. 25", min_length=1, max_length=3)

    def __init__(self, view: "HeistPlayerView", member_id: int, current: int) -> None:
        super().__init__()
        self.parent_view = view
        self.member_id = member_id
        self.percent.default = str(current)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = int(str(self.percent.value).strip())
            await self.parent_view.cog.service.set_cut(interaction.guild_id, self.parent_view.lobby_id, interaction.user.id, self.member_id, value)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.parent_view.refresh(interaction)


class HeistUserSelect(discord.ui.UserSelect):
    def __init__(self, parent_view: "InviteUserView") -> None:
        self.parent_view = parent_view
        super().__init__(placeholder="Válassz egy játékost…", min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.values:
            return
        user = self.values[0]
        if user.bot:
            return await interaction.response.send_message("❌ Botot nem hívhatsz Nagy Melóba.", ephemeral=True)
        try:
            await self.parent_view.cog.service.invite_member(
                interaction.guild_id, self.parent_view.lobby_id, interaction.user.id, user.id
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.edit_message(
            content=f"✅ Meghívó elküldve: {user.mention}. Nyissa meg a `!heist` panelt az elfogadáshoz.",
            view=None,
        )


class InviteUserView(discord.ui.View):
    def __init__(self, cog: "HeistCog", owner_id: int, lobby_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.lobby_id = lobby_id
        self.add_item(HeistUserSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a pickert nem te nyitottad meg.", ephemeral=True)
            return False
        return True


class HeistResultView(discord.ui.View):
    def __init__(self, cog: "HeistCog", owner_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Nagy Meló panel", emoji="🎯", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        embed, view = await self.cog.build_panel(interaction.guild, interaction.user, mode="targets")
        await interaction.response.edit_message(embed=embed, view=view)


class HeistPlayerView(discord.ui.View):
    def __init__(
        self,
        cog: "HeistCog",
        owner_id: int,
        *,
        mode: str,
        selected_target: str | None = None,
        selected_gear: str | None = None,
        selected_invite_id: int | None = None,
        lobby_id: int | None = None,
        selected_member_id: int | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id
        self.mode = mode
        self.selected_target = selected_target or cfg.HEIST_TARGETS[0].key
        self.selected_gear = selected_gear or cfg.HEIST_GEAR[0].key
        self.selected_invite_id = selected_invite_id
        self.lobby_id = lobby_id or 0
        self.selected_member_id = selected_member_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a Nagy Meló panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction: discord.Interaction) -> None:
        embed, view = await self.cog.build_panel(
            interaction.guild, interaction.user, mode=self.mode,
            selected_target=self.selected_target, selected_gear=self.selected_gear,
            selected_invite_id=self.selected_invite_id, selected_member_id=self.selected_member_id,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Célpontok", emoji="🎯", style=discord.ButtonStyle.primary, row=0)
    async def targets(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.mode = "targets"; await self.refresh(interaction)

    @discord.ui.button(label="Lobby", emoji="👥", style=discord.ButtonStyle.secondary, row=0)
    async def lobby(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.mode = "lobby"; await self.refresh(interaction)

    @discord.ui.button(label="Gear", emoji="🎒", style=discord.ButtonStyle.secondary, row=0)
    async def gear(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.mode = "gear"; await self.refresh(interaction)

    @discord.ui.button(label="Előzmények", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def history(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.mode = "history"; await self.refresh(interaction)

    @discord.ui.button(label="Meghívók", emoji="✉️", style=discord.ButtonStyle.secondary, row=0)
    async def invites(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.mode = "invites"; await self.refresh(interaction)

    async def create_lobby_button(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.create_lobby(interaction.guild_id, interaction.user.id, self.selected_target)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.mode = "lobby"; await self.refresh(interaction)

    async def buy_gear_button(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.buy_gear(interaction.guild_id, interaction.user.id, self.selected_gear, 1)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.refresh(interaction)

    async def accept_invite_button(self, interaction: discord.Interaction, accept: bool) -> None:
        if not self.selected_invite_id:
            return await interaction.response.send_message("❌ Válassz meghívót.", ephemeral=True)
        try:
            await self.cog.service.respond_invite(interaction.guild_id, self.selected_invite_id, interaction.user.id, accept=accept)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.mode = "lobby" if accept else "invites"; await self.refresh(interaction)

    async def invite_button(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("👥 Kit hívsz a Nagy Melóba?", view=InviteUserView(self.cog, interaction.user.id, self.lobby_id), ephemeral=True)

    async def cut_button(self, interaction: discord.Interaction, members: list[dict[str, Any]]) -> None:
        if not self.selected_member_id:
            return await interaction.response.send_message("❌ Előbb válassz tagot a listából.", ephemeral=True)
        member = next((m for m in members if int(m["user_id"]) == self.selected_member_id), None)
        if member is None:
            return await interaction.response.send_message("❌ A tag már nincs a lobbyban.", ephemeral=True)
        await interaction.response.send_modal(CutModal(self, self.selected_member_id, int(member["cut_percent"])))

    async def accept_cut_button(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.accept_cut(interaction.guild_id, self.lobby_id, interaction.user.id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.refresh(interaction)

    async def start_or_advance_button(self, interaction: discord.Interaction, running: bool) -> None:
        try:
            result = await (self.cog.service.advance_phase(interaction.guild_id, self.lobby_id, interaction.user.id) if running else self.cog.service.start_heist(interaction.guild_id, self.lobby_id, interaction.user.id))
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        if result.get("status") in {"success", "failed"}:
            embed = await self.cog.build_result_embed(interaction.guild, result)
            return await interaction.response.edit_message(embed=embed, view=HeistResultView(self.cog, interaction.user.id))
        await self.refresh(interaction)

    async def cancel_or_leave_button(self, interaction: discord.Interaction, leader: bool) -> None:
        try:
            if leader:
                await self.cog.service.cancel_lobby(interaction.guild_id, self.lobby_id, interaction.user.id)
            else:
                await self.cog.service.remove_member(interaction.guild_id, self.lobby_id, interaction.user.id, interaction.user.id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.mode = "targets"; await self.refresh(interaction)


class SimpleCallbackButton(discord.ui.Button):
    def __init__(self, *, label: str, emoji: str, style: discord.ButtonStyle, row: int, callback_fn) -> None:
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.callback_fn = callback_fn

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.callback_fn(interaction)


class UnlockSettingsModal(discord.ui.Modal, title="Nagy Meló • Unlock"):
    activity = discord.ui.TextInput(label="Minimum Activity Level", min_length=1, max_length=3)
    prestige = discord.ui.TextInput(label="Minimum Prestige", min_length=1, max_length=3)

    def __init__(self, cog: "HeistCog", owner_id: int, settings) -> None:
        super().__init__(); self.cog = cog; self.owner_id = owner_id
        self.activity.default = str(settings.required_activity_level); self.prestige.default = str(settings.required_prestige)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.set_unlock_settings(interaction.guild_id, activity_level=int(str(self.activity.value)), prestige=int(str(self.prestige.value)))
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class RiskSettingsModal(discord.ui.Modal, title="Nagy Meló • Balance"):
    cooldown = discord.ui.TextInput(label="Cooldown (óra)", min_length=1, max_length=3)
    jail = discord.ui.TextInput(label="Bukás jail (perc)", min_length=1, max_length=4)
    fine = discord.ui.TextInput(label="Bukás bírság %", min_length=1, max_length=2)
    gear_loss = discord.ui.TextInput(label="Gear loss esély %", min_length=1, max_length=3)
    reward = discord.ui.TextInput(label="Reward multiplier %", min_length=1, max_length=3)

    def __init__(self, cog: "HeistCog", owner_id: int, settings) -> None:
        super().__init__(); self.cog = cog; self.owner_id = owner_id
        self.cooldown.default = str(settings.cooldown_hours); self.jail.default = str(settings.jail_minutes)
        self.fine.default = str(settings.fine_percent); self.gear_loss.default = str(settings.gear_loss_percent)
        self.reward.default = str(settings.reward_multiplier_percent)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.service.set_risk_settings(
                interaction.guild_id, cooldown_hours=int(str(self.cooldown.value)), jail_minutes=int(str(self.jail.value)),
                fine_percent=int(str(self.fine.value)), gear_loss_percent=int(str(self.gear_loss.value)),
                reward_multiplier_percent=int(str(self.reward.value)),
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self.cog.show_settings(interaction, self.owner_id)


class HeistAdminView(discord.ui.View):
    def __init__(self, cog: "HeistCog", owner_id: int, enabled: bool) -> None:
        super().__init__(timeout=600); self.cog = cog; self.owner_id = owner_id; self.enabled = enabled
        self.toggle.label = "Nagy Meló: ON" if enabled else "Nagy Meló: OFF"
        self.toggle.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a settings panelt nem te nyitottad meg.", ephemeral=True); return False
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Nagy Meló", emoji="🎯", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.service.set_enabled(interaction.guild_id, not self.enabled)
        await self.cog.show_settings(interaction, self.owner_id)

    @discord.ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary, row=0)
    async def unlock(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(UnlockSettingsModal(self.cog, self.owner_id, await self.cog.service.get_settings(interaction.guild_id)))

    @discord.ui.button(label="Risk / Balance", emoji="⚖️", style=discord.ButtonStyle.secondary, row=0)
    async def balance(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RiskSettingsModal(self.cog, self.owner_id, await self.cog.service.get_settings(interaction.guild_id)))

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        settings_cog = self.cog.bot.get_cog("SettingsCog")
        if settings_cog is None:
            return await interaction.response.send_message("❌ Settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, self.owner_id)


class HeistCog(commands.Cog):
    heist = app_commands.Group(name="heist", description="Nagy Meló – kooperatív, fikciós endgame heistek.")

    def __init__(self, bot, database, economy, service) -> None:
        self.bot = bot
        self.db = database
        self.economy = economy
        self.service = service

    async def home_status(self, guild: discord.Guild) -> str:
        settings = await self.service.get_settings(guild.id)
        return (
            f"{'🟢 ON' if settings.enabled else '🔴 OFF'} • "
            f"Activity Lv.{settings.required_activity_level} • Prestige {settings.required_prestige}"
        )

    async def _prefix_access(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        try:
            await self.economy.prepare_context(ctx.guild.id)
            await self.economy.guild_settings.require_channel(ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None))
            return True
        except ValueError:
            await handle_wrong_economy_channel(ctx, self.economy)
            return False

    async def _slash_access(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None or interaction.channel is None:
            await interaction.response.send_message("❌ Ez csak szerveren használható.", ephemeral=True); return False
        try:
            await self.economy.prepare_context(interaction.guild_id)
            await self.economy.guild_settings.require_channel(interaction.guild_id, interaction.channel.id, getattr(interaction.channel, "category_id", None))
            return True
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True); return False

    async def build_panel(
        self,
        guild: discord.Guild,
        user: discord.abc.User,
        *,
        mode: str = "targets",
        selected_target: str | None = None,
        selected_gear: str | None = None,
        selected_invite_id: int | None = None,
        selected_member_id: int | None = None,
    ) -> tuple[discord.Embed, HeistPlayerView]:
        selected_target = selected_target or cfg.HEIST_TARGETS[0].key
        selected_gear = selected_gear or cfg.HEIST_GEAR[0].key
        active = await self.service.active_lobby_for_user(guild.id, user.id)
        lobby_id = int(active["lobby_id"]) if active else 0
        view = HeistPlayerView(
            self, user.id, mode=mode, selected_target=selected_target, selected_gear=selected_gear,
            selected_invite_id=selected_invite_id, lobby_id=lobby_id, selected_member_id=selected_member_id,
        )

        if mode == "targets":
            target = cfg.TARGET_BY_KEY.get(selected_target, cfg.HEIST_TARGETS[0])
            eligibility = await self.service.eligibility(guild.id, user.id, target.key)
            embed = base_embed("🎯 Nagy Meló • Célpontok", "Fikciós, absztrakt kooperatív endgame rendszer. A részletek játékmechanikák, nem valós műveleti útmutatók.")
            embed.add_field(name=_target_label(target), value=f"📍 {target.location}\n{target.flavor}\n👥 {target.min_party}–{target.max_party} fő • ⚠️ Nehézség {target.difficulty}/100", inline=False)
            embed.add_field(name="💰 Jutalompool", value=f"**{money(target.reward_min)} – {money(target.reward_max)}**", inline=True)
            embed.add_field(name="🔓 Követelmény", value=f"Activity **Lv.{max((await self.service.get_settings(guild.id)).required_activity_level,target.activity_level)}**\nPrestige **{max((await self.service.get_settings(guild.id)).required_prestige,target.prestige)}**", inline=True)
            status = "✅ Elérhető" if eligibility["eligible"] else "❌ Még nem elérhető"
            if eligibility["cooldown_until"]: status += f"\nCooldown: {_ts(eligibility['cooldown_until'])}"
            if eligibility["jailed_until"]: status += f"\nJail: {_ts(eligibility['jailed_until'])}"
            embed.add_field(name="📌 Állapot", value=status, inline=True)
            view.add_item(TargetSelect(view))
            view.add_item(SimpleCallbackButton(label="Lobby létrehozása", emoji="➕", style=discord.ButtonStyle.success, row=2, callback_fn=view.create_lobby_button))
            return embed, view

        if mode == "invites":
            invites = await self.service.pending_invites(guild.id, user.id)
            embed = base_embed("✉️ Nagy Meló • Meghívók", "A csatlakozás után a részesedést külön el kell fogadnod.")
            if not invites:
                embed.description = "Nincs aktív Nagy Meló meghívód."
                return embed, view
            if selected_invite_id is None or not any(int(item["lobby_id"]) == selected_invite_id for item in invites):
                selected_invite_id = int(invites[0]["lobby_id"]); view.selected_invite_id = selected_invite_id
            chosen = next(item for item in invites if int(item["lobby_id"]) == selected_invite_id)
            target = cfg.TARGET_BY_KEY.get(str(chosen["target_key"]))
            embed.add_field(name=(f"{target.emoji} {target.name}" if target else "🎯 Meghívó"), value=f"Leader: <@{chosen['leader_id']}>\nLejár: {_ts(chosen['expires_at'])}", inline=False)
            view.add_item(InviteSelect(view, invites))
            view.add_item(SimpleCallbackButton(label="Elfogadom", emoji="✅", style=discord.ButtonStyle.success, row=2, callback_fn=lambda i: view.accept_invite_button(i, True)))
            view.add_item(SimpleCallbackButton(label="Elutasítom", emoji="❌", style=discord.ButtonStyle.danger, row=2, callback_fn=lambda i: view.accept_invite_button(i, False)))
            return embed, view

        if mode == "gear":
            inventory = await self.service.gear_inventory(guild.id, user.id)
            gear = cfg.GEAR_BY_KEY.get(selected_gear, cfg.HEIST_GEAR[0])
            embed = base_embed("🎒 Nagy Meló • Gear", "A felszerelések tisztán absztrakt stat boostok. Bukáskor a beállított eséllyel elveszhet a kiválasztott darab.")
            for item in cfg.HEIST_GEAR:
                embed.add_field(name=f"{item.emoji} {item.name} • ×{inventory.get(item.key,0)}", value=f"{money(item.price)}\n{item.description}", inline=True)
            embed.add_field(name="🛒 Kiválasztva", value=f"**{gear.name}** • {money(gear.price)}", inline=False)
            view.add_item(GearShopSelect(view))
            view.add_item(SimpleCallbackButton(label="Vásárlás ×1", emoji="🛒", style=discord.ButtonStyle.success, row=2, callback_fn=view.buy_gear_button))
            return embed, view

        if mode == "history":
            history = await self.service.history(guild.id, user.id)
            embed = base_embed("📜 Nagy Meló • Előzmények")
            if not history:
                embed.description = "Még nincs lezárt Nagy Melód."
            else:
                lines = []
                for item in history[:12]:
                    target = cfg.TARGET_BY_KEY.get(str(item["target_key"]))
                    icon = "✅" if item["status"] == "success" else "❌"
                    lines.append(f"{icon} **{target.name if target else item['target_key']}** • pool {money(int(item['total_reward'] or 0))} • {_ts(item['resolved_at'])}")
                embed.description = "\n".join(lines)
            return embed, view

        # Lobby page
        if active is None:
            embed = base_embed("👥 Nagy Meló • Lobby", "Nincs aktív lobbyd. Válassz célpontot, vagy nézd meg a Meghívók oldalt.")
            return embed, view
        members = await self.service.lobby_members(guild.id, lobby_id)
        target = cfg.TARGET_BY_KEY.get(str(active["target_key"]))
        leader = int(active["leader_id"]) == user.id
        accepted = [m for m in members if m["status"] == "accepted"]
        own = next((m for m in accepted if int(m["user_id"]) == user.id), None)
        run = await self.service.run_state(guild.id, lobby_id) if active["status"] == "running" else {}
        embed = base_embed(f"👥 Nagy Meló • {_target_label(target) if target else active['target_key']}", f"Lobby **#{lobby_id}** • {'🟠 FUT' if active['status']=='running' else '🟢 SZERVEZÉS'}")
        lines = []
        for m in members:
            if m["status"] == "declined" or m["status"] == "left": continue
            status_icon = "✅" if m["status"] == "accepted" else "⏳"
            role = cfg.ROLE_BY_KEY.get(str(m["role_key"]))
            gear = cfg.GEAR_BY_KEY.get(str(m["gear_key"])) if m.get("gear_key") else None
            cut_ok = "✅" if m["cut_accepted"] else "⚠️"
            lines.append(f"{status_icon} <@{m['user_id']}> • {role.emoji if role else '🤝'} {role.name if role else m['role_key']} • {gear.emoji if gear else '➖'} • **{m['cut_percent']}%** {cut_ok}")
        embed.add_field(name=f"👥 Party ({len(accepted)}/{target.max_party if target else cfg.MAX_PARTY_SIZE})", value="\n".join(lines) or "—", inline=False)
        cut_total = sum(int(m["cut_percent"]) for m in accepted)
        embed.add_field(name="💸 Részesedés", value=f"Összesen: **{cut_total}%** • Minden tagnak külön el kell fogadnia.", inline=False)
        if active["status"] == "running":
            phase_results = run.get("phase_results", [])
            phase_lines = []
            for result in phase_results:
                phase_lines.append(f"{'✅' if result['passed'] else '❌'} {result['label']} • esély {result['chance']}% • roll {result['roll']}")
            next_phase = cfg.PHASE_LABELS[int(run.get("phase",0))][1] if int(run.get("phase",0)) < 3 else "Lezárva"
            embed.add_field(name="🎬 Fázisok", value=("\n".join(phase_lines) or "Még nincs lefutott fázis.") + f"\n\n**Következő:** {next_phase}", inline=False)
            embed.add_field(name="💰 Potenciális pool", value=money(int(run.get("reward_pool",0))), inline=True)
            if leader:
                view.add_item(SimpleCallbackButton(label="Következő fázis", emoji="▶️", style=discord.ButtonStyle.success, row=4, callback_fn=lambda i: view.start_or_advance_button(i, True)))
            return embed, view

        if accepted:
            if view.selected_member_id is None or not any(int(m["user_id"]) == view.selected_member_id for m in accepted):
                view.selected_member_id = int(accepted[0]["user_id"])
            view.add_item(LobbyMemberSelect(view, accepted))
        if own is not None:
            view.add_item(RoleSelect(view, str(own["role_key"])))
            view.add_item(LoadoutSelect(view, await self.service.gear_inventory(guild.id, user.id), own.get("gear_key")))
        if leader:
            view.add_item(SimpleCallbackButton(label="Meghívás", emoji="➕", style=discord.ButtonStyle.primary, row=4, callback_fn=view.invite_button))
            view.add_item(SimpleCallbackButton(label="Részesedés", emoji="💸", style=discord.ButtonStyle.secondary, row=4, callback_fn=lambda i: view.cut_button(i, accepted)))
        if own is not None and not bool(own["cut_accepted"]):
            view.add_item(SimpleCallbackButton(label="Részesedés OK", emoji="✅", style=discord.ButtonStyle.success, row=4, callback_fn=view.accept_cut_button))
        if leader:
            view.add_item(SimpleCallbackButton(label="Indítás", emoji="🚀", style=discord.ButtonStyle.success, row=4, callback_fn=lambda i: view.start_or_advance_button(i, False)))
            # If row would exceed 5 buttons, skip cancel when the cut button set is full.
            if len([c for c in view.children if getattr(c, "row", None) == 4]) < 5:
                view.add_item(SimpleCallbackButton(label="Törlés", emoji="🗑️", style=discord.ButtonStyle.danger, row=4, callback_fn=lambda i: view.cancel_or_leave_button(i, True)))
        else:
            view.add_item(SimpleCallbackButton(label="Kilépés", emoji="🚪", style=discord.ButtonStyle.danger, row=4, callback_fn=lambda i: view.cancel_or_leave_button(i, False)))
        return embed, view

    async def build_result_embed(self, guild: discord.Guild, result: dict[str, Any]) -> discord.Embed:
        target = cfg.TARGET_BY_KEY.get(str(result.get("target_key")))
        success = result.get("status") == "success"
        embed = base_embed(
            f"{'✅' if success else '❌'} Nagy Meló • {'SIKER' if success else 'BUKÁS'}",
            f"{_target_label(target) if target else result.get('target_key','Célpont')} • Lobby #{result.get('lobby_id')}",
            SUCCESS if success else DANGER,
        )
        lines = [f"{'✅' if r['passed'] else '❌'} {r['label']} • {r['chance']}% / roll {r['roll']}" for r in result.get("phase_results", [])]
        embed.add_field(name="🎬 Fázisok", value="\n".join(lines) or "—", inline=False)
        if success:
            payouts = result.get("payouts", {})
            embed.add_field(name="💰 Kifizetés", value="\n".join(f"<@{uid}> • **{money(amount)}**" for uid, amount in payouts.items()) or money(int(result.get("total_reward",0))), inline=False)
        else:
            fines = result.get("fines", {})
            lost = result.get("lost_gear", {})
            embed.add_field(name="🚔 Következmény", value="\n".join(f"<@{uid}> • bírság **{money(amount)}**" for uid, amount in fines.items()) or "Nincs bírság.", inline=False)
            if lost:
                embed.add_field(name="🎒 Elveszett gear", value="\n".join(f"<@{uid}> • {cfg.GEAR_BY_KEY.get(key).name if cfg.GEAR_BY_KEY.get(key) else key}" for uid,key in lost.items()), inline=False)
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int) -> None:
        settings = await self.service.get_settings(interaction.guild_id)
        embed = base_embed("🎯 Settings • Nagy Meló", "A rendszer minden paramétere Discordon belül állítható.")
        embed.add_field(name="Állapot", value="✅ ON" if settings.enabled else "❌ OFF", inline=True)
        embed.add_field(name="Unlock", value=f"Activity Lv.{settings.required_activity_level}\nPrestige {settings.required_prestige}", inline=True)
        embed.add_field(name="Cooldown", value=f"{settings.cooldown_hours} óra", inline=True)
        embed.add_field(name="Bukás", value=f"Jail {settings.jail_minutes} perc\nBírság {settings.fine_percent}%\nGear loss {settings.gear_loss_percent}%", inline=True)
        embed.add_field(name="Reward", value=f"{settings.reward_multiplier_percent}%", inline=True)
        view = HeistAdminView(self, owner_id, settings.enabled)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    @commands.command(name="heist", aliases=["nagymelo", "nagymeló", "melo", "meló"])
    @commands.guild_only()
    async def heist_prefix(self, ctx: commands.Context) -> None:
        if not await self._prefix_access(ctx): return
        embed, view = await self.build_panel(ctx.guild, ctx.author, mode="targets")
        await ctx.send(embed=embed, view=view)

    @commands.command(name="heisttop", aliases=["melotop", "nagymelotop"])
    @commands.guild_only()
    async def heisttop_prefix(self, ctx: commands.Context) -> None:
        if not await self._prefix_access(ctx): return
        rows = await self.service.leaderboard(ctx.guild.id)
        embed = base_embed("🏆 Nagy Meló toplista")
        embed.description = "\n".join(f"**{i}.** <@{uid}> • {money(earned)} • {wins} siker" for i,(uid,earned,wins) in enumerate(rows,1)) or "Még nincs adat."
        await ctx.send(embed=embed)

    @heist.command(name="panel", description="Megnyitja a teljes interaktív Nagy Meló panelt.")
    async def panel_slash(self, interaction: discord.Interaction) -> None:
        if not await self._slash_access(interaction): return
        embed, view = await self.build_panel(interaction.guild, interaction.user, mode="targets")
        await interaction.response.send_message(embed=embed, view=view)

    @heist.command(name="top", description="Nagy Meló ranglista.")
    async def top_slash(self, interaction: discord.Interaction) -> None:
        if not await self._slash_access(interaction): return
        rows = await self.service.leaderboard(interaction.guild_id)
        embed = base_embed("🏆 Nagy Meló toplista")
        embed.description = "\n".join(f"**{i}.** <@{uid}> • {money(earned)} • {wins} siker" for i,(uid,earned,wins) in enumerate(rows,1)) or "Még nincs adat."
        await interaction.response.send_message(embed=embed)
