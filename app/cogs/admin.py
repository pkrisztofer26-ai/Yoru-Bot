from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from app.database import Database
from app.services.economy_events_settings import EconomyEventsSettingsService
from app.ui import base_embed, money


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
        effects = await self.db.list_guild_effects(guild.id)
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
        embed.add_field(name="🎁 Auto Láda", value=f"{money(event_cfg.safe_min_reward)} – {money(event_cfg.safe_max_reward)}", inline=True)
        embed.add_field(name="☠️ Auto HH belépő", value=f"{money(event_cfg.bomb_min_entry)} – {money(event_cfg.bomb_max_entry)}", inline=True)
        embed.add_field(name="⏳ Nevezési idő", value=f"{event_cfg.join_seconds} mp", inline=True)
        embed.add_field(name="💥 HH köridő", value=f"{event_cfg.bomb_round_seconds} mp", inline=True)
        embed.add_field(name="👥 Economy userek", value=str(users), inline=True)
        embed.add_field(name="💵 Tárcák összesen", value=money(wallets), inline=True)
        embed.add_field(name="🏦 Bankok összesen", value=money(banks), inline=True)
        embed.add_field(name="👑 Legnagyobb vagyon", value=money(richest), inline=True)
        embed.add_field(name="⚡ Aktív effektek", value=str(len(effects)), inline=True)
        embed.add_field(name="🗄️ Adatbázis", value=f"`{settings.database_path}`", inline=True)
        return embed

    @app_commands.command(name="yoruconfig", description="Yoru economy és event állapot (admin).")
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

    @commands.command(name="starteffect", aliases=["seffect"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def starteffect(self, ctx: commands.Context, effect: str, multiplier: float = 2.0, minutes: int = 60) -> None:
        aliases = {
            "work": "work_multiplier", "w": "work_multiplier",
            "crime": "crime_multiplier", "cr": "crime_multiplier",
            "luck": "luck_multiplier", "lucky": "luck_multiplier",
        }
        effect_id = aliases.get(effect.lower())
        if effect_id is None:
            return await ctx.send("❌ Effekt: `work`, `crime` vagy `luck`.")
        if multiplier < 1 or multiplier > 5 or minutes < 1 or minutes > 1440:
            return await ctx.send("❌ Szorzó: 1–5, idő: 1–1440 perc.")
        expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await self.db.set_guild_effect(ctx.guild.id, effect_id, multiplier, expires)
        await ctx.send(f"⚡ **{effect} x{multiplier:g}** aktiválva • vége: <t:{int(expires.timestamp())}:R>")

    @commands.command(name="cleareffects", aliases=["ceffects"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def cleareffects(self, ctx: commands.Context) -> None:
        now = datetime.now(timezone.utc) - timedelta(seconds=1)
        for effect_id in ("work_multiplier", "crime_multiplier", "luck_multiplier"):
            await self.db.set_guild_effect(ctx.guild.id, effect_id, 1.0, now)
        await ctx.send("✅ A szerveres economy effektek törölve.")

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
        description="v3.5 economy rebase: új pénzskála, lifetime aktivitás megtartásával.",
    )
    @app_commands.describe(confirm="A megerősítéshez írd be pontosan: REBASE")
    @app_commands.checks.has_permissions(administrator=True)
    async def rebaseeconomy_slash(self, interaction: discord.Interaction, confirm: str) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez a parancs csak szerveren használható.", ephemeral=True)
        if confirm != "REBASE":
            return await interaction.response.send_message(
                "⚠️ Nem történt rebase. A megerősítéshez írd be pontosan: `REBASE`", ephemeral=True
            )
        reason = self._economy_reset_block_reason(interaction.guild.id)
        if reason:
            return await interaction.response.send_message(f"❌ **A rebase most nem indítható.**\n{reason}", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        result = await self._perform_economy_rebase(interaction.guild)
        await interaction.followup.send(
            "✅ **YORU v3.5 ECONOMY REBASE KÉSZ**\n"
            "💵 Wallet: új starter balance • Bank/XP/Prestige: reset\n"
            "🎒 Normál inventory/boosterek/piac/questek: reset\n"
            "🌙 Frakció tagság megmaradt, Frakció bank/infrastructure/contribution reset\n"
            "📊 Lifetime aktivitási count statok megmaradtak\n"
            "🎁 Premium reward item + vásárlási history megmaradt\n"
            f"🧹 Régi economy tranzakciók törölve: **{result.get('transactions', 0)}**",
            ephemeral=True,
        )

    @commands.command(name="rebaseeconomy", aliases=["rebaseeco", "erebase"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def rebaseeconomy_prefix(self, ctx: commands.Context, confirm: str = "") -> None:
        if confirm != "REBASE":
            try:
                await ctx.author.send("⚠️ A v3.5 economy rebase-hez használd: `!rebaseeconomy REBASE`")
            except discord.HTTPException:
                pass
            return
        reason = self._economy_reset_block_reason(ctx.guild.id)
        if reason:
            try:
                await ctx.author.send(f"❌ **A rebase most nem indítható.**\n{reason}")
            except discord.HTTPException:
                pass
            return
        result = await self._perform_economy_rebase(ctx.guild)
        try:
            await ctx.author.send(
                "✅ **YORU v3.5 ECONOMY REBASE KÉSZ**\n"
                "Wallet/starter, bank, XP, prestige és normál inventory újraindítva.\n"
                "Frakció tagság + lifetime activity statok + premium history megmaradt.\n"
                f"Régi economy tranzakciók törölve: **{result.get('transactions', 0)}**"
            )
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="reseteconomy",
        description="TELJES economy reset ezen a szerveren. Minden játékosadat törlődik.",
    )
    @app_commands.describe(confirm="A megerősítéshez írd be pontosan: RESET")
    @app_commands.checks.has_permissions(administrator=True)
    async def reseteconomy_slash(self, interaction: discord.Interaction, confirm: str) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez a parancs csak szerveren használható.", ephemeral=True)
        if confirm != "RESET":
            return await interaction.response.send_message(
                "⚠️ **Nem történt reset.** A teljes economy törléséhez a `confirm` mezőbe írd pontosan: `RESET`",
                ephemeral=True,
            )
        reason = self._economy_reset_block_reason(interaction.guild.id)
        if reason:
            return await interaction.response.send_message(f"❌ **A reset most nem indítható.**\n{reason}", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        result = await self._perform_economy_reset(interaction.guild)
        await interaction.followup.send(
            "✅ **TELJES ECONOMY RESET KÉSZ**\n"
            f"👥 Törölt játékosprofilok: **{result.get('users', 0)}**\n"
            f"🎒 Inventory sorok: **{result.get('inventory', 0)}**\n"
            f"🏅 Achievementek: **{result.get('achievements', 0)}**\n"
            f"🌌 Prestige profilok: **{result.get('user_prestige', 0)}**\n"
            f"🌙 Frakciók: **{result.get('crews', 0)}** • tagságok: **{result.get('crew_members', 0)}**\n"
            f"📊 v3 stat sorok: **{result.get('user_statistics', 0)}**\n"
            f"🧾 Tranzakciók: **{result.get('transactions', 0)}**\n"
            "\nMindenki a következő economy parancsnál új játékosként indul. "
            "A kezdő pénz a `.env` fájl `STARTING_BALANCE` értéke.",
            ephemeral=True,
        )

    @commands.command(name="reseteconomy", aliases=["reseteco", "economyreset", "ereset"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def reseteconomy_prefix(self, ctx: commands.Context, confirm: str = "") -> None:
        if confirm != "RESET":
            try:
                await ctx.author.send(
                    "⚠️ **Yoru Economy Reset**\nA teljes economy törléséhez használd: `!reseteconomy RESET`"
                )
            except discord.HTTPException:
                pass
            return
        reason = self._economy_reset_block_reason(ctx.guild.id)
        if reason:
            try:
                await ctx.author.send(f"❌ **A reset most nem indítható.**\n{reason}")
            except discord.HTTPException:
                pass
            return

        result = await self._perform_economy_reset(ctx.guild)
        try:
            await ctx.author.send(
                "✅ **TELJES ECONOMY RESET KÉSZ**\n"
                f"👥 Törölt játékosprofilok: **{result.get('users', 0)}**\n"
                f"🎒 Inventory sorok: **{result.get('inventory', 0)}**\n"
                f"🏅 Achievementek: **{result.get('achievements', 0)}**\n"
                f"🌌 Prestige profilok: **{result.get('user_prestige', 0)}**\n"
                f"🌙 Frakciók: **{result.get('crews', 0)}** • tagságok: **{result.get('crew_members', 0)}**\n"
                f"🧾 Tranzakciók: **{result.get('transactions', 0)}**\n"
                "Mindenki a következő economy parancsnál új játékosként indul."
            )
        except discord.HTTPException:
            pass

