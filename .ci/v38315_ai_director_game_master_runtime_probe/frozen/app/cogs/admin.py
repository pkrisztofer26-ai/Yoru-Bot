from __future__ import annotations

import io
import json
import discord
from discord import app_commands
from discord.ext import commands

from app.database import Database
from app.services.economy_events_settings import EconomyEventsSettingsService
from app.ui import base_embed, money, money_inline
from app.ai_director_game_master_runtime_probe import run_live_runtime_probe


def _duration_label(hours: float) -> str:
    minutes = hours * 60
    if hours < 1:
        rounded = round(minutes)
        return f"{rounded} perc"
    if float(hours).is_integer():
        return f"{int(hours)} óra"
    return f"{hours:g} óra"


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db
        self.guild_settings = EconomyEventsSettingsService(db)

    async def _config_embed(self, guild: discord.Guild) -> discord.Embed:
        settings = self.bot.settings  # type: ignore[attr-defined]
        await self.guild_settings.prepare_currency(guild.id)
        event_cfg = await self.guild_settings.get_event_config(guild.id, settings)
        users, wallets, banks, richest = await self.db.economy_summary(guild.id)
        embed = base_embed("⚙️ Yoru szerverbeállítások")
        embed.add_field(name="💰 Economy", value="✅ Bekapcsolva" if await self.guild_settings.get_economy_enabled(guild.id) else "❌ Kikapcsolva", inline=True)
        eco_channels = await self.guild_settings.get_economy_channel_ids(guild.id)
        eco_categories = await self.guild_settings.get_economy_category_ids(guild.id)
        if eco_channels or eco_categories:
            eco_places = f"{len(eco_channels)} csatorna • {len(eco_categories)} kategória"
        else:
            eco_places = "Minden csatorna"
        embed.add_field(name="💬 Economy helyek", value=eco_places, inline=True)
        embed.add_field(name="🎁 Event csatorna", value=(f"<#{event_cfg.channel_id}>" if event_cfg.channel_id else "Nincs beállítva"), inline=True)
        embed.add_field(name="🤖 Auto event", value="✅ Bekapcsolva" if event_cfg.auto_enabled else "❌ Kikapcsolva", inline=True)
        embed.add_field(name="⏱️ Auto intervallum", value=f"{_duration_label(event_cfg.min_hours)} – {_duration_label(event_cfg.max_hours)}", inline=True)

        event_cog = self.bot.get_cog("EventCog")
        activity_status = None
        if event_cog is not None:
            runtime = getattr(event_cog, "get_runtime_config", None)
            if callable(runtime):
                await runtime(guild.id)
            getter = getattr(event_cog, "get_activity_status", None)
            if callable(getter):
                activity_status = getter(guild.id)
        if activity_status:
            state = "🟢 Felfegyverezve" if activity_status["armed"] else "🟡 Gyűjtés"
            activity_value = (
                f"{state}\n**{activity_status['messages']}/{activity_status['required_messages']}** üzenet • "
                f"**{activity_status['users']}/{activity_status['required_users']}** user\n"
                f"{activity_status['window_minutes']} perc ablak • {activity_status['user_cooldown_seconds']} mp/user"
            )
        else:
            activity_value = f"**{event_cfg.activity_messages}** üzenet • **{event_cfg.activity_min_users}** user\n{event_cfg.activity_window_minutes} perc ablak • {event_cfg.activity_user_cooldown_seconds} mp/user"
        embed.add_field(name="💬 Event aktivitás", value=activity_value, inline=False)
        embed.add_field(name="🎁 Auto Láda", value=f"{money(event_cfg.safe_min_reward)} – {money(event_cfg.safe_max_reward)}", inline=money_inline(event_cfg.safe_min_reward, event_cfg.safe_max_reward))
        embed.add_field(name="☠️ Auto HH belépő", value=f"{money(event_cfg.bomb_min_entry)} – {money(event_cfg.bomb_max_entry)}", inline=money_inline(event_cfg.bomb_min_entry, event_cfg.bomb_max_entry))
        embed.add_field(name="⏳ Nevezési idő", value=f"{event_cfg.join_seconds} mp", inline=True)
        embed.add_field(name="💥 HH köridő", value=f"{event_cfg.bomb_round_seconds} mp", inline=True)
        embed.add_field(name="👥 Economy userek", value=str(users), inline=True)
        embed.add_field(name="💵 Tárcák összesen", value=money(wallets), inline=money_inline(wallets, banks, richest))
        embed.add_field(name="🏦 Bankok összesen", value=money(banks), inline=money_inline(wallets, banks, richest))
        embed.add_field(name="👑 Legnagyobb vagyon", value=money(richest), inline=money_inline(wallets, banks, richest))
        embed.add_field(name="🗄️ Adatbázis", value=f"`{settings.database_path}`", inline=True)
        return embed

    @app_commands.command(name="yoruconfig", description="Yoru gazdasági és eseményállapot (adminisztrátor).")
    @app_commands.checks.has_permissions(administrator=True)
    async def yoruconfig_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.send_message(embed=await self._config_embed(interaction.guild), ephemeral=True)

    @commands.command(name="yoruconfig", aliases=["yc", "config"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def yoruconfig_prefix(self, ctx: commands.Context) -> None:
        await ctx.send(embed=await self._config_embed(ctx.guild))



    @app_commands.command(
        name="gmpilotprobe",
        description="W22.7.1: owner-only Tier-3 live test-guild runtime probe.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def gm_pilot_probe_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez a probe csak szerveren használható.", ephemeral=True)
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Ez a W22.7.1 probe csak a bot tulajdonosának érhető el.", ephemeral=True)

        pilot = getattr(self.bot, "ai_director_game_master", None)
        if pilot is None or not pilot.active_for_guild(interaction.guild.id):
            return await interaction.response.send_message(
                "❌ A Tier-3 pilot ezen a guildon nem aktív. Ellenőrizd a TEST_GUILD_ID, "
                "YORU_AI_DIRECTOR_PILOT_ENABLED és YORU_AI_DIRECTOR_GAME_MASTER_PILOT_ENABLED beállításokat.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        def embed_factory(family: str, pass_index: int) -> discord.Embed:
            embed = base_embed(
                "🧪 W22.7.1 • Tier-3 live runtime probe",
                f"Canonical host probe • `{family}` • pass {pass_index}",
            )
            embed.add_field(name="HOST", value="Canonical host panel intact", inline=False)
            return embed

        report, preview_embeds = await run_live_runtime_probe(
            self.bot, interaction.guild.id, embed_factory=embed_factory
        )
        evidence = report.as_dict()
        metrics = evidence["metrics"]
        passed = sum(1 for value in evidence["checks"].values() if value)
        total = len(evidence["checks"])
        icon = "✅" if report.status == "GO" else "⚠️"

        # First-pass embeds are actually transmitted through Discord so W22.7.1
        # validates the real network/presentation path, not only in-process objects.
        if preview_embeds:
            await interaction.followup.send(embeds=preview_embeds[:10], ephemeral=True)

        payload = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
        file = discord.File(io.BytesIO(payload), filename="YORU_v3.83.15_W22.7.1_LIVE_RUNTIME_PROBE.json")
        await interaction.followup.send(
            f"{icon} **W22.7.1 live runtime probe: {report.status}**\n"
            f"Checks: **{passed}/{total}** • provider: **{metrics.get('provider_attempts', 0)}** "
            f"• AI: **{metrics.get('ai_surfaces', 0)}** • cache: **{metrics.get('cache_hits', 0)}** "
            f"• fallback: **{metrics.get('deterministic_fallbacks', 0)}** "
            f"• integration failure: **{metrics.get('integration_failures', 0)}**\n"
            "Gameplay authority: **NONE** • persistence: **NONE** • production rollout: **NO**",
            file=file,
            ephemeral=True,
        )

    def _economy_reset_block_reason(self, guild_id: int) -> str | None:
        event_cog = self.bot.get_cog("EventCog")
        active_events = getattr(event_cog, "active_events", {}) if event_cog else {}
        if guild_id in active_events:
            return "Fut egy Kincses Láda vagy Hirtelen Halál event. Várd meg, amíg véget ér."

        community = self.bot.get_cog("CommunityCog")
        jackpots = getattr(community, "jackpots", {}) if community else {}
        if guild_id in jackpots:
            return "Fut egy Jackpot kör. Várd meg, amíg véget ér."
        return None

    def _clear_runtime_economy_state(self, guild_id: int) -> None:
        community = self.bot.get_cog("CommunityCog")
        if community is not None:
            black_markets = getattr(community, "black_markets", None)
            if isinstance(black_markets, dict):
                black_markets.pop(guild_id, None)

    async def _perform_economy_reset(self, guild: discord.Guild) -> dict[str, int]:
        result = await self.db.reset_guild_economy(guild.id)
        self._clear_runtime_economy_state(guild.id)
        return result

    async def _perform_economy_rebase(self, guild: discord.Guild) -> dict[str, int]:
        result = await self.db.rebase_guild_economy(guild.id)
        self._clear_runtime_economy_state(guild.id)
        return result

    @app_commands.command(
        name="rebaseeconomy",
        description="Régi gazdasági adatok átvezetése az új pénzskálára, a közösségi aktivitás megtartásával.",
    )
    @app_commands.describe(confirm="A megerősítéshez írd be pontosan: REBASE")
    @app_commands.checks.has_permissions(administrator=True)
    async def rebaseeconomy_slash(self, interaction: discord.Interaction, confirm: str) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez a parancs csak szerveren használható.", ephemeral=True)
        if confirm != "REBASE":
            return await interaction.response.send_message(
                "⚠️ Nem történt átvezetés. A megerősítéshez írd be pontosan: `REBASE`", ephemeral=True
            )
        reason = self._economy_reset_block_reason(interaction.guild.id)
        if reason:
            return await interaction.response.send_message(f"❌ **Az átvezetés most nem indítható.**\n{reason}", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        result = await self._perform_economy_rebase(interaction.guild)
        await interaction.followup.send(
            "✅ **GAZDASÁGI ÁTVEZETÉS KÉSZ**\n"
            "💵 Készpénz: új kezdőegyenleg • Bank és játékbeli fejlődés: újraindítva\n"
            "🎒 Tárgyak, piactér és játékbeli fejlődés: újraindítva\n"
            "🌙 Szervezet tagság megmaradt, Szervezet Közös kassza/működési háttér/hozzájárulás reset\n"
            "📊 A teljes közösségi aktivitási statisztika megmaradt\n"
            "🎁 A közösségi jutalmak és vásárlási előzmények megmaradtak\n"
            f"🧹 Régi gazdasági tranzakciók törölve: **{result.get('transactions', 0)}**",
            ephemeral=True,
        )

    @commands.command(name="rebaseeconomy", aliases=["rebaseeco", "erebase"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def rebaseeconomy_prefix(self, ctx: commands.Context, confirm: str = "") -> None:
        if confirm != "REBASE":
            try:
                await ctx.author.send("⚠️ A gazdasági átvezetéshez használd: `!rebaseeconomy REBASE`")
            except discord.HTTPException:
                pass
            return
        reason = self._economy_reset_block_reason(ctx.guild.id)
        if reason:
            try:
                await ctx.author.send(f"❌ **Az átvezetés most nem indítható.**\n{reason}")
            except discord.HTTPException:
                pass
            return
        result = await self._perform_economy_rebase(ctx.guild)
        try:
            await ctx.author.send(
                "✅ **GAZDASÁGI ÁTVEZETÉS KÉSZ**\n"
                "Készpénz, bank, tárgyak és játékbeli fejlődés újraindítva.\n"
                "A szervezeti tagság, közösségi aktivitás és közösségi jutalmak előzményei megmaradtak.\n"
                f"Régi gazdasági tranzakciók törölve: **{result.get('transactions', 0)}**"
            )
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="reseteconomy",
        description="TELJES játékgazdasági visszaállítás ezen a szerveren. Minden játékosadat törlődik.",
    )
    @app_commands.describe(confirm="A megerősítéshez írd be pontosan: RESET")
    @app_commands.checks.has_permissions(administrator=True)
    async def reseteconomy_slash(self, interaction: discord.Interaction, confirm: str) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez a parancs csak szerveren használható.", ephemeral=True)
        if confirm != "RESET":
            return await interaction.response.send_message(
                "⚠️ **Nem történt visszaállítás.** A teljes játékgazdaság törléséhez a `confirm` mezőbe írd pontosan: `RESET`",
                ephemeral=True,
            )
        reason = self._economy_reset_block_reason(interaction.guild.id)
        if reason:
            return await interaction.response.send_message(f"❌ **A visszaállítás most nem indítható.**\n{reason}", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        result = await self._perform_economy_reset(interaction.guild)
        await interaction.followup.send(
            "✅ **TELJES JÁTÉKGAZDASÁGI VISSZAÁLLÍTÁS KÉSZ**\n"
            f"👥 Törölt játékosprofilok: **{result.get('users', 0)}**\n"
            f"🎒 Tárgysorok: **{result.get('inventory', 0)}**\n"
            f"🏅 Eredmények: **{result.get('achievements', 0)}**\n"            f"🌙 Szervezetk: **{result.get('crews', 0)}** • tagságok: **{result.get('crew_members', 0)}**\n"
            f"📊 Statisztikai sorok: **{result.get('user_statistics', 0)}**\n"
            f"🧾 Tranzakciók: **{result.get('transactions', 0)}**\n"
            "\nMindenki a következő gazdasági parancsnál új játékosként indul. "
            "A kezdő pénzt a `!settings → Gazdaság → Haladó → Kezdő egyenleg` kezeli.",
            ephemeral=True,
        )

    @commands.command(name="reseteconomy", aliases=["reseteco", "economyreset", "ereset"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def reseteconomy_prefix(self, ctx: commands.Context, confirm: str = "") -> None:
        if confirm != "RESET":
            try:
                await ctx.author.send(
                    "⚠️ **Yoru játékgazdasági visszaállítás**\nA teljes játékgazdaság törléséhez használd: `!reseteconomy RESET`"
                )
            except discord.HTTPException:
                pass
            return
        reason = self._economy_reset_block_reason(ctx.guild.id)
        if reason:
            try:
                await ctx.author.send(f"❌ **A visszaállítás most nem indítható.**\n{reason}")
            except discord.HTTPException:
                pass
            return

        result = await self._perform_economy_reset(ctx.guild)
        try:
            await ctx.author.send(
                "✅ **TELJES JÁTÉKGAZDASÁGI VISSZAÁLLÍTÁS KÉSZ**\n"
                f"👥 Törölt játékosprofilok: **{result.get('users', 0)}**\n"
                f"🎒 Tárgysorok: **{result.get('inventory', 0)}**\n"
                f"🏅 Eredmények: **{result.get('achievements', 0)}**\n"                f"🌙 Szervezetk: **{result.get('crews', 0)}** • tagságok: **{result.get('crew_members', 0)}**\n"
                f"🧾 Tranzakciók: **{result.get('transactions', 0)}**\n"
                "Mindenki a következő gazdasági parancsnál új játékosként indul."
            )
        except discord.HTTPException:
            pass
