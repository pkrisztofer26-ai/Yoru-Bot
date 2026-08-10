from __future__ import annotations

import asyncio
import io
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from app.amounts import parse_amount
from app.database import Database
from app.services.server_settings import ServerSettingsService
from app import moderation_config as modcfg
from app.ui import BRAND, DANGER, GOLD, SUCCESS, action_embed, base_embed, money


_DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)


@dataclass
class CachedAttachment:
    filename: str
    size: int
    content_type: str | None
    data: bytes | None


@dataclass
class CachedMessageSnapshot:
    guild_id: int
    channel_id: int
    author_id: int
    author_name: str
    content: str
    cached_at: float
    attachments: list[CachedAttachment]


def parse_duration(value: str) -> timedelta:
    value = value.strip().lower()
    match = _DURATION_RE.fullmatch(value)
    if not match:
        raise ValueError("Időtartam példa: `10m`, `2h`, `1d`, `1w`.")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ValueError("Az időtartam legyen nagyobb 0-nál.")
    seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit] * amount
    duration = timedelta(seconds=seconds)
    if duration > timedelta(days=28):
        raise ValueError("A Discord timeout maximum 28 nap lehet.")
    return duration


def clean_reason(reason: str | None) -> str:
    reason = (reason or "Nincs megadva").strip()
    return reason[:500] if reason else "Nincs megadva"


class ModerationCog(commands.GroupCog, group_name="mod", group_description="Yoru moderáció, logok és szerver admin eszközök."):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.settings = ServerSettingsService(db)
        self._external_audit_suppress: dict[tuple[int, int, str], float] = {}
        self._message_snapshots: OrderedDict[int, CachedMessageSnapshot] = OrderedDict()
        self._attachment_cache_bytes = 0
        self._handled_delete_ids: dict[int, float] = {}

    async def _log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        channel_id = await self.settings.get_log_channel_id(guild.id)
        if channel_id is None:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _log_enabled(self, guild_id: int, key: str) -> bool:
        return await self.settings.get_log_enabled(guild_id, key)

    async def _send_log(
        self,
        guild: discord.Guild,
        title: str,
        *,
        description: str | None = None,
        color: discord.Color = BRAND,
        fields: list[tuple[str, str, bool]] | None = None,
        files: list[discord.File] | None = None,
        log_key: str = "moderation_actions",
    ) -> None:
        if not await self._log_enabled(guild.id, log_key):
            return
        channel = await self._log_channel(guild)
        if channel is None:
            return
        embed = base_embed(title, description, color)
        embed.set_footer(text="Yoru • Moderációs napló")
        for name, value, inline in fields or []:
            embed.add_field(name=name, value=value, inline=inline)
        try:
            if files:
                await channel.send(embed=embed, files=files)
            else:
                await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    def _assert_target(self, actor: discord.Member, target: discord.Member) -> None:
        if actor.id == target.id:
            raise ValueError("Saját magadon nem használhatod ezt a parancsot.")
        if target.id == actor.guild.owner_id:
            raise ValueError("A szerver tulajdonosán nem használható ez a parancs.")
        if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
            raise ValueError("A célpont rangja azonos vagy magasabb a tiednél.")
        me = actor.guild.me
        if me and target.top_role >= me.top_role:
            raise ValueError("A Yoru rangját a célpont rangja fölé kell helyezned.")

    async def _case(self, guild: discord.Guild, action: str, target_id: int, moderator_id: int, reason: str) -> int:
        return await self.db.add_mod_case(guild.id, action, target_id, moderator_id, reason)

    def suppress_external_audit(self, guild_id: int, target_id: int, action: str, seconds: float = 6.0) -> None:
        self._external_audit_suppress[(guild_id, target_id, action)] = time.monotonic() + seconds

    def _audit_suppressed(self, guild_id: int, target_id: int, action: str, *, consume: bool = True) -> bool:
        key = (guild_id, target_id, action)
        until = self._external_audit_suppress.get(key, 0.0)
        if until <= time.monotonic():
            self._external_audit_suppress.pop(key, None)
            return False
        if consume:
            self._external_audit_suppress.pop(key, None)
        return True

    async def _audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        *,
        channel_id: int | None = None,
        settle: bool = True,
    ) -> discord.AuditLogEntry | None:
        me = guild.me
        if me is None or not me.guild_permissions.view_audit_log:
            return None
        if settle:
            await asyncio.sleep(modcfg.AUDIT_SETTLE_SECONDS)
        now = datetime.now(timezone.utc)
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                age = abs((now - entry.created_at).total_seconds())
                if age > modcfg.AUDIT_LOOKBACK_SECONDS:
                    continue
                target = getattr(entry, "target", None)
                if getattr(target, "id", None) != target_id:
                    continue
                if channel_id is not None:
                    extra = getattr(entry, "extra", None)
                    audit_channel = getattr(extra, "channel", None)
                    if audit_channel is not None and getattr(audit_channel, "id", None) != channel_id:
                        continue
                return entry
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    @staticmethod
    def _actor_text(entry: discord.AuditLogEntry | None) -> tuple[int, str, str]:
        if entry is None:
            return 0, "Ismeretlen / önmaga", "Nincs megadva"
        actor = getattr(entry, "user", None)
        actor_id = int(getattr(actor, "id", 0) or 0)
        actor_text = f"{actor} (`{actor_id}`)" if actor is not None else "Ismeretlen"
        return actor_id, actor_text, clean_reason(getattr(entry, "reason", None))

    async def _result(
        self,
        destination,
        moderator: discord.abc.User,
        title: str,
        target_text: str,
        reason: str,
        *,
        case_id: int | None = None,
        extra: str | None = None,
        ephemeral: bool = False,
    ) -> None:
        embed = action_embed(title, moderator, color=SUCCESS, footer="Yoru • Moderáció")
        embed.add_field(name="👤 Felhasználó", value=target_text, inline=True)
        if case_id is not None:
            embed.add_field(name="🧾 Eset", value=f"`#{case_id}`", inline=True)
        if extra:
            embed.add_field(name="ℹ️ Részletek", value=extra, inline=False)
        embed.add_field(name="📝 Indok", value=reason, inline=False)
        if isinstance(destination, discord.Interaction):
            if destination.response.is_done():
                await destination.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await destination.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            await destination.send(embed=embed)

    # ---------- config ----------
    @app_commands.command(name="setlogchannel", description="Beállítja a Yoru moderációs log csatornáját.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            return
        await self.settings.set_log_channel_id(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ Moderációs log csatorna: {channel.mention}", ephemeral=True)

    @commands.command(name="setlogchannel", aliases=["setlog", "logchannel"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setlogchannel_prefix(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        await self.settings.set_log_channel_id(ctx.guild.id, channel.id)
        await ctx.send(f"✅ Moderációs log csatorna: {channel.mention}")

    @app_commands.command(name="disablelogs", description="Kikapcsolja a Yoru moderációs logolást.")
    @app_commands.checks.has_permissions(administrator=True)
    async def disablelogs_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await self.settings.set_log_channel_id(interaction.guild.id, None)
        await interaction.response.send_message("✅ Moderációs logolás kikapcsolva.", ephemeral=True)

    @commands.command(name="disablelogs", aliases=["logoff"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def disablelogs_prefix(self, ctx: commands.Context) -> None:
        await self.settings.set_log_channel_id(ctx.guild.id, None)
        await ctx.send("✅ Moderációs logolás kikapcsolva.")

    # ---------- ban / kick ----------
    async def _ban(self, guild: discord.Guild, moderator: discord.Member, target: discord.Member, reason: str) -> int:
        self._assert_target(moderator, target)
        reason = clean_reason(reason)
        self.suppress_external_audit(guild.id, target.id, "ban")
        await target.ban(reason=f"{reason} | Yoru moderator: {moderator}")
        case = await self._case(guild, "ban", target.id, moderator.id, reason)
        await self._send_log(guild, "🔨 Kitiltás", color=DANGER, log_key="ban_kick", fields=[
            ("👤 Felhasználó", f"{target} (`{target.id}`)", True),
            ("🛡️ Moderátor", f"{moderator} (`{moderator.id}`)", True),
            ("🧾 Eset", f"#{case}", True),
            ("📝 Indok", reason, False),
        ])
        return case

    @app_commands.command(name="ban", description="Kitilt egy felhasználót a szerverről.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nincs megadva") -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        try:
            case = await self._ban(interaction.guild, interaction.user, member, reason)
            await self._result(interaction, interaction.user, "🔨 Kitiltás", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case)
        except (ValueError, discord.Forbidden) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    @commands.guild_only()
    async def ban_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Nincs megadva") -> None:
        try:
            case = await self._ban(ctx.guild, ctx.author, member, reason)
            await self._result(ctx, ctx.author, "🔨 Kitiltás", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case)
        except (ValueError, discord.Forbidden) as exc:
            await ctx.send(f"❌ {exc}")

    @app_commands.command(name="unban", description="Felold egy kitiltást felhasználói ID alapján.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_slash(self, interaction: discord.Interaction, user_id: str, reason: str = "Nincs megadva") -> None:
        if interaction.guild is None or not user_id.isdigit():
            return await interaction.response.send_message("❌ Adj meg egy érvényes Discord user ID-t.", ephemeral=True)
        user = discord.Object(id=int(user_id))
        try:
            self.suppress_external_audit(interaction.guild.id, int(user_id), "unban")
            await interaction.guild.unban(user, reason=clean_reason(reason))
        except discord.NotFound:
            return await interaction.response.send_message("❌ Ez a felhasználó nincs kitiltva.", ephemeral=True)
        case = await self._case(interaction.guild, "unban", int(user_id), interaction.user.id, clean_reason(reason))
        await self._send_log(interaction.guild, "🔓 Kitiltás feloldva", color=SUCCESS, log_key="ban_kick", fields=[("👤 User ID", f"`{user_id}`", True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", clean_reason(reason), False)])
        await self._result(interaction, interaction.user, "🔓 Kitiltás feloldva", f"`{user_id}`", clean_reason(reason), case_id=case)

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    @commands.guild_only()
    async def unban_prefix(self, ctx: commands.Context, user_id: int, *, reason: str = "Nincs megadva") -> None:
        try:
            self.suppress_external_audit(ctx.guild.id, user_id, "unban")
            await ctx.guild.unban(discord.Object(id=user_id), reason=clean_reason(reason))
        except discord.NotFound:
            return await ctx.send("❌ Ez a felhasználó nincs kitiltva.")
        case = await self._case(ctx.guild, "unban", user_id, ctx.author.id, clean_reason(reason))
        await self._send_log(ctx.guild, "🔓 Kitiltás feloldva", color=SUCCESS, log_key="ban_kick", fields=[("👤 User ID", f"`{user_id}`", True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", clean_reason(reason), False)])
        await self._result(ctx, ctx.author, "🔓 Kitiltás feloldva", f"`{user_id}`", clean_reason(reason), case_id=case)

    async def _kick(self, guild: discord.Guild, moderator: discord.Member, target: discord.Member, reason: str) -> int:
        self._assert_target(moderator, target)
        reason = clean_reason(reason)
        self.suppress_external_audit(guild.id, target.id, "kick")
        await target.kick(reason=f"{reason} | Yoru moderator: {moderator}")
        case = await self._case(guild, "kick", target.id, moderator.id, reason)
        await self._send_log(guild, "👢 Kirúgás", color=GOLD, log_key="ban_kick", fields=[("👤 Felhasználó", f"{target} (`{target.id}`)", True), ("🛡️ Moderátor", str(moderator), True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", reason, False)])
        return case

    @app_commands.command(name="kick", description="Kirúg egy felhasználót a szerverről.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nincs megadva") -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        try:
            case = await self._kick(interaction.guild, interaction.user, member, reason)
            await self._result(interaction, interaction.user, "👢 Kirúgás", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case)
        except (ValueError, discord.Forbidden) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    @commands.guild_only()
    async def kick_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Nincs megadva") -> None:
        try:
            case = await self._kick(ctx.guild, ctx.author, member, reason)
            await self._result(ctx, ctx.author, "👢 Kirúgás", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case)
        except (ValueError, discord.Forbidden) as exc:
            await ctx.send(f"❌ {exc}")

    # ---------- timeout / mute ----------
    async def _mute(self, guild: discord.Guild, moderator: discord.Member, target: discord.Member, duration_text: str, reason: str) -> tuple[int, datetime]:
        self._assert_target(moderator, target)
        duration = parse_duration(duration_text)
        until = datetime.now(timezone.utc) + duration
        reason = clean_reason(reason)
        self.suppress_external_audit(guild.id, target.id, "timeout")
        await target.timeout(until, reason=f"{reason} | Yoru moderator: {moderator}")
        case = await self._case(guild, "mute", target.id, moderator.id, f"{duration_text} | {reason}")
        await self._send_log(guild, "🔇 Némítás", color=GOLD, log_key="timeout", fields=[("👤 Felhasználó", f"{target} (`{target.id}`)", True), ("⏱️ Időtartam", duration_text, True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", reason, False)])
        return case, until

    @app_commands.command(name="mute", description="Ideiglenesen lenémít egy felhasználót Discord timeouttal.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_slash(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Nincs megadva") -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        try:
            case, until = await self._mute(interaction.guild, interaction.user, member, duration, reason)
            await self._result(interaction, interaction.user, "🔇 Némítás", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case, extra=f"{duration} • vége: <t:{int(until.timestamp())}:R>")
        except (ValueError, discord.Forbidden) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

    @commands.command(name="mute", aliases=["timeout", "to"])
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def mute_prefix(self, ctx: commands.Context, member: discord.Member, duration: str, *, reason: str = "Nincs megadva") -> None:
        try:
            case, until = await self._mute(ctx.guild, ctx.author, member, duration, reason)
            await self._result(ctx, ctx.author, "🔇 Némítás", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case, extra=f"{duration} • vége: <t:{int(until.timestamp())}:R>")
        except (ValueError, discord.Forbidden) as exc:
            await ctx.send(f"❌ {exc}")

    async def _unmute(self, guild: discord.Guild, moderator: discord.Member, target: discord.Member, reason: str) -> int:
        self._assert_target(moderator, target)
        reason = clean_reason(reason)
        self.suppress_external_audit(guild.id, target.id, "timeout")
        await target.timeout(None, reason=f"{reason} | Yoru moderator: {moderator}")
        case = await self._case(guild, "unmute", target.id, moderator.id, reason)
        await self._send_log(guild, "🔊 Némítás feloldva", color=SUCCESS, log_key="timeout", fields=[("👤 Felhasználó", f"{target} (`{target.id}`)", True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", reason, False)])
        return case

    @app_commands.command(name="unmute", description="Feloldja egy felhasználó némítását.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nincs megadva") -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        try:
            case = await self._unmute(interaction.guild, interaction.user, member, reason)
            await self._result(interaction, interaction.user, "🔊 Némítás feloldva", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case)
        except (ValueError, discord.Forbidden) as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

    @commands.command(name="unmute", aliases=["untimeout", "uto"])
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def unmute_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Nincs megadva") -> None:
        try:
            case = await self._unmute(ctx.guild, ctx.author, member, reason)
            await self._result(ctx, ctx.author, "🔊 Némítás feloldva", f"{member} (`{member.id}`)", clean_reason(reason), case_id=case)
        except (ValueError, discord.Forbidden) as exc:
            await ctx.send(f"❌ {exc}")

    # ---------- warnings ----------
    async def _warn(self, guild: discord.Guild, moderator: discord.Member, target: discord.Member, reason: str) -> tuple[int, int]:
        self._assert_target(moderator, target)
        reason = clean_reason(reason)
        warning_id = await self.db.add_warning(guild.id, target.id, moderator.id, reason)
        case = await self._case(guild, "warn", target.id, moderator.id, reason)
        count = await self.db.warning_count(guild.id, target.id)
        await self._send_log(guild, "⚠️ Figyelmeztetés", color=GOLD, fields=[("👤 Felhasználó", f"{target} (`{target.id}`)", True), ("⚠️ Warningok", str(count), True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", reason, False)])
        return warning_id, count

    @app_commands.command(name="warn", description="Figyelmeztet egy felhasználót.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        try:
            warning_id, count = await self._warn(interaction.guild, interaction.user, member, reason)
            await self._result(interaction, interaction.user, "⚠️ Figyelmeztetés", f"{member} (`{member.id}`)", clean_reason(reason), extra=f"Warning `#{warning_id}` • összesen **{count}**")
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def warn_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str) -> None:
        try:
            warning_id, count = await self._warn(ctx.guild, ctx.author, member, reason)
            await self._result(ctx, ctx.author, "⚠️ Figyelmeztetés", f"{member} (`{member.id}`)", clean_reason(reason), extra=f"Warning `#{warning_id}` • összesen **{count}**")
        except ValueError as exc:
            await ctx.send(f"❌ {exc}")

    async def _warnings_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        rows = await self.db.get_warnings(guild.id, member.id, 15)
        embed = base_embed(f"⚠️ Figyelmeztetések • {member.display_name}")
        embed.set_thumbnail(url=member.display_avatar.url)
        if not rows:
            embed.description = "Nincs aktív figyelmeztetése."
        else:
            lines = []
            for warning_id, moderator_id, reason, created_at in rows:
                stamp = int(datetime.fromisoformat(created_at).timestamp())
                lines.append(f"**#{warning_id}** • <@{moderator_id}> • <t:{stamp}:d>\n{reason}")
            embed.description = "\n\n".join(lines)
        embed.set_footer(text="Yoru • Moderáció")
        return embed

    @app_commands.command(name="warnings", description="Megmutatja egy felhasználó figyelmeztetéseit.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild is None:
            return
        await interaction.response.send_message(embed=await self._warnings_embed(interaction.guild, member), ephemeral=True)

    @commands.command(name="warnings", aliases=["warns"])
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def warnings_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        await ctx.send(embed=await self._warnings_embed(ctx.guild, member))

    @app_commands.command(name="clearwarns", description="Törli egy felhasználó összes figyelmeztetését.")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearwarns_slash(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild is None:
            return
        count = await self.db.clear_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ {member.display_name}: **{count}** warning törölve.", ephemeral=True)

    @commands.command(name="clearwarns", aliases=["cw"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def clearwarns_prefix(self, ctx: commands.Context, member: discord.Member) -> None:
        count = await self.db.clear_warnings(ctx.guild.id, member.id)
        await ctx.send(f"✅ {member.display_name}: **{count}** warning törölve.")

    # ---------- channel tools ----------
    async def _suppress_bulk_delete_candidates(self, channel: discord.TextChannel, amount: int) -> list[int]:
        ids: list[int] = []
        try:
            async for msg in channel.history(limit=amount):
                ids.append(msg.id)
        except (discord.Forbidden, discord.HTTPException):
            return ids
        suppressed = getattr(self.bot, "_suppressed_delete_log_ids", None)
        if isinstance(suppressed, set):
            suppressed.update(ids)

            async def cleanup() -> None:
                await asyncio.sleep(8)
                for message_id in ids:
                    suppressed.discard(message_id)

            asyncio.create_task(cleanup())
        return ids

    @app_commands.command(name="purge", description="Üzenetek tömeges törlése az aktuális csatornából.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_slash(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer(ephemeral=True)
        await self._suppress_bulk_delete_candidates(interaction.channel, int(amount))
        deleted = await interaction.channel.purge(limit=int(amount))
        await self._send_log(interaction.guild, "🧹 Tömeges törlés", color=GOLD, fields=[
            ("🛡️ Moderátor", f"{interaction.user} (`{interaction.user.id}`)", True),
            ("📍 Csatorna", interaction.channel.mention, True),
            ("🗑️ Törölve", str(len(deleted)), True),
        ])
        await interaction.followup.send(f"🧹 **{len(deleted)}** üzenet törölve.", ephemeral=True)

    @commands.command(name="purge", aliases=["clear", "clean"])
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def purge_prefix(self, ctx: commands.Context, amount: int) -> None:
        if amount < 1 or amount > 500:
            return await ctx.send("❌ 1 és 500 közötti számot adj meg.")
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        await self._suppress_bulk_delete_candidates(ctx.channel, amount)
        deleted = await ctx.channel.purge(limit=amount)
        await self._send_log(ctx.guild, "🧹 Tömeges törlés", color=GOLD, fields=[
            ("🛡️ Moderátor", f"{ctx.author} (`{ctx.author.id}`)", True),
            ("📍 Csatorna", ctx.channel.mention, True),
            ("🗑️ Törölve", str(len(deleted)), True),
        ])
        await ctx.send(f"🧹 **{len(deleted)}** üzenet törölve.", delete_after=4)

    async def _lock(self, channel: discord.TextChannel, locked: bool) -> None:
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = False if locked else None
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite, reason="Yoru channel lock")

    @app_commands.command(name="lock", description="Lezárja az aktuális szöveges csatornát.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_slash(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        await self._lock(interaction.channel, True)
        await interaction.response.send_message("🔒 Csatorna lezárva.")

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock_prefix(self, ctx: commands.Context) -> None:
        if isinstance(ctx.channel, discord.TextChannel):
            await self._lock(ctx.channel, True)
            await ctx.send("🔒 Csatorna lezárva.")

    @app_commands.command(name="unlock", description="Feloldja az aktuális szöveges csatornát.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock_slash(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        await self._lock(interaction.channel, False)
        await interaction.response.send_message("🔓 Csatorna feloldva.")

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock_prefix(self, ctx: commands.Context) -> None:
        if isinstance(ctx.channel, discord.TextChannel):
            await self._lock(ctx.channel, False)
            await ctx.send("🔓 Csatorna feloldva.")

    @app_commands.command(name="slowmode", description="Beállítja az aktuális csatorna lassított módját másodpercben.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_slash(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.channel.edit(slowmode_delay=int(seconds), reason=f"Yoru: {interaction.user}")
        await interaction.response.send_message(f"🐢 Slowmode: **{seconds} mp**.")

    @commands.command(name="slowmode", aliases=["slow"])
    @commands.has_permissions(manage_channels=True)
    async def slowmode_prefix(self, ctx: commands.Context, seconds: int) -> None:
        if not 0 <= seconds <= 21600:
            return await ctx.send("❌ Slowmode: 0–21600 másodperc.")
        if isinstance(ctx.channel, discord.TextChannel):
            await ctx.channel.edit(slowmode_delay=seconds, reason=f"Yoru: {ctx.author}")
            await ctx.send(f"🐢 Slowmode: **{seconds} mp**.")

    # ---------- admin pay ----------
    async def _adminpay(self, guild_id: int, target_id: int, amount_text: str, admin_id: int) -> int:
        wallet, _ = await self.db.get_balance(guild_id, target_id)
        amount = parse_amount(amount_text)
        if amount <= 0:
            raise ValueError("Az összeg legyen pozitív.")
        return await self.db.add_wallet(guild_id, target_id, amount, f"adminpay:{admin_id}")

    @app_commands.command(name="adminpay", description="Adminisztrátorként pénzt ad egy felhasználónak.")
    @app_commands.checks.has_permissions(administrator=True)
    async def adminpay_slash(self, interaction: discord.Interaction, member: discord.Member, amount: str, reason: str = "Admin kifizetés") -> None:
        if interaction.guild is None:
            return
        try:
            wallet = await self._adminpay(interaction.guild.id, member.id, amount, interaction.user.id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        case = await self._case(interaction.guild, "adminpay", member.id, interaction.user.id, f"{amount} | {clean_reason(reason)}")
        await self._send_log(interaction.guild, "💸 Admin kifizetés", color=SUCCESS, fields=[("👤 Felhasználó", f"{member} (`{member.id}`)", True), ("💰 Új tárca", money(wallet), True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", clean_reason(reason), False)])
        await interaction.response.send_message(f"✅ {member.display_name} új tárcája: **{money(wallet)}**.", ephemeral=True)

    @commands.command(name="adminpay", aliases=["apay"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def adminpay_prefix(self, ctx: commands.Context, member: discord.Member, amount: str, *, reason: str = "Admin kifizetés") -> None:
        try:
            wallet = await self._adminpay(ctx.guild.id, member.id, amount, ctx.author.id)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        case = await self._case(ctx.guild, "adminpay", member.id, ctx.author.id, f"{amount} | {clean_reason(reason)}")
        await self._send_log(ctx.guild, "💸 Admin kifizetés", color=SUCCESS, fields=[("👤 Felhasználó", f"{member} (`{member.id}`)", True), ("💰 Új tárca", money(wallet), True), ("🧾 Eset", f"#{case}", True), ("📝 Indok", clean_reason(reason), False)])
        await ctx.send(f"✅ {member.display_name} új tárcája: **{money(wallet)}**.")

    # ---------- info / cases ----------
    @app_commands.command(name="modlog", description="Megmutatja a legutóbbi moderációs eseteket.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def modlog_slash(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild is None:
            return
        await interaction.response.send_message(embed=await self._modlog_embed(interaction.guild, member), ephemeral=True)

    @commands.command(name="modlog", aliases=["cases", "mlog"])
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def modlog_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await ctx.send(embed=await self._modlog_embed(ctx.guild, member))

    async def _modlog_embed(self, guild: discord.Guild, member: discord.Member | None) -> discord.Embed:
        rows = await self.db.get_mod_cases(guild.id, member.id if member else None, 15)
        title = f"🧾 Moderációs esetek • {member.display_name}" if member else "🧾 Legutóbbi moderációs esetek"
        embed = base_embed(title)
        if not rows:
            embed.description = "Nincs találat."
        else:
            lines = []
            for case_id, action, target_id, moderator_id, reason, created_at in rows:
                stamp = int(datetime.fromisoformat(created_at).timestamp())
                moderator_text = f"<@{moderator_id}>" if moderator_id else "Ismeretlen"
                lines.append(f"**#{case_id} • {action.upper()}** • <@{target_id}> • {moderator_text} • <t:{stamp}:R>\n{reason}")
            embed.description = "\n\n".join(lines)
        embed.set_footer(text="Yoru • Moderáció")
        return embed

    async def _case_embed(self, guild: discord.Guild, case_id: int) -> discord.Embed:
        row = await self.db.get_mod_case(guild.id, case_id)
        if row is None:
            return base_embed("🧾 Moderációs eset", "❌ Nincs ilyen eset ezen a szerveren.", DANGER)
        cid, action, target_id, moderator_id, reason, created_at = row
        stamp = int(datetime.fromisoformat(created_at).timestamp())
        moderator = f"<@{moderator_id}> (`{moderator_id}`)" if moderator_id else "Ismeretlen / Discord audit nem elérhető"
        embed = base_embed(f"🧾 Eset #{cid}")
        embed.add_field(name="⚙️ Művelet", value=action, inline=True)
        embed.add_field(name="👤 Célpont", value=f"<@{target_id}> (`{target_id}`)", inline=True)
        embed.add_field(name="🛡️ Moderátor", value=moderator, inline=False)
        embed.add_field(name="📝 Indok", value=reason or "Nincs megadva", inline=False)
        embed.add_field(name="🕒 Idő", value=f"<t:{stamp}:F> • <t:{stamp}:R>", inline=False)
        embed.set_footer(text="Yoru • Moderáció")
        return embed

    @app_commands.command(name="case", description="Megmutat egy moderációs esetet az ID alapján.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def case_slash(self, interaction: discord.Interaction, case_id: int) -> None:
        if interaction.guild:
            await interaction.response.send_message(embed=await self._case_embed(interaction.guild, case_id), ephemeral=True)

    @commands.command(name="case")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def case_prefix(self, ctx: commands.Context, case_id: int) -> None:
        await ctx.send(embed=await self._case_embed(ctx.guild, case_id))

    async def _modstatus_embed(self, guild: discord.Guild) -> discord.Embed:
        channel = await self._log_channel(guild)
        me = guild.me
        perms = me.guild_permissions if me else None
        voice_enabled = await self._log_enabled(guild.id, "voice")
        embed = base_embed("🛡️ Moderációs státusz")
        embed.add_field(name="📋 Log csatorna", value=channel.mention if channel else "Nincs beállítva", inline=False)
        if perms is not None:
            checks = [
                ("Audit Log", perms.view_audit_log),
                ("Üzenetek kezelése", perms.manage_messages),
                ("Tagok moderálása", perms.moderate_members),
                ("Ban", perms.ban_members),
                ("Kick", perms.kick_members),
            ]
            embed.add_field(
                name="🔐 Yoru jogosultságok",
                value="\n".join(f"{'✅' if ok else '❌'} {label}" for label, ok in checks),
                inline=False,
            )
        embed.add_field(name="🖼️ Törölt attachment cache", value=f"≤ {modcfg.ATTACHMENT_CACHE_FILE_MAX_BYTES // 1024 // 1024} MB / fájl • {modcfg.ATTACHMENT_CACHE_TTL_SECONDS // 60} perc", inline=True)
        embed.add_field(name="🔊 Voice log", value="ON" if voice_enabled else "OFF", inline=True)
        embed.set_footer(text="Yoru • Moderáció • A kézi Discord büntetésekhez View Audit Log kell")
        return embed

    @app_commands.command(name="modstatus", description="Moderációs log és permission állapot.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def modstatus_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild:
            await interaction.response.send_message(embed=await self._modstatus_embed(interaction.guild), ephemeral=True)

    @commands.command(name="modstatus")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def modstatus_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await self._modstatus_embed(ctx.guild))

    @app_commands.command(name="logvoice", description="Voice join/leave/move modlog ki-/bekapcsolása.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logvoice_slash(self, interaction: discord.Interaction, enabled: bool) -> None:
        if interaction.guild is None:
            return
        await self.settings.set_log_enabled(interaction.guild.id, "voice", enabled)
        await interaction.response.send_message(f"✅ Voice log: **{'ON' if enabled else 'OFF'}**.", ephemeral=True)

    @commands.command(name="logvoice")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def logvoice_prefix(self, ctx: commands.Context, state: str) -> None:
        value = state.lower() in {"on", "1", "true", "be", "igen"}
        if state.lower() not in {"on", "off", "1", "0", "true", "false", "be", "ki", "igen", "nem"}:
            return await ctx.send("❌ Használat: `!logvoice on` vagy `!logvoice off`.")
        await self.settings.set_log_enabled(ctx.guild.id, "voice", value)
        await ctx.send(f"✅ Voice log: **{'ON' if value else 'OFF'}**.")

    @app_commands.command(name="userinfo", description="Információk egy szervertagról.")
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild is None:
            return
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            return
        await interaction.response.send_message(embed=self._userinfo_embed(target))

    @commands.command(name="userinfo", aliases=["ui", "whois"])
    @commands.guild_only()
    async def userinfo_prefix(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        await ctx.send(embed=self._userinfo_embed(member or ctx.author))

    def _userinfo_embed(self, member: discord.Member) -> discord.Embed:
        embed = base_embed(f"👤 {member.display_name}")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="🤖 Bot", value="Igen" if member.bot else "Nem", inline=True)
        embed.add_field(name="📅 Fiók létrehozva", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        if member.joined_at:
            embed.add_field(name="📥 Csatlakozott", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
        embed.add_field(name="🏷️ Legmagasabb rang", value=member.top_role.mention, inline=True)
        embed.add_field(name="🔇 Timeout", value=(f"<t:{int(member.timed_out_until.timestamp())}:R>" if member.timed_out_until else "Nincs"), inline=True)
        embed.set_footer(text="Yoru • Utility")
        return embed

    @app_commands.command(name="serverinfo", description="Információk a szerverről.")
    async def serverinfo_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild:
            await interaction.response.send_message(embed=self._serverinfo_embed(interaction.guild))

    @commands.command(name="serverinfo", aliases=["si"])
    @commands.guild_only()
    async def serverinfo_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=self._serverinfo_embed(ctx.guild))

    def _serverinfo_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = base_embed(f"🏠 {guild.name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="🆔 ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="👥 Tagok", value=str(guild.member_count or 0), inline=True)
        embed.add_field(name="💬 Csatornák", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="🎭 Rangok", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="👑 Tulajdonos", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(name="📅 Létrehozva", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=True)
        embed.set_footer(text="Yoru • Utility")
        return embed

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "⛔ Nincs jogosultságod ehhez a moderációs parancshoz."
        elif isinstance(error, app_commands.BotMissingPermissions):
            message = "❌ A Yoru botnak nincs meg a szükséges Discord jogosultsága ehhez a művelethez."
        else:
            raise error
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ---------- automatic audit logs ----------
    def _prune_message_cache(self) -> None:
        now = time.monotonic()
        while self._message_snapshots:
            message_id, snap = next(iter(self._message_snapshots.items()))
            if (
                now - snap.cached_at <= modcfg.ATTACHMENT_CACHE_TTL_SECONDS
                and len(self._message_snapshots) <= modcfg.ATTACHMENT_CACHE_MAX_MESSAGES
                and self._attachment_cache_bytes <= modcfg.ATTACHMENT_CACHE_TOTAL_MAX_BYTES
            ):
                break
            self._message_snapshots.pop(message_id, None)
            self._attachment_cache_bytes -= sum(len(a.data) for a in snap.attachments if a.data is not None)

        for message_id, stamp in list(self._handled_delete_ids.items()):
            if now - stamp > 60:
                self._handled_delete_ids.pop(message_id, None)

    async def _cache_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        if not await self._log_enabled(message.guild.id, "message_delete"):
            return
        self._prune_message_cache()
        cached_attachments: list[CachedAttachment] = []
        attachment_logging = await self._log_enabled(message.guild.id, "deleted_attachments")
        should_read_files = (
            attachment_logging
            and bool(message.attachments)
            and await self._log_channel(message.guild) is not None
        )
        for attachment in (message.attachments[:8] if attachment_logging else []):
            data: bytes | None = None
            if should_read_files and attachment.size <= modcfg.ATTACHMENT_CACHE_FILE_MAX_BYTES:
                if self._attachment_cache_bytes + attachment.size <= modcfg.ATTACHMENT_CACHE_TOTAL_MAX_BYTES:
                    try:
                        data = await attachment.read()
                    except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                        data = None
            if data is not None:
                self._attachment_cache_bytes += len(data)
            cached_attachments.append(
                CachedAttachment(
                    filename=attachment.filename,
                    size=attachment.size,
                    content_type=attachment.content_type,
                    data=data,
                )
            )
        old = self._message_snapshots.pop(message.id, None)
        if old:
            self._attachment_cache_bytes -= sum(len(a.data) for a in old.attachments if a.data is not None)
        self._message_snapshots[message.id] = CachedMessageSnapshot(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=str(message.author),
            content=message.content or "",
            cached_at=time.monotonic(),
            attachments=cached_attachments,
        )
        self._prune_message_cache()

    def _pop_snapshot(self, message_id: int) -> CachedMessageSnapshot | None:
        snap = self._message_snapshots.pop(message_id, None)
        if snap:
            self._attachment_cache_bytes -= sum(len(a.data) for a in snap.attachments if a.data is not None)
        return snap

    @staticmethod
    def _files_from_snapshot(snapshot: CachedMessageSnapshot | None) -> list[discord.File]:
        if snapshot is None:
            return []
        result: list[discord.File] = []
        for attachment in snapshot.attachments:
            if attachment.data is None:
                continue
            try:
                result.append(discord.File(io.BytesIO(attachment.data), filename=attachment.filename))
            except Exception:
                continue
        return result

    async def _deleted_message_log(
        self,
        guild: discord.Guild,
        *,
        message_id: int,
        channel_id: int,
        author_id: int | None,
        author_text: str,
        content: str,
        snapshot: CachedMessageSnapshot | None,
    ) -> None:
        entry: discord.AuditLogEntry | None = None
        if author_id:
            entry = await self._audit_entry(
                guild,
                discord.AuditLogAction.message_delete,
                author_id,
                channel_id=channel_id,
            )
        _actor_id, actor_text, _reason = self._actor_text(entry)
        channel = guild.get_channel(channel_id)
        channel_text = channel.mention if isinstance(channel, discord.abc.GuildChannel) else f"`{channel_id}`"
        attachments = snapshot.attachments if snapshot else []
        attachment_lines = []
        for item in attachments:
            readable = f"{item.size / 1024:.0f} KB" if item.size < 1024 * 1024 else f"{item.size / 1024 / 1024:.1f} MB"
            restored = "✅ visszacsatolva" if item.data is not None else "⚠️ csak metaadat"
            attachment_lines.append(f"`{item.filename}` • {readable} • {restored}")
        fields = [
            ("👤 Szerző", author_text, True),
            ("📍 Csatorna", channel_text, True),
            ("🆔 Message ID", f"`{message_id}`", True),
            ("🗑️ Törölte", actor_text, False),
            ("💬 Tartalom", (content or "*(nincs szöveges tartalom)*")[:1000], False),
        ]
        if attachment_lines:
            fields.append(("🖼️ Attachmentek", "\n".join(attachment_lines)[:1000], False))
        await self._send_log(
            guild,
            "🗑️ Üzenet törölve",
            color=DANGER,
            fields=fields,
            files=self._files_from_snapshot(snapshot) if await self._log_enabled(guild.id, "deleted_attachments") else None,
            log_key="message_delete",
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._cache_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        suppressed = getattr(self.bot, "_suppressed_delete_log_ids", None)
        if suppressed is not None and message.id in suppressed:
            suppressed.discard(message.id)
            self._pop_snapshot(message.id)
            self._handled_delete_ids[message.id] = time.monotonic()
            return
        if message.guild is None or message.author.bot:
            return
        if message.id in self._handled_delete_ids:
            return
        self._handled_delete_ids[message.id] = time.monotonic()
        snapshot = self._pop_snapshot(message.id)
        await self._deleted_message_log(
            message.guild,
            message_id=message.id,
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_text=f"{message.author} (`{message.author.id}`)",
            content=message.content,
            snapshot=snapshot,
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id is None:
            return
        await asyncio.sleep(0.25)
        suppressed = getattr(self.bot, "_suppressed_delete_log_ids", None)
        if suppressed is not None and payload.message_id in suppressed:
            suppressed.discard(payload.message_id)
            self._pop_snapshot(payload.message_id)
            self._handled_delete_ids[payload.message_id] = time.monotonic()
            return
        if payload.message_id in self._handled_delete_ids:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        snapshot = self._pop_snapshot(payload.message_id)
        # If the normal cached event did not fire, our own lightweight snapshot can
        # still restore recent content/attachments.  Otherwise we at least log IDs.
        self._handled_delete_ids[payload.message_id] = time.monotonic()
        author_id = snapshot.author_id if snapshot else None
        author_text = (
            f"{snapshot.author_name} (`{snapshot.author_id}`)" if snapshot else "Ismeretlen (nem volt cache-ben)"
        )
        await self._deleted_message_log(
            guild,
            message_id=payload.message_id,
            channel_id=payload.channel_id,
            author_id=author_id,
            author_text=author_text,
            content=snapshot.content if snapshot else "*(az üzenet nem volt cache-ben)*",
            snapshot=snapshot,
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot:
            return
        content_changed = before.content != after.content
        attachments_changed = [a.id for a in before.attachments] != [a.id for a in after.attachments]
        if not content_changed and not attachments_changed:
            return
        await self._cache_message(after)
        fields = [
            ("👤 Szerző", f"{before.author} (`{before.author.id}`)", True),
            ("📍 Csatorna", before.channel.mention, True),
        ]
        if content_changed:
            fields.extend([
                ("⬅️ Előtte", (before.content or "*(üres)*")[:900], False),
                ("➡️ Utána", (after.content or "*(üres)*")[:900], False),
            ])
        if attachments_changed:
            fields.append(("📎 Attachment", f"{len(before.attachments)} → {len(after.attachments)}", False))
        await self._send_log(before.guild, "✏️ Üzenet szerkesztve", color=GOLD, fields=fields, log_key="message_edit")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - member.created_at).total_seconds()))
        warning = " ⚠️ **Nagyon új fiók**" if age_seconds < 24 * 3600 else ""
        await self._send_log(
            member.guild,
            "📥 Tag csatlakozott",
            color=SUCCESS,
            log_key="join_leave",
            fields=[
                ("👤 Felhasználó", f"{member} (`{member.id}`)", True),
                ("📅 Fiók kora", f"<t:{int(member.created_at.timestamp())}:R>{warning}", True),
            ],
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        # Yoru kick/ban already has its own command log.
        if self._audit_suppressed(guild.id, member.id, "kick", consume=True):
            return
        if self._audit_suppressed(guild.id, member.id, "ban", consume=False):
            return
        await asyncio.sleep(modcfg.AUDIT_SETTLE_SECONDS)
        ban_entry = await self._audit_entry(guild, discord.AuditLogAction.ban, member.id, settle=False)
        if ban_entry is not None:
            return  # on_member_ban logs it with richer data.
        kick_entry = await self._audit_entry(guild, discord.AuditLogAction.kick, member.id, settle=False)
        if kick_entry is not None:
            actor_id, actor_text, reason = self._actor_text(kick_entry)
            case = await self._case(guild, "kick", member.id, actor_id, reason)
            await self._send_log(guild, "👢 Kirúgás (Discord)", color=GOLD, log_key="ban_kick", fields=[
                ("👤 Felhasználó", f"{member} (`{member.id}`)", True),
                ("🛡️ Moderátor", actor_text, True),
                ("🧾 Eset", f"#{case}", True),
                ("📝 Indok", reason, False),
            ])
            return
        await self._send_log(guild, "📤 Tag távozott", color=GOLD, log_key="join_leave", fields=[
            ("👤 Felhasználó", f"{member} (`{member.id}`)", True)
        ])

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> None:
        if self._audit_suppressed(guild.id, user.id, "ban", consume=True):
            return
        entry = await self._audit_entry(guild, discord.AuditLogAction.ban, user.id)
        actor_id, actor_text, reason = self._actor_text(entry)
        case = await self._case(guild, "ban", user.id, actor_id, reason)
        await self._send_log(guild, "🔨 Kitiltás (Discord)", color=DANGER, log_key="ban_kick", fields=[
            ("👤 Felhasználó", f"{user} (`{user.id}`)", True),
            ("🛡️ Moderátor", actor_text, True),
            ("🧾 Eset", f"#{case}", True),
            ("📝 Indok", reason, False),
        ])

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        if self._audit_suppressed(guild.id, user.id, "unban", consume=True):
            return
        entry = await self._audit_entry(guild, discord.AuditLogAction.unban, user.id)
        actor_id, actor_text, reason = self._actor_text(entry)
        case = await self._case(guild, "unban", user.id, actor_id, reason)
        await self._send_log(guild, "🔓 Kitiltás feloldva (Discord)", color=SUCCESS, log_key="ban_kick", fields=[
            ("👤 Felhasználó", f"{user} (`{user.id}`)", True),
            ("🛡️ Moderátor", actor_text, True),
            ("🧾 Eset", f"#{case}", True),
            ("📝 Indok", reason, False),
        ])

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild
        before_timeout = before.timed_out_until
        after_timeout = after.timed_out_until
        if before_timeout != after_timeout:
            if not self._audit_suppressed(guild.id, after.id, "timeout", consume=True):
                entry = await self._audit_entry(guild, discord.AuditLogAction.member_update, after.id)
                actor_id, actor_text, reason = self._actor_text(entry)
                now = datetime.now(timezone.utc)
                is_timeout = after_timeout is not None and after_timeout > now
                action = "mute" if is_timeout else "unmute"
                case = await self._case(guild, action, after.id, actor_id, reason)
                fields = [
                    ("👤 Felhasználó", f"{after} (`{after.id}`)", True),
                    ("🛡️ Moderátor", actor_text, True),
                    ("🧾 Eset", f"#{case}", True),
                ]
                if is_timeout and after_timeout:
                    fields.append(("⏱️ Vége", f"<t:{int(after_timeout.timestamp())}:F> • <t:{int(after_timeout.timestamp())}:R>", False))
                fields.append(("📝 Indok", reason, False))
                await self._send_log(
                    guild,
                    "🔇 Némítás (Discord)" if is_timeout else "🔊 Némítás feloldva (Discord)",
                    color=GOLD if is_timeout else SUCCESS,
                    fields=fields,
                    log_key="timeout",
                )

        if before.nick != after.nick:
            entry = await self._audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            _actor_id, actor_text, reason = self._actor_text(entry)
            await self._send_log(guild, "🏷️ Becenév változott", color=GOLD, log_key="role_nick", fields=[
                ("👤 Felhasználó", f"{after} (`{after.id}`)", True),
                ("🛡️ Módosította", actor_text, True),
                ("⬅️ Előtte", before.nick or before.name, False),
                ("➡️ Utána", after.nick or after.name, False),
                ("📝 Indok", reason, False),
            ])

        before_roles = {r.id: r for r in before.roles if not r.is_default()}
        after_roles = {r.id: r for r in after.roles if not r.is_default()}
        added = [role for rid, role in after_roles.items() if rid not in before_roles]
        removed = [role for rid, role in before_roles.items() if rid not in after_roles]
        if added or removed:
            role_action = getattr(discord.AuditLogAction, "member_role_update", discord.AuditLogAction.member_update)
            entry = await self._audit_entry(guild, role_action, after.id)
            _actor_id, actor_text, reason = self._actor_text(entry)
            fields = [
                ("👤 Felhasználó", f"{after} (`{after.id}`)", True),
                ("🛡️ Módosította", actor_text, True),
            ]
            if added:
                fields.append(("➕ Hozzáadva", ", ".join(r.mention for r in added)[:900], False))
            if removed:
                fields.append(("➖ Eltávolítva", ", ".join(r.mention for r in removed)[:900], False))
            fields.append(("📝 Indok", reason, False))
            await self._send_log(guild, "🎭 Rang változott", color=BRAND, fields=fields, log_key="role_nick")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        enabled = await self._log_enabled(member.guild.id, "voice")
        if not enabled or before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            title = "🔊 Voice csatlakozás"
            detail = f"Belépett: {after.channel.mention}"
        elif before.channel is not None and after.channel is None:
            title = "🔇 Voice távozás"
            detail = f"Kilépett: {before.channel.mention}"
        else:
            title = "🔁 Voice mozgatás"
            detail = f"{before.channel.mention} → {after.channel.mention}"
        await self._send_log(member.guild, title, color=BRAND, log_key="voice", fields=[
            ("👤 Felhasználó", f"{member} (`{member.id}`)", True),
            ("🎙️ Voice", detail, False),
        ])
