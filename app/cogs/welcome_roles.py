from __future__ import annotations

import random
from datetime import datetime, timezone

import discord
from discord.ext import commands

from app.database import Database
from app.services.server_settings import ServerSettingsService
from app.ui import BRAND, SUCCESS, base_embed


class _TemplateValues(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _account_age(member: discord.Member) -> str:
    delta = datetime.now(timezone.utc) - member.created_at
    days = max(0, delta.days)
    if days >= 1:
        return f"{days} nap"
    hours = max(0, int(delta.total_seconds() // 3600))
    if hours >= 1:
        return f"{hours} óra"
    minutes = max(0, int(delta.total_seconds() // 60))
    return f"{minutes} perc"


def render_member_template(template: str, member: discord.Member) -> str:
    guild = member.guild
    values = _TemplateValues(
        user=member.mention,
        username=member.name,
        display_name=member.display_name,
        server=guild.name,
        membercount=str(guild.member_count or len(guild.members)),
        account_age=_account_age(member),
    )
    try:
        return template.format_map(values)
    except (ValueError, IndexError):
        # A rosszul lezárt kapcsos zárójel ne akadályozza meg a join eventet.
        return template


DANGEROUS_ROLE_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
    "ban_members", "kick_members", "moderate_members", "manage_messages",
)


def role_has_dangerous_permissions(role: discord.Role) -> bool:
    perms = role.permissions
    return any(bool(getattr(perms, name, False)) for name in DANGEROUS_ROLE_PERMISSIONS)


def role_assignable(guild: discord.Guild, role: discord.Role | None, *, public_safe: bool = True) -> bool:
    if role is None or role.is_default() or role.managed:
        return False
    if public_safe and role_has_dangerous_permissions(role):
        return False
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        return False
    return me.top_role > role


class RolePanelButton(discord.ui.Button):
    def __init__(self, cog: "WelcomeRolesCog", panel_id: int, role_id: int, label: str, emoji: str | None, row: int) -> None:
        super().__init__(
            label=(label or "Rang")[:80],
            emoji=emoji or "🎭",
            style=discord.ButtonStyle.secondary,
            custom_id=f"yoru:rolepanel:{panel_id}:{role_id}",
            row=row,
        )
        self.cog = cog
        self.panel_id = panel_id
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Ez a gomb csak szerveren használható.", ephemeral=True)

        panel = await self.cog.db.get_role_panel(self.panel_id)
        if panel is None or not panel["active"] or panel["guild_id"] != interaction.guild.id:
            return await interaction.response.send_message("❌ Ez a rangpanel már nem aktív.", ephemeral=True)

        role = interaction.guild.get_role(self.role_id)
        if not role_assignable(interaction.guild, role):
            return await interaction.response.send_message(
                "❌ Ezt a rangot Yoru nem tudja kezelni. Ellenőrizd a **Manage Roles** jogot és a ranghierarchiát.",
                ephemeral=True,
            )

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason=f"Yoru self-role panel #{self.panel_id}")
                return await interaction.response.send_message(f"➖ Levetted ezt a rangot: {role.mention}", ephemeral=True)

            if panel["mode"] == "single":
                other_roles = []
                for item_role_id, _label, _emoji, _position in panel["items"]:
                    other = interaction.guild.get_role(item_role_id)
                    if other is not None and other.id != role.id and other in member.roles and role_assignable(interaction.guild, other):
                        other_roles.append(other)
                if other_roles:
                    await member.remove_roles(*other_roles, reason=f"Yoru single-choice role panel #{self.panel_id}")

            await member.add_roles(role, reason=f"Yoru self-role panel #{self.panel_id}")
            await interaction.response.send_message(f"✅ Megkaptad ezt a rangot: {role.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Yoru nem tudja módosítani ezt a rangot a Discord jogosultságok miatt.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("❌ Discord hiba történt a rang módosításakor. Próbáld újra.", ephemeral=True)


class RolePanelView(discord.ui.View):
    def __init__(self, cog: "WelcomeRolesCog", panel: dict) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        for index, (role_id, label, emoji, _position) in enumerate(panel["items"][:10]):
            self.add_item(RolePanelButton(cog, panel["panel_id"], role_id, label, emoji, index // 5))


class VerificationButton(discord.ui.Button):
    def __init__(self, cog: "WelcomeRolesCog", guild_id: int, label: str) -> None:
        super().__init__(
            label=(label or "Elfogadom")[:80],
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"yoru:verify:{guild_id}",
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Ez az ellenőrzőpanel nem ehhez a szerverhez tartozik.", ephemeral=True)

        panel = await self.cog.db.get_verification_panel(self.guild_id)
        if panel is None or not panel["active"]:
            return await interaction.response.send_message("❌ Ez az ellenőrzőpanel már nem aktív.", ephemeral=True)

        role = interaction.guild.get_role(panel["role_id"])
        if not role_assignable(interaction.guild, role):
            return await interaction.response.send_message(
                "❌ A beállított ellenőrzött rangot Yoru nem tudja kiosztani. Szólj egy adminnak.", ephemeral=True
            )

        remove_role = interaction.guild.get_role(panel["remove_role_id"]) if panel["remove_role_id"] else None
        try:
            if role not in interaction.user.roles:
                await interaction.user.add_roles(role, reason="Yoru rules verification")
            if remove_role is not None and remove_role in interaction.user.roles and role_assignable(interaction.guild, remove_role):
                await interaction.user.remove_roles(remove_role, reason="Yoru rules verification")
            await interaction.response.send_message(f"✅ Sikeres ellenőrzés! Megkaptad ezt a rangot: {role.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Yoru ranghierarchiája/jogosultsága nem megfelelő ehhez.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("❌ Discord hiba történt. Próbáld újra.", ephemeral=True)


class VerificationView(discord.ui.View):
    def __init__(self, cog: "WelcomeRolesCog", guild_id: int, label: str) -> None:
        super().__init__(timeout=None)
        self.add_item(VerificationButton(cog, guild_id, label))


class WelcomeRolesCog(commands.Cog):
    """Welcome/goodbye, autorole, role restore, self-role and verification runtime."""

    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.settings = ServerSettingsService(db)

    async def cog_load(self) -> None:
        # Re-register persistent views before the bot becomes ready.
        for panel in await self.db.list_role_panels(active_only=True):
            if panel["items"]:
                self.bot.add_view(RolePanelView(self, panel), message_id=panel["message_id"])
        for panel in await self.db.list_verification_panels(active_only=True):
            self.bot.add_view(
                VerificationView(self, panel["guild_id"], panel["button_label"]),
                message_id=panel["message_id"],
            )

    async def post_role_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        creator_id: int,
        roles: list[discord.Role],
        title: str,
        description: str,
        mode: str,
    ) -> int:
        if mode not in {"toggle", "single"}:
            mode = "toggle"
        active_panels = await self.db.list_role_panels(guild.id, active_only=True)
        if len(active_panels) >= 20:
            raise ValueError("Maximum 20 aktív self-role panel lehet egy szerveren.")
        valid_roles = [role for role in roles if role_assignable(guild, role)]
        if not valid_roles:
            raise ValueError("Nincs kiosztható rang a panelen.")
        valid_roles = valid_roles[:10]
        items = [(role.id, role.name[:80], None, index) for index, role in enumerate(valid_roles)]
        panel_id = await self.db.create_role_panel(
            guild.id,
            channel.id,
            title[:256] or "🎭 Válassz rangot",
            description[:4000],
            mode,
            creator_id,
            items,
        )
        panel = await self.db.get_role_panel(panel_id)
        embed = base_embed(panel["title"], panel["description"] or "Az alábbi gombokkal kezelheted a saját rangjaidat.", BRAND)
        embed.add_field(
            name="Elérhető rangok",
            value="\n".join(f"• {role.mention}" for role in valid_roles),
            inline=False,
        )
        embed.set_footer(text="Yoru • Self Roles • A gomb újbóli megnyomása leveszi a rangot")
        view = RolePanelView(self, panel)
        message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        await self.db.set_role_panel_message(panel_id, message.id)
        return panel_id

    async def deactivate_role_panel(self, guild: discord.Guild, panel_id: int, *, delete_message: bool = True) -> bool:
        panel = await self.db.get_role_panel(panel_id)
        if panel is None or panel["guild_id"] != guild.id:
            return False
        changed = await self.db.deactivate_role_panel(panel_id)
        if delete_message and panel["message_id"]:
            channel = guild.get_channel(panel["channel_id"])
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(panel["message_id"])
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        return changed

    async def post_verification_panel(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        role: discord.Role,
        remove_role: discord.Role | None,
        title: str,
        body: str,
        button_label: str,
    ) -> int:
        if not role_assignable(guild, role):
            raise ValueError("A kiosztandó rangot Yoru nem tudja kezelni.")
        if remove_role is not None and not role_assignable(guild, remove_role):
            raise ValueError("Az eltávolítandó rangot Yoru nem tudja kezelni.")

        old = await self.db.get_verification_panel(guild.id)
        if old and old["message_id"]:
            old_channel = guild.get_channel(old["channel_id"])
            if isinstance(old_channel, discord.TextChannel):
                try:
                    old_message = await old_channel.fetch_message(old["message_id"])
                    await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        await self.db.upsert_verification_panel(
            guild.id,
            channel.id,
            role.id,
            remove_role.id if remove_role else None,
            title[:256],
            body[:4000],
            button_label[:80],
            message_id=None,
            active=True,
        )
        embed = base_embed(title[:256], body[:4000], SUCCESS)
        embed.add_field(name="Mit kapsz?", value=role.mention, inline=False)
        embed.set_footer(text="Yoru • Verification")
        view = VerificationView(self, guild.id, button_label)
        message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        await self.db.set_verification_message(guild.id, message.id)
        return message.id

    async def deactivate_verification_panel(self, guild: discord.Guild, *, delete_message: bool = True) -> bool:
        panel = await self.db.get_verification_panel(guild.id)
        if panel is None:
            return False
        changed = await self.db.deactivate_verification_panel(guild.id)
        if delete_message and panel["message_id"]:
            channel = guild.get_channel(panel["channel_id"])
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(panel["message_id"])
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        return changed

    async def _send_welcome(self, member: discord.Member) -> None:
        if not await self.settings.get_welcome_enabled(member.guild.id):
            return
        channel_id = await self.settings.get_welcome_channel_id(member.guild.id)
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        templates = await self.settings.get_welcome_templates(member.guild.id)
        random_enabled = await self.settings.get_welcome_random(member.guild.id)
        template = random.choice(templates) if random_enabled and len(templates) > 1 else templates[0]
        text = render_member_template(template, member)
        try:
            if await self.settings.get_welcome_embed(member.guild.id):
                title = render_member_template(await self.settings.get_welcome_title(member.guild.id), member)
                embed = base_embed(title, text, SUCCESS)
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"Yoru • Welcome • {member.guild.name}")
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False))
            else:
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False))
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _send_welcome_dm(self, member: discord.Member) -> None:
        if not await self.settings.get_welcome_dm_enabled(member.guild.id):
            return
        text = render_member_template(await self.settings.get_welcome_dm_template(member.guild.id), member)
        try:
            await member.send(text)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _send_goodbye(self, member: discord.Member) -> None:
        if not await self.settings.get_goodbye_enabled(member.guild.id):
            return
        channel_id = await self.settings.get_goodbye_channel_id(member.guild.id)
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        text = render_member_template(await self.settings.get_goodbye_template(member.guild.id), member)
        try:
            if await self.settings.get_goodbye_embed(member.guild.id):
                title = render_member_template(await self.settings.get_goodbye_title(member.guild.id), member)
                embed = base_embed(title, text)
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"Yoru • Goodbye • {member.guild.name}")
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            else:
                await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _apply_join_roles(self, member: discord.Member) -> None:
        guild = member.guild
        ids = await (self.settings.get_bot_autoroles(guild.id) if member.bot else self.settings.get_human_autoroles(guild.id))
        roles: list[discord.Role] = []
        for role_id in ids:
            role = guild.get_role(role_id)
            if role_assignable(guild, role):
                roles.append(role)

        if await self.settings.get_role_restore_enabled(guild.id):
            raw = await self.db.pop_member_role_snapshot(guild.id, member.id)
            if raw:
                for token in raw.split(","):
                    try:
                        role_id = int(token)
                    except ValueError:
                        continue
                    role = guild.get_role(role_id)
                    if role_assignable(guild, role) and role not in roles:
                        roles.append(role)

        if roles:
            try:
                await member.add_roles(*roles, reason="Yoru autorole / role restore")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._apply_join_roles(member)
        if not member.bot:
            await self._send_welcome(member)
            await self._send_welcome_dm(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if await self.settings.get_role_restore_enabled(member.guild.id):
            role_ids = [
                str(role.id)
                for role in member.roles
                if role_assignable(member.guild, role, public_safe=True)
            ][:50]
            await self.db.save_member_role_snapshot(member.guild.id, member.id, ",".join(role_ids))
        if not member.bot:
            await self._send_goodbye(member)
