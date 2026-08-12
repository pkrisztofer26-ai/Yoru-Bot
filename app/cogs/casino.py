from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from app import casino_config as cfg
from app import economy_config as eco
from app.amounts import parse_amount
from app.services.casino import CasinoService
from app.services.gambling import GamblingService
from app.ui import BRAND, GOLD, base_embed, error_embed, money
from app.cogs.access_utils import handle_wrong_gambling_channel
from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.services.server_settings import ServerSettingsService


GAME_LABELS = {
    "blackjack": "🃏 Blackjack",
    "coinflip": "🪙 Coinflip",
    "dice": "🎲 Dice",
    "slots": "🎰 Slots",
    "roulette": "🎡 Roulette",
    "highlow": "📈 High/Low",
    "rps": "✂️ RPS",
    "chickenfight": "🐔 Chicken Fight",
}


def _signed_money(value: int) -> str:
    if value > 0:
        return f"+{money(value)}"
    if value < 0:
        return f"-{money(abs(value))}"
    return money(0)


class CasinoBetModal(discord.ui.Modal):
    def __init__(self, cog: "CasinoCog", game: str) -> None:
        title = "🃏 Blackjack" if game == "blackjack" else "🎰 Slots"
        super().__init__(title=title, timeout=120)
        self.cog = cog
        self.game = game
        self.amount = discord.ui.TextInput(label="Tét", placeholder="pl. 100k, 5m, 1b vagy all", max_length=32)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        gambling_cog = self.cog.bot.get_cog("GamblingCog")
        if gambling_cog is None:
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A gambling modul nem érhető el."), ephemeral=True)
        wallet, _ = await self.cog.casino.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(str(self.amount.value), wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        if self.game == "blackjack":
            await gambling_cog.open_blackjack_interaction(interaction, bet)
        else:
            await gambling_cog.run_slots_interaction(interaction, bet)


class CasinoQuickModal(discord.ui.Modal):
    def __init__(self, cog: "CasinoCog", game: str) -> None:
        titles = {"coinflip":"🪙 Coinflip","dice":"🎲 Dice","highlow":"🃏 High / Low","rps":"✂️ RPS","chicken":"🐔 Chicken Fight"}
        super().__init__(title=titles.get(game, "Casino"), timeout=120)
        self.cog = cog
        self.game = game
        self.amount = discord.ui.TextInput(label="Tét", placeholder="pl. 100k, 5m, 1b vagy all", max_length=32)
        self.add_item(self.amount)
        self.choice = None
        self.guess = None
        if game == "coinflip":
            self.choice = discord.ui.TextInput(label="Oldal", placeholder="fej / írás", max_length=12)
            self.add_item(self.choice)
        elif game == "rps":
            self.choice = discord.ui.TextInput(label="Választás", placeholder="rock / paper / scissors", max_length=16)
            self.add_item(self.choice)
        elif game == "dice":
            self.choice = discord.ui.TextInput(label="Mód", placeholder="exact / high / low / odd / even / over7 / under7 / seven", max_length=16)
            self.guess = discord.ui.TextInput(label="Exact tipp", placeholder="1–6 (csak exact módnál)", required=False, max_length=2)
            self.add_item(self.choice); self.add_item(self.guess)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        wallet, _ = await self.cog.casino.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(str(self.amount.value), wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        gambling = self.cog.bot.get_cog("GamblingCog")
        extras = self.cog.bot.get_cog("ExtrasCog")
        if self.game == "coinflip":
            if gambling is None: return await interaction.response.send_message("❌ Gambling modul nem elérhető.", ephemeral=True)
            return await gambling.run_coinflip_interaction(interaction, str(self.choice.value), bet)
        if self.game == "dice":
            if gambling is None: return await interaction.response.send_message("❌ Gambling modul nem elérhető.", ephemeral=True)
            guess = None
            if str(self.guess.value).strip():
                try: guess = int(str(self.guess.value).strip())
                except ValueError: return await interaction.response.send_message("❌ Az exact tipp 1–6 legyen.", ephemeral=True)
            return await gambling.run_dice_interaction(interaction, str(self.choice.value), bet, guess)
        if extras is None:
            return await interaction.response.send_message("❌ Extras modul nem elérhető.", ephemeral=True)
        if self.game == "highlow": return await extras.start_highlow_interaction(interaction, bet)
        if self.game == "rps": return await extras.run_rps_interaction(interaction, str(self.choice.value), bet)
        return await extras.run_chicken_interaction(interaction, bet)


class CasinoLobbyView(discord.ui.View):
    def __init__(self, cog: "CasinoCog", owner_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a Casino panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Blackjack", emoji="🃏", style=discord.ButtonStyle.primary, row=0)
    async def blackjack(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoBetModal(self.cog, "blackjack"))

    @discord.ui.button(label="Slots", emoji="🎰", style=discord.ButtonStyle.primary, row=0)
    async def slots(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoBetModal(self.cog, "slots"))

    @discord.ui.button(label="Roulette", emoji="🎡", style=discord.ButtonStyle.success, row=0)
    async def roulette(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        gambling_cog = self.cog.bot.get_cog("GamblingCog")
        if gambling_cog is None:
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A gambling modul nem érhető el."), ephemeral=True)
        await gambling_cog.open_roulette_interaction(interaction)

    @discord.ui.button(label="Coinflip", emoji="🪙", style=discord.ButtonStyle.secondary, row=1)
    async def coinflip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "coinflip"))

    @discord.ui.button(label="Dice", emoji="🎲", style=discord.ButtonStyle.secondary, row=1)
    async def dice(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "dice"))

    @discord.ui.button(label="High/Low", emoji="📈", style=discord.ButtonStyle.secondary, row=1)
    async def highlow(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "highlow"))

    @discord.ui.button(label="RPS", emoji="✂️", style=discord.ButtonStyle.secondary, row=1)
    async def rps(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "rps"))

    @discord.ui.button(label="Chicken", emoji="🐔", style=discord.ButtonStyle.secondary, row=1)
    async def chicken(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "chicken"))

    @discord.ui.button(label="Statisztika", emoji="📊", style=discord.ButtonStyle.secondary, row=2)
    async def stats(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = await self.cog.stats_embed(interaction.guild_id, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Előzmények", emoji="📜", style=discord.ButtonStyle.secondary, row=2)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = await self.cog.history_embed(interaction.guild_id, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Monthly Jackpot", emoji="💰", style=discord.ButtonStyle.secondary, row=2)
    async def jackpot(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = await self.cog.jackpot_embed(interaction.guild_id, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Lottery", emoji="🎟️", style=discord.ButtonStyle.secondary, row=2)
    async def lottery(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.lottery_embed(interaction.guild_id, interaction.user), view=LotteryView(self.cog, self.owner_id))

    @discord.ui.button(label="Casino főoldal", emoji="🏠", style=discord.ButtonStyle.secondary, row=3)
    async def home(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        embed = await self.cog.lobby_embed(interaction.guild_id, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)


class LotteryView(discord.ui.View):
    def __init__(self, cog: "CasinoCog", owner_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ezt a Lottery panelt nem te nyitottad meg.", ephemeral=True)
            return False
        return True

    async def _buy(self, interaction: discord.Interaction, count: int) -> None:
        community = self.cog.bot.get_cog("CommunityCog")
        if community is None or interaction.guild_id is None:
            return await interaction.response.send_message("❌ A Lottery modul nem elérhető.", ephemeral=True)
        try:
            await community._buy_lottery(interaction.guild_id, interaction.user.id, count, interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.edit_message(embed=await self.cog.lottery_embed(interaction.guild_id, interaction.user), view=self)

    @discord.ui.button(label="+1", emoji="🎟️", style=discord.ButtonStyle.secondary, row=0)
    async def one(self, interaction: discord.Interaction, _: discord.ui.Button) -> None: await self._buy(interaction, 1)
    @discord.ui.button(label="+5", emoji="🎟️", style=discord.ButtonStyle.secondary, row=0)
    async def five(self, interaction: discord.Interaction, _: discord.ui.Button) -> None: await self._buy(interaction, 5)
    @discord.ui.button(label="+10", emoji="🎟️", style=discord.ButtonStyle.primary, row=0)
    async def ten(self, interaction: discord.Interaction, _: discord.ui.Button) -> None: await self._buy(interaction, 10)
    @discord.ui.button(label="+50", emoji="🎟️", style=discord.ButtonStyle.success, row=0)
    async def fifty(self, interaction: discord.Interaction, _: discord.ui.Button) -> None: await self._buy(interaction, 50)

    @discord.ui.button(label="Casino főoldal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.lobby_embed(interaction.guild_id, interaction.user), view=CasinoLobbyView(self.cog, self.owner_id))


CASINO_LOG_CHANNEL_KEY = "casino_log_channel_id"


class CasinoSettingsView(OwnedView):
    def __init__(self, cog: "CasinoCog", owner_id: int) -> None:
        super().__init__(cog, owner_id)
        self.channel_page = 0

    def add_channel_selector(self, guild: discord.Guild) -> None:
        self.add_item(PagedGuildChannelSelect(
            self, guild,
            page_attr="channel_page",
            selection_key="casino_log",
            placeholder="Casino log csatorna…",
            channel_types=(discord.ChannelType.text, discord.ChannelType.news),
            row=1,
        ))

    async def refresh(self, interaction: discord.Interaction) -> None:
        await self.cog.show_settings(interaction, self.owner_id, channel_page=self.channel_page)

    async def handle_channel_selection(self, interaction: discord.Interaction, selection_key: str, channels: list[discord.abc.GuildChannel]) -> None:
        if interaction.guild_id is None or not channels:
            return
        await self.cog.settings.set_int(interaction.guild_id, CASINO_LOG_CHANNEL_KEY, channels[0].id)
        await self.cog.show_settings(interaction, self.owner_id)

    @discord.ui.button(label="Log kikapcsolása", emoji="🧹", style=discord.ButtonStyle.danger, row=0)
    async def clear_log(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild_id is None:
            return
        await self.cog.settings.set_int(interaction.guild_id, CASINO_LOG_CHANNEL_KEY, None)
        await self.cog.show_settings(interaction, self.owner_id)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        settings_cog = self.cog.bot.get_cog("SettingsCog")
        if settings_cog is None:
            return await interaction.response.send_message("❌ A settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, self.owner_id)


class CasinoCog(commands.GroupCog, group_name="casino", group_description="Yoru Casino lobby, játékok, statok és előzmények."):
    def __init__(self, bot: commands.Bot, casino: CasinoService, gambling: GamblingService | None = None) -> None:
        self.bot = bot
        self.casino = casino
        self.gambling = gambling
        self.settings = getattr(casino.guild_settings, "state", ServerSettingsService(casino.db))
        self.casino.set_settlement_listener(self._log_settlement)
        self._jackpot_task: asyncio.Task | None = None
        super().__init__()

    async def cog_load(self) -> None:
        self._jackpot_task = asyncio.create_task(self._jackpot_loop())

    async def cog_unload(self) -> None:
        if self._jackpot_task:
            self._jackpot_task.cancel()

    async def _jackpot_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self._process_pending_jackpots()
            except Exception:
                pass
            await asyncio.sleep(max(60, int(cfg.MONTHLY_JACKPOT_CHECK_SECONDS)))

    async def _process_pending_jackpots(self) -> None:
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        for guild in list(self.bot.guilds):
            months = await self.casino.pending_jackpot_months(guild.id, current_month)
            for month in months:
                eligible = await self.casino.jackpot_eligible(guild.id, month)
                winner_id = random.choice(eligible)["user_id"] if eligible else None
                result = await self.casino.finalize_jackpot(
                    guild.id, month, winner_id=winner_id, eligible_players=len(eligible), rollover_month=current_month,
                )
                if not result.get("idempotent"):
                    await self._announce_jackpot(guild, result)

    async def _announce_jackpot(self, guild: discord.Guild, result: dict) -> None:
        channel = None
        try:
            event_cfg = await self.casino.guild_settings.get_event_config(guild.id, self.bot.settings)
            if event_cfg.channel_id:
                candidate = guild.get_channel(event_cfg.channel_id)
                if isinstance(candidate, discord.TextChannel): channel = candidate
        except Exception:
            pass
        if channel is None:
            cid = await self.settings.get_int(guild.id, CASINO_LOG_CHANNEL_KEY)
            candidate = guild.get_channel(cid) if cid else None
            if isinstance(candidate, discord.TextChannel): channel = candidate
        if channel is None:
            return
        if result.get("outcome") == "draw" and result.get("winner_id"):
            embed = base_embed("👑 MONTHLY JACKPOT WINNER", f"<@{result['winner_id']}>\n\n💰 **{money(int(result.get('payout',0)))}**", GOLD)
            embed.add_field(name="Hónap", value=f"**{result['month']}**", inline=True)
            embed.add_field(name="Jogosult játékosok", value=f"**{result.get('eligible_players',0)}**", inline=True)
        else:
            embed = base_embed("💰 Monthly Jackpot rollover", f"A **{result['month']}** havi pool továbbgördült, mert nem volt jogosult játékos.", GOLD)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    async def _log_settlement(self, settlement) -> None:
        row = await self.casino.db.get_casino_session(settlement.game_id)
        if not row:
            return
        guild_id = int(row["guild_id"])
        channel_id = await self.settings.get_int(guild_id, CASINO_LOG_CHANNEL_KEY)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            return
        user_id = int(row["user_id"])
        label = GAME_LABELS.get(settlement.game, settlement.game.title())
        embed = base_embed("🧾 Yoru Casino Log", f"**{label}** lezárva", BRAND)
        embed.add_field(name="Game ID", value=f"`{settlement.game_id}`", inline=True)
        embed.add_field(name="Játékos", value=f"<@{user_id}>\n`{user_id}`", inline=True)
        embed.add_field(name="Eredmény", value=str(settlement.result)[:1024] or "—", inline=False)
        embed.add_field(name="Tét", value=f"**{money(settlement.bet)}**", inline=True)
        embed.add_field(name="Kifizetés", value=f"**{money(settlement.payout)}**", inline=True)
        embed.add_field(name="P/L", value=f"**{_signed_money(settlement.profit)}**", inline=True)
        embed.add_field(name="Multiplier", value=f"**x{settlement.multiplier:.2f}**", inline=True)
        if settlement.jackpot_contribution:
            embed.add_field(name="Jackpot", value=f"**+{money(settlement.jackpot_contribution)}**", inline=True)
        embed.set_footer(text="Yoru • belső casino audit")
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def settings_embed(self, guild: discord.Guild) -> discord.Embed:
        channel_id = await self.settings.get_int(guild.id, CASINO_LOG_CHANNEL_KEY)
        channel = guild.get_channel(channel_id) if channel_id else None
        embed = base_embed("🎰 Casino beállítások", "A játékos UI nem mutat belső Game ID-ket; az audit külön log csatornába kerül.", BRAND)
        embed.add_field(name="🧾 Casino log", value=channel.mention if channel else "**Nincs beállítva**", inline=False)
        embed.add_field(name="Mit ment?", value="Game ID • játékos • játék • tét • payout • P/L • multiplier • eredmény", inline=False)
        embed.set_footer(text="Yoru • Casino audit")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, *, channel_page: int = 0) -> None:
        if interaction.guild is None:
            return
        view = CasinoSettingsView(self, owner_id)
        view.channel_page = max(0, int(channel_page))
        view.add_channel_selector(interaction.guild)
        await interaction.response.edit_message(embed=await self.settings_embed(interaction.guild), view=view)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return False
        try:
            await self.casino.guild_settings.prepare_currency(interaction.guild_id)
            await self.casino.guild_settings.require_feature(interaction.guild_id, "gambling")
            await self.casino.guild_settings.require_channel(
                interaction.guild_id,
                interaction.channel_id,
                getattr(interaction.channel, "category_id", None),
            )
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            return False
        return True

    async def lobby_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        wallet, _ = await self.casino.db.get_balance(guild_id, user.id)
        summary = await self.casino.summary(guild_id, user.id)
        jackpot = await self.casino.monthly_jackpot(guild_id, user.id)
        embed = base_embed(
            "🎰 YORU CASINO",
            "Válassz játékot. A játékfelületek a játékmenetet helyezik előtérbe; a statok csak kiegészítő HUD-ként jelennek meg.",
            BRAND,
        )
        embed.set_author(name=getattr(user, "display_name", user.name), icon_url=getattr(getattr(user, "display_avatar", None), "url", None))
        embed.add_field(name="💵 Wallet", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="📆 Havi P/L", value=f"**{_signed_money(summary['month_profit'])}**", inline=True)
        embed.add_field(name="🎮 Havi játék", value=f"**{summary['month_games']}**", inline=True)
        embed.add_field(name="💰 Monthly Jackpot", value=f"**{money(jackpot['pool'])}**", inline=True)
        embed.add_field(name="🧾 Saját hozzájárulás", value=f"**{money(jackpot['user_contributed'])}**", inline=True)
        embed.add_field(
            name="🎮 Játékok",
            value=(
                "🃏 **Blackjack** — Hit • Stand • Double • Split • Insurance\n"
                "🎰 **Slots** — 5×3 vizuális gép • Wild • Scatter • Free Spins\n"
                "🎡 **Roulette** — egyéni európai kerék • multi-bet\n"
                "🪙 **Coinflip** • 🎲 **Dice** több móddal • 🃏 **High/Low** streak + cashout\n"
                "✂️ **RPS** • 🐔 **Chicken Fight** animált harc"
            ),
            inline=False,
        )
        embed.add_field(name="⌨️ Shortcutok", value="`!bj <tét>` • `!sl <tét>` • `!r` • `!cf fej <tét>` • `!dice odd <tét>` • `!hl <tét>` • `!rps rock <tét>` • `!cock <tét>`", inline=False)
        embed.set_footer(text="Yoru • Casino")
        return embed

    async def stats_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        s = await self.casino.summary(guild_id, user.id)
        embed = base_embed("📊 Casino statisztika", "A Casino ledger alapján számolt összesített statok.", BRAND)
        embed.set_author(name=getattr(user, "display_name", user.name), icon_url=getattr(getattr(user, "display_avatar", None), "url", None))
        embed.add_field(name="🎮 Games", value=f"**{s['games']}**", inline=True)
        embed.add_field(name="✅ / ❌ / 🤝", value=f"**{s['wins']} / {s['losses']} / {s['pushes']}**", inline=True)
        embed.add_field(name="📆 Havi games", value=f"**{s['month_games']}**", inline=True)
        embed.add_field(name="🎟️ Total wagered", value=f"**{money(s['wagered'])}**", inline=True)
        embed.add_field(name="💸 Total payout", value=f"**{money(s['payout'])}**", inline=True)
        embed.add_field(name="📈 Nettó P/L", value=f"**{_signed_money(s['profit'])}**", inline=True)
        embed.add_field(name="🐋 Legnagyobb tét", value=f"**{money(s['biggest_bet'])}**", inline=True)
        embed.add_field(name="🏆 Legnagyobb profit", value=f"**{money(s['biggest_win'])}**", inline=True)
        embed.add_field(name="✖️ Legnagyobb multiplier", value=f"**x{s['highest_multiplier']:.2f}**", inline=True)
        embed.set_footer(text="Yoru • Casino")
        return embed

    async def history_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        rows = await self.casino.history(guild_id, user.id, limit=cfg.CASINO_HISTORY_PAGE_SIZE)
        embed = base_embed("📜 Casino előzmények", "A legutóbbi auditált Casino köreid.", BRAND)
        if not rows:
            embed.description = "Még nincs Casino előzményed."
            return embed
        lines: list[str] = []
        for row in rows:
            label = GAME_LABELS.get(row["game"], row["game"])
            try:
                stamp = int(datetime.fromisoformat(row["created_at"]).timestamp())
                when = f"<t:{stamp}:R>"
            except ValueError:
                when = "—"
            lines.append(
                f"**{label}** • {when}\n"
                f"Tét {money(row['bet'])} • P/L **{_signed_money(row['profit'])}** • x{row['multiplier']:.2f}"
            )
        embed.description = "\n\n".join(lines)
        embed.set_footer(text="Yoru • Casino előzmények")
        return embed

    async def jackpot_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        j = await self.casino.monthly_jackpot(guild_id, user.id)
        summary = await self.casino.summary(guild_id, user.id)
        history = await self.casino.jackpot_history(guild_id, cfg.MONTHLY_JACKPOT_HISTORY_LIMIT)
        eligible = summary["month_games"] >= cfg.MONTHLY_JACKPOT_MIN_GAMES or summary["month_wagered"] >= cfg.MONTHLY_JACKPOT_MIN_WAGER
        now = datetime.now(timezone.utc)
        if now.month == 12: next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else: next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        embed = base_embed("💰 MONTHLY GLOBAL JACKPOT", "A house-game veszteségek egy része automatikusan a havi közösségi poolba kerül.", GOLD)
        embed.add_field(name="🏦 Aktuális pool", value=f"# **{money(j['pool'])}**", inline=False)
        embed.add_field(name="⏳ Következő húzás", value=f"<t:{int(next_month.timestamp())}:R>", inline=True)
        embed.add_field(name="👤 Jogosultság", value=("✅ **Jogosult vagy**" if eligible else f"❌ {summary['month_games']}/{cfg.MONTHLY_JACKPOT_MIN_GAMES} game • {money(summary['month_wagered'])}/{money(cfg.MONTHLY_JACKPOT_MIN_WAGER)} wager"), inline=False)
        embed.add_field(name="🧾 Saját hozzájárulás", value=f"**{money(j['user_contributed'])}**", inline=True)
        embed.add_field(name="📉 Havi house loss", value=f"**{money(j['total_house_loss'])}**", inline=True)
        if history:
            lines=[]
            for item in history[:5]:
                if item['outcome']=='draw' and item['winner_id']:
                    lines.append(f"**{item['month']}** • <@{item['winner_id']}> • **{money(item['payout'])}**")
                else:
                    lines.append(f"**{item['month']}** • rollover")
            embed.add_field(name="📜 Előzmények", value="\n".join(lines), inline=False)
        embed.set_footer(text="Yoru • minden jogosult játékos azonos eséllyel indul")
        return embed

    async def lottery_embed(self, guild_id: int, user: discord.abc.User) -> discord.Embed:
        community = self.bot.get_cog("CommunityCog")
        if community is None:
            return base_embed("🎟️ YORU LOTTERY", "A Lottery modul nem érhető el.", GOLD)
        entries = await self.casino.db.get_lottery_entries(guild_id)
        total_tickets = sum(int(t) for _, t in entries)
        own = next((int(t) for uid, t in entries if int(uid) == int(user.id)), 0)
        pot = int(total_tickets * community.LOTTERY_TICKET_PRICE * eco.LOTTERY_PAYOUT_SHARE)
        history = await self.casino.db.get_lottery_history(guild_id, 1)
        embed = base_embed("🎟️ YORU LOTTERY", "Kisebb, gyakrabban húzott ticket-alapú játék. A Monthly Jackpot ettől teljesen külön rendszer.", GOLD)
        embed.set_author(name=getattr(user, "display_name", user.name), icon_url=getattr(getattr(user, "display_avatar", None), "url", None))
        embed.add_field(name="💰 Aktuális pot", value=f"# **{money(pot)}**", inline=False)
        embed.add_field(name="🎟️ Összes jegy", value=f"**{total_tickets}**", inline=True)
        embed.add_field(name="👤 Saját jegy", value=f"**{own}**", inline=True)
        embed.add_field(name="💵 Jegyár", value=f"**{money(community.LOTTERY_TICKET_PRICE)}**", inline=True)
        embed.add_field(name="⏳ Következő húzás", value=f"<t:{int(community.next_lottery_at.timestamp())}:R>", inline=False)
        if history:
            last=history[0]
            embed.add_field(name="🏆 Legutóbbi nyertes", value=f"<@{last['winner_id']}> • **{money(last['payout'])}**", inline=False)
        embed.set_footer(text="Yoru • Lottery")
        return embed

    @app_commands.command(name="lobby", description="Megnyitja a Yoru Casino főoldalát.")
    async def lobby(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(embed=await self.lobby_embed(interaction.guild_id, interaction.user), view=CasinoLobbyView(self, interaction.user.id))

    @app_commands.command(name="blackjack", description="Blackjack indítása a Casino menüből.")
    @app_commands.describe(osszeg="Tét: 100k, 5m, 1b vagy all")
    async def blackjack(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction):
            return
        gambling_cog = self.bot.get_cog("GamblingCog")
        if gambling_cog is None:
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A gambling modul nem érhető el."), ephemeral=True)
        wallet, _ = await self.casino.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(osszeg, wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await gambling_cog.open_blackjack_interaction(interaction, bet)

    @app_commands.command(name="slots", description="Slots indítása a Casino menüből.")
    @app_commands.describe(osszeg="Tét: 100k, 5m, 1b vagy all")
    async def slots(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction):
            return
        gambling_cog = self.bot.get_cog("GamblingCog")
        if gambling_cog is None:
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A gambling modul nem érhető el."), ephemeral=True)
        wallet, _ = await self.casino.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(osszeg, wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        await gambling_cog.run_slots_interaction(interaction, bet)

    @app_commands.command(name="roulette", description="Megnyitja a saját Roulette asztalodat.")
    async def roulette(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        gambling_cog = self.bot.get_cog("GamblingCog")
        if gambling_cog is None:
            return await interaction.response.send_message(embed=error_embed(interaction.user, "A gambling modul nem érhető el."), ephemeral=True)
        await gambling_cog.open_roulette_interaction(interaction)

    @app_commands.command(name="coinflip", description="Coinflip indítása.")
    @app_commands.choices(oldal=[app_commands.Choice(name="Fej", value="fej"), app_commands.Choice(name="Írás", value="írás")])
    async def coinflip_game(self, interaction: discord.Interaction, oldal: app_commands.Choice[str], osszeg: str) -> None:
        if not await self._guard(interaction): return
        gambling=self.bot.get_cog("GamblingCog"); wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await gambling.run_coinflip_interaction(interaction,oldal.value,bet)

    @app_commands.command(name="dice", description="Dice indítása több játékmóddal.")
    async def dice_game(self, interaction: discord.Interaction, mod: str, osszeg: str, tipped: app_commands.Range[int,1,6] | None = None) -> None:
        if not await self._guard(interaction): return
        gambling=self.bot.get_cog("GamblingCog"); wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await gambling.run_dice_interaction(interaction,mod,bet,int(tipped) if tipped is not None else None)

    @app_commands.command(name="highlow", description="High / Low streak + cashout játék.")
    async def highlow_game(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction): return
        extras=self.bot.get_cog("ExtrasCog"); wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await extras.start_highlow_interaction(interaction,bet)

    @app_commands.command(name="rps", description="RPS Yoru ellen.")
    async def rps_game(self, interaction: discord.Interaction, valasztas: str, osszeg: str) -> None:
        if not await self._guard(interaction): return
        extras=self.bot.get_cog("ExtrasCog"); wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await extras.run_rps_interaction(interaction,valasztas,bet)

    @app_commands.command(name="chicken", description="Chicken Fight indítása.")
    async def chicken_game(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction): return
        extras=self.bot.get_cog("ExtrasCog"); wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await extras.run_chicken_interaction(interaction,bet)

    @app_commands.command(name="lottery", description="Megnyitja a Yoru Lottery panelt.")
    async def lottery_game(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction): return
        await interaction.response.send_message(embed=await self.lottery_embed(interaction.guild_id, interaction.user), view=LotteryView(self, interaction.user.id))

    @app_commands.command(name="stats", description="Megmutatja a Casino statisztikáidat.")
    async def stats(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(embed=await self.stats_embed(interaction.guild_id, interaction.user), view=CasinoLobbyView(self, interaction.user.id))

    @app_commands.command(name="history", description="Megmutatja a legutóbbi Casino köreidet.")
    async def history(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(embed=await self.history_embed(interaction.guild_id, interaction.user), view=CasinoLobbyView(self, interaction.user.id))

    @app_commands.command(name="jackpot", description="Megmutatja a Monthly Global Jackpot poolját.")
    async def jackpot(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(embed=await self.jackpot_embed(interaction.guild_id, interaction.user), view=CasinoLobbyView(self, interaction.user.id))

    @commands.command(name="casino", aliases=["kaszino", "kaszinó"])
    @commands.guild_only()
    async def casino_prefix(self, ctx: commands.Context) -> None:
        try:
            await self.casino.guild_settings.prepare_currency(ctx.guild.id)
            await self.casino.guild_settings.require_feature(ctx.guild.id, "gambling")
        except ValueError as exc:
            return await ctx.send(embed=error_embed(ctx.author, str(exc)))
        try:
            await self.casino.guild_settings.require_channel(ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None))
        except ValueError:
            await handle_wrong_gambling_channel(ctx, self.casino)
            return
        await ctx.send(embed=await self.lobby_embed(ctx.guild.id, ctx.author), view=CasinoLobbyView(self, ctx.author.id))
