from __future__ import annotations

import re
import time
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from app.database import Database
from app.services.server_settings import ServerSettingsService
from app import moderation_config as modcfg
from app.ui import BRAND, DANGER, GOLD, SUCCESS, base_embed


_INVITE_RE = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?(?:discord(?:app)?\.com/invite|discord\.gg)/[A-Za-z0-9-]+"
)
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>]+")
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")

_RULE_ALIASES = {
    "link": "links",
    "links": "links",
    "invite": "invite",
    "invites": "invite",
    "discord": "invite",
    "spam": "spam",
    "duplicate": "duplicate",
    "dupe": "duplicate",
    "mentions": "mentions",
    "mention": "mentions",
    "caps": "caps",
    "emoji": "emoji",
    "emojis": "emoji",
    "words": "words",
    "word": "words",
    "zalgo": "zalgo",
    "unicode": "zalgo",
}


def _rule_name(raw: str) -> str:
    key = raw.strip().lower()
    rule = _RULE_ALIASES.get(key, key)
    if rule not in modcfg.AUTOMOD_RULE_DEFAULTS:
        raise ValueError("Ismeretlen szabály. Használható: " + ", ".join(modcfg.AUTOMOD_RULE_DEFAULTS))
    return rule


def _on_off(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"on", "true", "1", "igen", "be", "enable", "enabled"}:
        return True
    if value in {"off", "false", "0", "nem", "ki", "disable", "disabled"}:
        return False
    raise ValueError("Használd: `on` vagy `off`.")


def _normalize_domain(raw: str) -> str:
    value = raw.strip().lower().rstrip("./")
    if not value:
        raise ValueError("Adj meg egy domaint.")
    if "://" not in value:
        value = "https://" + value
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise ValueError("Érvénytelen domain.") from exc
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or " " in host:
        raise ValueError("Érvénytelen domain.")
    return host


def _domain_matches(host: str, configured: str) -> bool:
    return host == configured or host.endswith("." + configured)


def _extract_domains(content: str) -> set[str]:
    result: set[str] = set()
    for match in _URL_RE.findall(content):
        raw = match.rstrip(".,!?;:)]}\"")
        if raw.lower().startswith("www."):
            raw = "https://" + raw
        try:
            host = (urlsplit(raw).hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host:
            result.add(host)
    # discord.gg links without an explicit scheme are caught by the invite regex.
    if _INVITE_RE.search(content):
        result.add("discord.gg")
    return result


def _emoji_count(content: str) -> int:
    custom = len(_CUSTOM_EMOJI_RE.findall(content))
    text = _CUSTOM_EMOJI_RE.sub("", content)
    unicode_count = 0
    for char in text:
        code = ord(char)
        if (
            0x1F300 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or 0x2300 <= code <= 0x23FF
        ):
            unicode_count += 1
    return custom + unicode_count


def _contains_word(content: str, words: list[str]) -> str | None:
    lowered = content.casefold()
    for raw in words:
        word = raw.casefold().strip()
        if not word:
            continue
        if " " in word or not word.replace("_", "").isalnum():
            if word in lowered:
                return raw
        else:
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", lowered, re.IGNORECASE):
                return raw
    return None


class AutomodCog(commands.GroupCog, group_name="automod", group_description="Yoru AutoMod beállítások."):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.settings = ServerSettingsService(db)
        self._spam: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._duplicate: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)
        self._notice_times: dict[tuple[int, int, str], float] = {}
        self._joins: dict[int, deque[tuple[float, int]]] = defaultdict(deque)
        self._raid_alert_times: dict[int, float] = {}
        self._runtime_prune_counter = 0

    def _prune_runtime_state(self, now: float) -> None:
        # Anti-spam deques are keyed by user. Without periodic pruning, users who
        # leave after one message would keep tiny cache entries for the whole uptime.
        stale_after = max(600.0, float(modcfg.RAID_JOIN_WINDOW_SECONDS) * 4.0)
        if len(self._spam) >= 1000:
            for key, values in list(self._spam.items()):
                if not values or now - values[-1] > stale_after:
                    self._spam.pop(key, None)
        if len(self._duplicate) >= 1000:
            for key, values in list(self._duplicate.items()):
                if not values or now - values[-1][0] > stale_after:
                    self._duplicate.pop(key, None)
        notice_cutoff = now - max(600.0, float(modcfg.AUTOMOD_NOTICE_COOLDOWN_SECONDS) * 4.0)
        if len(self._notice_times) >= 1000:
            self._notice_times = {key: stamp for key, stamp in self._notice_times.items() if stamp >= notice_cutoff}
        raid_cutoff = now - max(600.0, float(modcfg.RAID_ALERT_COOLDOWN_SECONDS) * 4.0)
        if len(self._raid_alert_times) >= 250:
            self._raid_alert_times = {gid: stamp for gid, stamp in self._raid_alert_times.items() if stamp >= raid_cutoff}

    async def _global_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_automod_enabled(guild_id)

    async def _set_global_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.settings.set_automod_enabled(guild_id, enabled)

    async def _rule(self, guild_id: int, rule: str) -> tuple[bool, str, int, int]:
        state = await self.settings.get_rule(guild_id, rule)
        return state.enabled, state.action, state.threshold, state.timeout_seconds

    async def _save_rule(
        self,
        guild_id: int,
        rule: str,
        *,
        enabled: bool | None = None,
        action: str | None = None,
        threshold: int | None = None,
        timeout_seconds: int | None = None,
    ) -> tuple[bool, str, int, int]:
        state = await self.settings.set_rule(
            guild_id,
            rule,
            enabled=enabled,
            action=action,
            threshold=threshold,
            timeout_seconds=timeout_seconds,
        )
        return state.enabled, state.action, state.threshold, state.timeout_seconds

    async def _window_seconds(self, guild_id: int, rule: str) -> float:
        value = await self.settings.get_rule_window(guild_id, rule)
        if value is None:
            return float(modcfg.SPAM_WINDOW_SECONDS if rule == "spam" else modcfg.DUPLICATE_WINDOW_SECONDS)
        return value

    async def _is_exempt(self, message: discord.Message, rule: str) -> bool:
        member = message.author
        if not isinstance(member, discord.Member):
            return False
        if member.id == message.guild.owner_id:
            return True
        if modcfg.AUTOMOD_STAFF_BYPASS and (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_messages
            or member.guild_permissions.manage_guild
        ):
            return True

        rows = await self.db.list_automod_exemptions(message.guild.id, rule)
        channel_id = message.channel.id
        category_id = getattr(message.channel, "category_id", None)
        if isinstance(message.channel, discord.Thread):
            parent = message.channel.parent
            category_id = getattr(parent, "category_id", None) if parent else None
        role_ids = {r.id for r in member.roles}
        for _stored_rule, scope_type, scope_id in rows:
            if scope_type == "channel" and scope_id == channel_id:
                return True
            if scope_type == "category" and category_id is not None and scope_id == category_id:
                return True
            if scope_type == "role" and scope_id in role_ids:
                return True
        return False

    async def _domains(self, guild_id: int) -> tuple[set[str], set[str]]:
        rows = await self.db.list_automod_domains(guild_id)
        allowed = set(modcfg.DEFAULT_ALLOWED_DOMAINS)
        blocked = set(modcfg.DEFAULT_BLOCKED_DOMAINS)
        for mode, domain in rows:
            (allowed if mode == "allow" else blocked).add(domain)
        return allowed, blocked

    async def _send_log(
        self,
        guild: discord.Guild,
        *,
        rule: str,
        action: str,
        message: discord.Message,
        detail: str,
        case_id: int | None = None,
    ) -> None:
        log_raw = await self.db.get_guild_state(guild.id, "moderation_log_automod")
        if log_raw is not None and log_raw != "1":
            return
        raw = await self.db.get_guild_state(guild.id, "moderation_log_channel")
        if not raw or not raw.isdigit():
            return
        channel = guild.get_channel(int(raw))
        if not isinstance(channel, discord.TextChannel):
            return
        label = modcfg.AUTOMOD_RULE_LABELS.get(rule, rule)
        embed = base_embed("🛡️ AutoMod intézkedés", color=DANGER)
        embed.add_field(name="👤 Felhasználó", value=f"{message.author} (`{message.author.id}`)", inline=True)
        embed.add_field(name="📍 Csatorna", value=getattr(message.channel, "mention", f"`{message.channel.id}`"), inline=True)
        embed.add_field(name="🔎 Szabály", value=label, inline=True)
        embed.add_field(name="⚙️ Művelet", value=action, inline=True)
        if case_id:
            embed.add_field(name="🧾 Eset", value=f"`#{case_id}`", inline=True)
        embed.add_field(name="ℹ️ Találat", value=detail[:900], inline=False)
        embed.add_field(name="💬 Üzenet", value=(message.content or "*(nincs szöveg)*")[:900], inline=False)
        embed.set_footer(text="Yoru • AutoMod")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _notice(self, message: discord.Message, rule: str, action: str) -> None:
        key = (message.guild.id, message.author.id, rule)
        now = time.monotonic()
        if now - self._notice_times.get(key, 0.0) < modcfg.AUTOMOD_NOTICE_COOLDOWN_SECONDS:
            return
        self._notice_times[key] = now
        label = modcfg.AUTOMOD_RULE_LABELS.get(rule, rule)
        suffix = ""
        if action == "warn":
            suffix = " • figyelmeztetés rögzítve"
        elif action == "timeout":
            suffix = " • timeout alkalmazva"
        try:
            await message.channel.send(
                f"{message.author.mention} 🛡️ **AutoMod:** {label}{suffix}.",
                delete_after=modcfg.AUTOMOD_NOTICE_DELETE_AFTER,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _apply(self, message: discord.Message, rule: str, detail: str, action: str, timeout_seconds: int) -> bool:
        suppressed = getattr(self.bot, "_suppressed_delete_log_ids", None)
        if isinstance(suppressed, set):
            suppressed.add(message.id)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            if isinstance(suppressed, set):
                suppressed.discard(message.id)

        case_id: int | None = None
        moderator_id = self.bot.user.id if self.bot.user else 0
        reason = f"AutoMod • {modcfg.AUTOMOD_RULE_LABELS.get(rule, rule)} • {detail[:300]}"
        member = message.author if isinstance(message.author, discord.Member) else None

        if action == "warn" and member is not None:
            await self.db.add_warning(message.guild.id, member.id, moderator_id, reason)
            case_id = await self.db.add_mod_case(message.guild.id, "automod_warn", member.id, moderator_id, reason)
        elif action == "timeout" and member is not None:
            until = datetime.now(timezone.utc) + timedelta(seconds=max(60, timeout_seconds))
            try:
                # Tell the moderation cog not to duplicate-log our own timeout.
                moderation = self.bot.get_cog("ModerationCog")
                if moderation and hasattr(moderation, "suppress_external_audit"):
                    moderation.suppress_external_audit(message.guild.id, member.id, "timeout")
                await member.timeout(until, reason=reason[:500])
                case_id = await self.db.add_mod_case(message.guild.id, "automod_timeout", member.id, moderator_id, reason)
            except (discord.Forbidden, discord.HTTPException):
                # Deletion still happened; fall back to a warning record rather than
                # silently losing the moderation action.
                await self.db.add_warning(message.guild.id, member.id, moderator_id, reason + " | timeout sikertelen")
                case_id = await self.db.add_mod_case(message.guild.id, "automod_warn", member.id, moderator_id, reason + " | timeout sikertelen")
                action = "warn (timeout sikertelen)"
        elif member is not None:
            case_id = await self.db.add_mod_case(message.guild.id, "automod_delete", member.id, moderator_id, reason)

        await self._send_log(message.guild, rule=rule, action=action, message=message, detail=detail, case_id=case_id)
        await self._notice(message, rule, action)
        return True

    async def check_message(self, message: discord.Message) -> bool:
        """Return True when AutoMod handled/deleted the message."""
        if message.guild is None or message.author.bot or message.webhook_id is not None:
            return False
        if not isinstance(message.author, discord.Member):
            return False
        if not await self._global_enabled(message.guild.id):
            return False

        self._runtime_prune_counter += 1
        if self._runtime_prune_counter >= 256:
            self._runtime_prune_counter = 0
            self._prune_runtime_state(time.monotonic())

        content = message.content or ""
        domains = _extract_domains(content)
        allowed_domains, blocked_domains = await self._domains(message.guild.id)

        # Explicit blocklist is the strongest rule.  It ignores normal channel / role
        # exemptions and staff bypass; only the guild owner bypasses it.
        if message.author.id != message.guild.owner_id:
            blocked_hit = next(
                (host for host in domains if any(_domain_matches(host, blocked) for blocked in blocked_domains)),
                None,
            )
            if blocked_hit:
                enabled, action, _threshold, timeout_seconds = await self._rule(message.guild.id, "links")
                # The blacklist is enforced even if generic links are disabled.
                return await self._apply(message, "links", f"Tiltott domain: `{blocked_hit}`", action if action != "delete" else "timeout", timeout_seconds)

        # Discord invite links get their own channel/category/role exemptions.
        invite_present = bool(_INVITE_RE.search(content))
        invite_exempt = False
        if invite_present:
            enabled, action, _threshold, timeout_seconds = await self._rule(message.guild.id, "invite")
            invite_exempt = await self._is_exempt(message, "invite")
            if enabled and not invite_exempt:
                return await self._apply(message, "invite", "Discord meghívó link", action, timeout_seconds)

        # Generic external links.  Allowlisted domains bypass this rule.  A channel
        # explicitly exempted from the invite rule is allowed to post Discord
        # invites even when generic link detection is enabled.
        if domains:
            enabled, action, _threshold, timeout_seconds = await self._rule(message.guild.id, "links")
            non_allowed = [
                host for host in domains
                if not any(_domain_matches(host, allowed) for allowed in allowed_domains)
                and not (invite_exempt and (host == "discord.gg" or _domain_matches(host, "discord.com")))
            ]
            if enabled and non_allowed and not await self._is_exempt(message, "links"):
                return await self._apply(message, "links", f"Külső domain: `{non_allowed[0]}`", action, timeout_seconds)

        # After dangerous-link checks, staff bypass applies to normal anti-spam rules.
        if modcfg.AUTOMOD_STAFF_BYPASS and (
            message.author.guild_permissions.administrator
            or message.author.guild_permissions.manage_messages
            or message.author.guild_permissions.manage_guild
        ):
            return False

        # Banned words.
        enabled, action, _threshold, timeout_seconds = await self._rule(message.guild.id, "words")
        if enabled and not await self._is_exempt(message, "words"):
            words = await self.db.list_automod_words(message.guild.id)
            hit = _contains_word(content, words)
            if hit:
                return await self._apply(message, "words", f"Tiltott szó/kifejezés: `{hit}`", action, timeout_seconds)

        # Mention spam.
        enabled, action, threshold, timeout_seconds = await self._rule(message.guild.id, "mentions")
        mention_count = len({u.id for u in message.mentions}) + len({r.id for r in message.role_mentions})
        if message.mention_everyone:
            mention_count = max(mention_count, threshold)
        if enabled and mention_count >= threshold and not await self._is_exempt(message, "mentions"):
            return await self._apply(message, "mentions", f"{mention_count} mention egy üzenetben", action, timeout_seconds)

        # CAPS spam.
        enabled, action, threshold, timeout_seconds = await self._rule(message.guild.id, "caps")
        letters = [char for char in content if char.isalpha()]
        if enabled and len(letters) >= modcfg.CAPS_MIN_LETTERS and not await self._is_exempt(message, "caps"):
            ratio = (sum(1 for c in letters if c.isupper()) / len(letters)) * 100
            if ratio >= threshold:
                return await self._apply(message, "caps", f"{ratio:.0f}% nagybetű", action, timeout_seconds)

        # Emoji spam.
        enabled, action, threshold, timeout_seconds = await self._rule(message.guild.id, "emoji")
        emoji_count = _emoji_count(content)
        if enabled and emoji_count >= threshold and not await self._is_exempt(message, "emoji"):
            return await self._apply(message, "emoji", f"{emoji_count} emoji", action, timeout_seconds)

        # Unicode / Zalgo spam.
        enabled, action, threshold, timeout_seconds = await self._rule(message.guild.id, "zalgo")
        combining = sum(1 for c in content if unicodedata.combining(c))
        if enabled and combining >= threshold and not await self._is_exempt(message, "zalgo"):
            return await self._apply(message, "zalgo", f"{combining} kombináló Unicode karakter", action, timeout_seconds)

        now = time.monotonic()
        key = (message.guild.id, message.author.id)

        # Duplicate message spam.
        enabled, action, threshold, timeout_seconds = await self._rule(message.guild.id, "duplicate")
        normalized = " ".join(content.casefold().split())
        if enabled and len(normalized) >= 3 and not await self._is_exempt(message, "duplicate"):
            dq = self._duplicate[key]
            duplicate_window = await self._window_seconds(message.guild.id, "duplicate")
            while dq and now - dq[0][0] > duplicate_window:
                dq.popleft()
            dq.append((now, normalized))
            same = sum(1 for _stamp, text in dq if text == normalized)
            if same >= threshold:
                dq.clear()
                return await self._apply(message, "duplicate", f"{same} azonos üzenet / {duplicate_window:g} mp", action, timeout_seconds)

        # General message-rate spam.
        enabled, action, threshold, timeout_seconds = await self._rule(message.guild.id, "spam")
        if enabled and not await self._is_exempt(message, "spam"):
            dq2 = self._spam[key]
            spam_window = await self._window_seconds(message.guild.id, "spam")
            while dq2 and now - dq2[0] > spam_window:
                dq2.popleft()
            dq2.append(now)
            if len(dq2) >= threshold:
                count = len(dq2)
                dq2.clear()
                return await self._apply(message, "spam", f"{count} üzenet / {spam_window:g} mp", action, timeout_seconds)

        return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not await self._global_enabled(member.guild.id):
            return
        now = time.monotonic()
        joins = self._joins[member.guild.id]
        while joins and now - joins[0][0] > modcfg.RAID_JOIN_WINDOW_SECONDS:
            joins.popleft()
        joins.append((now, member.id))
        if len(joins) < modcfg.RAID_JOIN_THRESHOLD:
            return
        if now - self._raid_alert_times.get(member.guild.id, 0.0) < modcfg.RAID_ALERT_COOLDOWN_SECONDS:
            return
        self._raid_alert_times[member.guild.id] = now
        raw = await self.db.get_guild_state(member.guild.id, "moderation_log_channel")
        if not raw or not raw.isdigit():
            return
        channel = member.guild.get_channel(int(raw))
        if not isinstance(channel, discord.TextChannel):
            return
        recent_ids = [uid for _stamp, uid in list(joins)[-10:]]
        new_accounts = 0
        for uid in recent_ids:
            joined = member.guild.get_member(uid)
            if joined and (datetime.now(timezone.utc) - joined.created_at).total_seconds() < 24 * 3600:
                new_accounts += 1
        embed = base_embed(
            "🚨 Raid activity alert",
            f"**{len(joins)} tag** csatlakozott az elmúlt **{modcfg.RAID_JOIN_WINDOW_SECONDS:.0f} másodpercben**.",
            DANGER,
        )
        embed.add_field(name="🆕 24 óránál fiatalabb account", value=str(new_accounts), inline=True)
        embed.add_field(name="ℹ️ Művelet", value="Csak riasztás — Yoru automatikusan nem bannol senkit.", inline=False)
        embed.set_footer(text="Yoru • AutoMod • Raid detection")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ---------------- status / helpers ----------------
    async def _status_embed(self, guild: discord.Guild) -> discord.Embed:
        enabled = await self._global_enabled(guild.id)
        overrides = await self.db.list_automod_rules(guild.id)
        lines: list[str] = []
        for rule in modcfg.AUTOMOD_RULE_DEFAULTS:
            state = overrides.get(rule) or await self._rule(guild.id, rule)
            is_enabled, action, threshold, timeout = state
            icon = "✅" if is_enabled else "❌"
            lines.append(
                f"{icon} **{modcfg.AUTOMOD_RULE_LABELS[rule]}** — `{action}` • küszöb `{threshold}`"
                + (f" • timeout {timeout // 60}p" if action == "timeout" else "")
            )
        exemptions = await self.db.list_automod_exemptions(guild.id)
        domains = await self.db.list_automod_domains(guild.id)
        words = await self.db.list_automod_words(guild.id)

        exemption_lines: list[str] = []
        for ex_rule, scope_type, scope_id in exemptions[:12]:
            if scope_type in {"channel", "category"}:
                obj = guild.get_channel(scope_id)
                target = getattr(obj, "mention", None) or (f"#{getattr(obj, 'name', scope_id)}" if obj else f"`{scope_id}`")
            else:
                role = guild.get_role(scope_id)
                target = role.mention if role else f"`{scope_id}`"
            exemption_lines.append(f"`{ex_rule}` • {scope_type}: {target}")
        if len(exemptions) > 12:
            exemption_lines.append(f"… +{len(exemptions) - 12} további")

        domain_lines = [f"{'✅' if mode == 'allow' else '⛔'} `{domain}`" for mode, domain in domains[:10]]
        if len(domains) > 10:
            domain_lines.append(f"… +{len(domains) - 10} további")
        word_preview = ", ".join(f"`{w}`" for w in words[:8]) or "—"
        if len(words) > 8:
            word_preview += f" … +{len(words) - 8}"

        embed = base_embed(
            "🛡️ Yoru AutoMod",
            "**BEKAPCSOLVA**" if enabled else "**KIKAPCSOLVA** — `!automod on` vagy `/automod enable`",
            SUCCESS if enabled else GOLD,
        )
        embed.add_field(name="Szabályok", value="\n".join(lines), inline=False)
        embed.add_field(name="Kivételek", value="\n".join(exemption_lines) if exemption_lines else "—", inline=False)
        embed.add_field(name="Domain szabályok", value="\n".join(domain_lines) if domain_lines else "—", inline=False)
        embed.add_field(name="Tiltott szavak", value=word_preview, inline=False)
        embed.add_field(
            name="Gyors példa",
            value=(
                "`!automod exemptchannel invite #partnereink`\n"
                "`!automod exemptcategory invite <ticket-kategória>`\n"
                "`!automod rule links on`"
            ),
            inline=False,
        )
        embed.set_footer(text="Yoru • AutoMod • A blacklistelt domain a normál kivételeket felülírja")
        return embed

    async def _require_manage_guild_interaction(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.guild_permissions.manage_guild:
            await interaction.response.send_message("⛔ Ehhez `Szerver kezelése` jogosultság kell.", ephemeral=True)
            return False
        return True

    # ---------------- prefix config ----------------
    @commands.group(name="automod", aliases=["amod"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def automod_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await self._status_embed(ctx.guild))

    @automod_prefix.command(name="on", aliases=["enable", "be"])
    async def automod_on_prefix(self, ctx: commands.Context) -> None:
        await self._set_global_enabled(ctx.guild.id, True)
        await ctx.send("✅ AutoMod bekapcsolva.")

    @automod_prefix.command(name="off", aliases=["disable", "ki"])
    async def automod_off_prefix(self, ctx: commands.Context) -> None:
        await self._set_global_enabled(ctx.guild.id, False)
        await ctx.send("✅ AutoMod kikapcsolva.")

    @automod_prefix.command(name="rule")
    async def automod_rule_prefix(self, ctx: commands.Context, rule: str, state: str) -> None:
        try:
            rule = _rule_name(rule)
            enabled = _on_off(state)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await self._save_rule(ctx.guild.id, rule, enabled=enabled)
        await ctx.send(f"✅ {modcfg.AUTOMOD_RULE_LABELS[rule]}: **{'ON' if enabled else 'OFF'}**.")

    @automod_prefix.command(name="action")
    async def automod_action_prefix(self, ctx: commands.Context, rule: str, action: str) -> None:
        try:
            rule = _rule_name(rule)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        action = action.lower()
        if action not in modcfg.AUTOMOD_ACTIONS:
            return await ctx.send("❌ Action: `delete`, `warn` vagy `timeout`.")
        await self._save_rule(ctx.guild.id, rule, action=action)
        await ctx.send(f"✅ {modcfg.AUTOMOD_RULE_LABELS[rule]} action: **{action}**.")

    @automod_prefix.command(name="threshold")
    async def automod_threshold_prefix(self, ctx: commands.Context, rule: str, value: int) -> None:
        try:
            rule = _rule_name(rule)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        if value < 1 or value > 100:
            return await ctx.send("❌ A küszöb 1–100 között legyen.")
        await self._save_rule(ctx.guild.id, rule, threshold=value)
        await ctx.send(f"✅ {modcfg.AUTOMOD_RULE_LABELS[rule]} küszöb: **{value}**.")

    @automod_prefix.command(name="timeout")
    async def automod_timeout_prefix(self, ctx: commands.Context, rule: str, minutes: int) -> None:
        try:
            rule = _rule_name(rule)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        if minutes < 1 or minutes > 40320:
            return await ctx.send("❌ 1 perc és 28 nap között legyen.")
        await self._save_rule(ctx.guild.id, rule, timeout_seconds=minutes * 60)
        await ctx.send(f"✅ {modcfg.AUTOMOD_RULE_LABELS[rule]} timeout: **{minutes} perc**.")

    async def _add_exemption(self, guild_id: int, rule_raw: str, scope_type: str, scope_id: int) -> str:
        rule = "all" if rule_raw.strip().lower() in {"all", "minden"} else _rule_name(rule_raw)
        await self.db.add_automod_exemption(guild_id, rule, scope_type, scope_id)
        return rule

    @automod_prefix.command(name="exemptchannel", aliases=["allowchannel"])
    async def automod_exempt_channel_prefix(self, ctx: commands.Context, rule: str, channel: discord.TextChannel) -> None:
        try:
            stored = await self._add_exemption(ctx.guild.id, rule, "channel", channel.id)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.send(f"✅ {channel.mention} kivétel: **{stored}**.")

    @automod_prefix.command(name="exemptcategory", aliases=["allowcategory"])
    async def automod_exempt_category_prefix(self, ctx: commands.Context, rule: str, category: discord.CategoryChannel) -> None:
        try:
            stored = await self._add_exemption(ctx.guild.id, rule, "category", category.id)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.send(f"✅ **{category.name}** kategória kivétel: **{stored}**.")

    @automod_prefix.command(name="exemptrole", aliases=["allowrole"])
    async def automod_exempt_role_prefix(self, ctx: commands.Context, rule: str, role: discord.Role) -> None:
        try:
            stored = await self._add_exemption(ctx.guild.id, rule, "role", role.id)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.send(f"✅ {role.mention} rang kivétel: **{stored}**.")

    @automod_prefix.command(name="unexemptchannel")
    async def automod_unexempt_channel_prefix(self, ctx: commands.Context, rule: str, channel: discord.TextChannel) -> None:
        try:
            stored = "all" if rule.lower() == "all" else _rule_name(rule)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        removed = await self.db.remove_automod_exemption(ctx.guild.id, stored, "channel", channel.id)
        await ctx.send("✅ Kivétel törölve." if removed else "ℹ️ Nem volt ilyen kivétel.")

    @automod_prefix.command(name="unexemptcategory")
    async def automod_unexempt_category_prefix(self, ctx: commands.Context, rule: str, category: discord.CategoryChannel) -> None:
        try:
            stored = "all" if rule.lower() == "all" else _rule_name(rule)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        removed = await self.db.remove_automod_exemption(ctx.guild.id, stored, "category", category.id)
        await ctx.send("✅ Kivétel törölve." if removed else "ℹ️ Nem volt ilyen kivétel.")

    @automod_prefix.command(name="unexemptrole")
    async def automod_unexempt_role_prefix(self, ctx: commands.Context, rule: str, role: discord.Role) -> None:
        try:
            stored = "all" if rule.lower() == "all" else _rule_name(rule)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        removed = await self.db.remove_automod_exemption(ctx.guild.id, stored, "role", role.id)
        await ctx.send("✅ Kivétel törölve." if removed else "ℹ️ Nem volt ilyen kivétel.")

    @automod_prefix.command(name="domain")
    async def automod_domain_prefix(self, ctx: commands.Context, mode: str, domain: str) -> None:
        mode = mode.lower()
        try:
            normalized = _normalize_domain(domain)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        if mode in {"allow", "whitelist"}:
            await self.db.set_automod_domain(ctx.guild.id, "allow", normalized)
            return await ctx.send(f"✅ Engedélyezett domain: `{normalized}`")
        if mode in {"block", "blacklist"}:
            await self.db.set_automod_domain(ctx.guild.id, "block", normalized)
            return await ctx.send(f"✅ Tiltott domain: `{normalized}`")
        if mode in {"remove", "delete", "del"}:
            removed = await self.db.remove_automod_domain(ctx.guild.id, normalized)
            return await ctx.send("✅ Domain szabály törölve." if removed else "ℹ️ Nem volt ilyen domain szabály.")
        await ctx.send("❌ Használat: `!automod domain allow|block|remove example.com`")

    @automod_prefix.command(name="word")
    async def automod_word_prefix(self, ctx: commands.Context, mode: str, *, word: str) -> None:
        value = word.strip().casefold()
        if not value or len(value) > 100:
            return await ctx.send("❌ A szó/kifejezés 1–100 karakter legyen.")
        if mode.lower() in {"add", "block"}:
            await self.db.add_automod_word(ctx.guild.id, value)
            return await ctx.send(f"✅ Tiltott szó/kifejezés hozzáadva: `{value}`")
        if mode.lower() in {"remove", "delete", "del"}:
            removed = await self.db.remove_automod_word(ctx.guild.id, value)
            return await ctx.send("✅ Törölve." if removed else "ℹ️ Nem volt a listában.")
        await ctx.send("❌ Használat: `!automod word add|remove <szó vagy kifejezés>`")

    # ---------------- slash config ----------------
    @app_commands.command(name="status", description="Megmutatja az AutoMod aktuális beállításait.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_status_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild:
            await interaction.response.send_message(embed=await self._status_embed(interaction.guild), ephemeral=True)

    @app_commands.command(name="enable", description="Be- vagy kikapcsolja az AutoModot.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_enable_slash(self, interaction: discord.Interaction, enabled: bool) -> None:
        if interaction.guild is None:
            return
        await self._set_global_enabled(interaction.guild.id, enabled)
        await interaction.response.send_message(f"✅ AutoMod **{'bekapcsolva' if enabled else 'kikapcsolva'}**.", ephemeral=True)

    @app_commands.command(name="rule", description="Egy AutoMod szabály ki-/bekapcsolása.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_rule_slash(self, interaction: discord.Interaction, rule: str, enabled: bool) -> None:
        if interaction.guild is None:
            return
        try:
            rule = _rule_name(rule)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await self._save_rule(interaction.guild.id, rule, enabled=enabled)
        await interaction.response.send_message(f"✅ {modcfg.AUTOMOD_RULE_LABELS[rule]}: **{'ON' if enabled else 'OFF'}**.", ephemeral=True)

    @app_commands.command(name="action", description="Szabály művelete: delete, warn vagy timeout.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_action_slash(self, interaction: discord.Interaction, rule: str, action: str) -> None:
        if interaction.guild is None:
            return
        try:
            rule = _rule_name(rule)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        action = action.lower()
        if action not in modcfg.AUTOMOD_ACTIONS:
            return await interaction.response.send_message("❌ Action: `delete`, `warn` vagy `timeout`.", ephemeral=True)
        await self._save_rule(interaction.guild.id, rule, action=action)
        await interaction.response.send_message(f"✅ {modcfg.AUTOMOD_RULE_LABELS[rule]} action: **{action}**.", ephemeral=True)

    @app_commands.command(name="exempt_channel", description="Csatorna kivétel hozzáadása egy szabályhoz.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_exempt_channel_slash(self, interaction: discord.Interaction, rule: str, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            return
        try:
            stored = await self._add_exemption(interaction.guild.id, rule, "channel", channel.id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ {channel.mention} kivétel: **{stored}**.", ephemeral=True)

    @app_commands.command(name="exempt_category", description="Kategória kivétel hozzáadása egy szabályhoz.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_exempt_category_slash(self, interaction: discord.Interaction, rule: str, category: discord.CategoryChannel) -> None:
        if interaction.guild is None:
            return
        try:
            stored = await self._add_exemption(interaction.guild.id, rule, "category", category.id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ **{category.name}** kategória kivétel: **{stored}**.", ephemeral=True)

    @app_commands.command(name="exempt_role", description="Rang kivétel hozzáadása egy szabályhoz.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_exempt_role_slash(self, interaction: discord.Interaction, rule: str, role: discord.Role) -> None:
        if interaction.guild is None:
            return
        try:
            stored = await self._add_exemption(interaction.guild.id, rule, "role", role.id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ {role.mention} rang kivétel: **{stored}**.", ephemeral=True)

    @app_commands.command(name="unexempt_channel", description="Csatorna kivétel törlése egy szabályból.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_unexempt_channel_slash(self, interaction: discord.Interaction, rule: str, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            return
        try:
            stored = "all" if rule.lower() == "all" else _rule_name(rule)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        removed = await self.db.remove_automod_exemption(interaction.guild.id, stored, "channel", channel.id)
        await interaction.response.send_message("✅ Kivétel törölve." if removed else "ℹ️ Nem volt ilyen kivétel.", ephemeral=True)

    @app_commands.command(name="unexempt_category", description="Kategória kivétel törlése egy szabályból.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_unexempt_category_slash(self, interaction: discord.Interaction, rule: str, category: discord.CategoryChannel) -> None:
        if interaction.guild is None:
            return
        try:
            stored = "all" if rule.lower() == "all" else _rule_name(rule)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        removed = await self.db.remove_automod_exemption(interaction.guild.id, stored, "category", category.id)
        await interaction.response.send_message("✅ Kivétel törölve." if removed else "ℹ️ Nem volt ilyen kivétel.", ephemeral=True)

    @app_commands.command(name="unexempt_role", description="Rang kivétel törlése egy szabályból.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_unexempt_role_slash(self, interaction: discord.Interaction, rule: str, role: discord.Role) -> None:
        if interaction.guild is None:
            return
        try:
            stored = "all" if rule.lower() == "all" else _rule_name(rule)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        removed = await self.db.remove_automod_exemption(interaction.guild.id, stored, "role", role.id)
        await interaction.response.send_message("✅ Kivétel törölve." if removed else "ℹ️ Nem volt ilyen kivétel.", ephemeral=True)

    @app_commands.command(name="domain", description="Domain allow/block/remove szabály.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_domain_slash(self, interaction: discord.Interaction, mode: str, domain: str) -> None:
        if interaction.guild is None:
            return
        mode = mode.lower()
        try:
            normalized = _normalize_domain(domain)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        if mode in {"allow", "whitelist"}:
            await self.db.set_automod_domain(interaction.guild.id, "allow", normalized)
            text = f"✅ Engedélyezett domain: `{normalized}`"
        elif mode in {"block", "blacklist"}:
            await self.db.set_automod_domain(interaction.guild.id, "block", normalized)
            text = f"✅ Tiltott domain: `{normalized}`"
        elif mode in {"remove", "delete", "del"}:
            removed = await self.db.remove_automod_domain(interaction.guild.id, normalized)
            text = "✅ Domain szabály törölve." if removed else "ℹ️ Nem volt ilyen domain szabály."
        else:
            text = "❌ Mode: `allow`, `block` vagy `remove`."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="word", description="Tiltott szó/kifejezés hozzáadása vagy törlése.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automod_word_slash(self, interaction: discord.Interaction, mode: str, word: str) -> None:
        if interaction.guild is None:
            return
        value = word.strip().casefold()
        if not value or len(value) > 100:
            return await interaction.response.send_message("❌ A szó/kifejezés 1–100 karakter legyen.", ephemeral=True)
        if mode.lower() in {"add", "block"}:
            await self.db.add_automod_word(interaction.guild.id, value)
            text = f"✅ Tiltott szó/kifejezés hozzáadva: `{value}`"
        elif mode.lower() in {"remove", "delete", "del"}:
            removed = await self.db.remove_automod_word(interaction.guild.id, value)
            text = "✅ Törölve." if removed else "ℹ️ Nem volt a listában."
        else:
            text = "❌ Mode: `add` vagy `remove`."
        await interaction.response.send_message(text, ephemeral=True)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("⛔ Ehhez `Szerver kezelése` jogosultság kell.", delete_after=5)
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send("❌ Hibás csatorna/rang/kategória paraméter.", delete_after=5)
            return
        raise error

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "⛔ Ehhez `Szerver kezelése` jogosultság kell."
        else:
            raise error
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
