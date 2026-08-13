from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import asyncio
import contextlib
import random

import discord
from discord import app_commands
from discord.ext import commands

from app import casino_config as cfg
from app.amounts import parse_amount
from app.services.casino import CasinoService, CasinoSession
from app.services.gambling import GamblingService
from app.ui import BRAND, GOLD, SUCCESS, DANGER, base_embed, error_embed, money
from app.cogs.access_utils import handle_wrong_gambling_channel
from app.cogs.settings import OwnedView, PagedGuildChannelSelect
from app.gamble_rooms import gamble_room_name, gamble_room_owner, is_gamble_room, make_gamble_room_topic, private_room_overwrites
from app.services.server_settings import ServerSettingsService
from app.casino_expansion import (
    MINES_ALLOWED_COUNTS, MinesState, ChickenRoadState,
    new_mines_state, reveal_mines_cell, advance_chicken, run_plinko, run_candy_rush,
)
from app.casino_expansion_visuals import (
    render_mines, render_mines_transition,
    render_chicken_road, render_chicken_road_transition,
    render_plinko, render_plinko_panel, render_plinko_round_media,
    plinko_animation_duration_seconds,
    render_candy_rush, render_candy_rush_animation,
)
from app.casino_ui_framework import adjust_bet, compact_amount


GAME_LABELS = {
    "blackjack": "🃏 Blackjack",
    "coinflip": "🪙 Coinflip",
    "dice": "🎲 Dice",
    "slots": "🎰 Slots",
    "roulette": "🎡 Roulette",
    "highlow": "📈 High/Low",
    "rps": "✂️ RPS",
    "chickenfight": "🐔 Chicken Fight",
    "mines": "💣 Mines",
    "chickenroad": "🐔 Chicken Road",
    "plinko": "🔵 Plinko",
    "candyrush": "🍬 Candy Rush",
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


class CasinoExpansionModal(discord.ui.Modal):
    def __init__(self, cog: "CasinoCog", game: str) -> None:
        titles = {
            "mines": "💣 Mines",
            "chickenroad": "🐔 Chicken Road",
            "plinko": "🔵 Plinko",
            "candyrush": "🍬 Candy Rush",
        }
        super().__init__(title=titles.get(game, "Casino Expansion"), timeout=180)
        self.cog = cog
        self.game = game
        self.amount = discord.ui.TextInput(label="Tét", placeholder="pl. 100k, 5m, 1b vagy all", max_length=32)
        self.add_item(self.amount)
        self.option = None
        if game == "mines":
            self.option = discord.ui.TextInput(label="Bombák", placeholder="3 / 5 / 7 / 9", default="3", max_length=2)
            self.add_item(self.option)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        wallet, _ = await self.cog.casino.db.get_balance(interaction.guild_id, interaction.user.id)
        try:
            bet = parse_amount(str(self.amount.value), wallet)
        except ValueError as exc:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
        if self.game == "mines":
            try:
                mines = int(str(self.option.value).strip())
            except ValueError:
                return await interaction.response.send_message("❌ Bombák: 3 / 5 / 7 / 9.", ephemeral=True)
            return await self.cog.start_mines_interaction(interaction, bet, mines)
        if self.game == "chickenroad":
            return await self.cog.start_chicken_road_interaction(interaction, bet)
        if self.game == "plinko":
            return await self.cog.open_plinko_interaction(interaction, bet)
        return await self.cog.run_candy_rush_interaction(interaction, bet)


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

    @discord.ui.button(label="Mines", emoji="💣", style=discord.ButtonStyle.primary, row=0)
    async def mines(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoExpansionModal(self.cog, "mines"))

    @discord.ui.button(label="Chicken Road", emoji="🐔", style=discord.ButtonStyle.primary, row=0)
    async def chicken_road(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoExpansionModal(self.cog, "chickenroad"))

    @discord.ui.button(label="Plinko", emoji="🔵", style=discord.ButtonStyle.primary, row=1)
    async def plinko(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoExpansionModal(self.cog, "plinko"))

    @discord.ui.button(label="Candy Rush", emoji="🍬", style=discord.ButtonStyle.primary, row=1)
    async def candy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoExpansionModal(self.cog, "candyrush"))

    @discord.ui.button(label="Coinflip", emoji="🪙", style=discord.ButtonStyle.secondary, row=1)
    async def coinflip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "coinflip"))

    @discord.ui.button(label="Dice", emoji="🎲", style=discord.ButtonStyle.secondary, row=1)
    async def dice(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "dice"))

    @discord.ui.button(label="High/Low", emoji="📈", style=discord.ButtonStyle.secondary, row=1)
    async def highlow(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "highlow"))

    @discord.ui.button(label="RPS", emoji="✂️", style=discord.ButtonStyle.secondary, row=2)
    async def rps(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "rps"))

    @discord.ui.button(label="Chicken Fight", emoji="🐔", style=discord.ButtonStyle.secondary, row=2)
    async def chicken(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(CasinoQuickModal(self.cog, "chicken"))

    @discord.ui.button(label="Lottery", emoji="🎟️", style=discord.ButtonStyle.secondary, row=2)
    async def lottery(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.lottery_embed(interaction.guild_id, interaction.user), view=LotteryView(self.cog, self.owner_id))

    @discord.ui.button(label="Statisztika", emoji="📊", style=discord.ButtonStyle.secondary, row=2)
    async def stats(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.stats_embed(interaction.guild_id, interaction.user), view=self)

    @discord.ui.button(label="Előzmények", emoji="📜", style=discord.ButtonStyle.secondary, row=2)
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.history_embed(interaction.guild_id, interaction.user), view=self)

    @discord.ui.button(label="Monthly Jackpot", emoji="💰", style=discord.ButtonStyle.secondary, row=3)
    async def jackpot(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.jackpot_embed(interaction.guild_id, interaction.user), view=self)

    @discord.ui.button(label="Casino főoldal", emoji="🏠", style=discord.ButtonStyle.secondary, row=3)
    async def home(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await self.cog.lobby_embed(interaction.guild_id, interaction.user), view=self)


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


class CasinoTuningModal(discord.ui.Modal, title="Casino • Balance / Jackpot"):
    min_bet = discord.ui.TextInput(label="Minimum tét", placeholder="5000", max_length=30)
    min_games = discord.ui.TextInput(label="Jackpot minimum játék", placeholder="25", max_length=12)
    min_wager = discord.ui.TextInput(label="Jackpot minimum wager", placeholder="250k", max_length=30)
    contribution = discord.ui.TextInput(label="Jackpot hozzájárulás %", placeholder="2", max_length=10)
    payout = discord.ui.TextInput(label="Jackpot payout %", placeholder="100", max_length=10)

    def __init__(self, view: "CasinoSettingsView", runtime) -> None:
        super().__init__(timeout=300)
        self.parent_view = view
        self.min_bet.default = str(runtime.min_bet)
        self.min_games.default = str(runtime.jackpot_min_games)
        self.min_wager.default = str(runtime.jackpot_min_wager)
        self.contribution.default = f"{runtime.jackpot_contribution_rate * 100:g}"
        self.payout.default = f"{runtime.jackpot_payout_share * 100:g}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.parent_view.cog.casino.gameplay_settings.set_casino(
                interaction.guild_id,
                min_bet=parse_amount(str(self.min_bet.value)),
                jackpot_min_games=int(str(self.min_games.value).strip()),
                jackpot_min_wager=parse_amount(str(self.min_wager.value)),
                jackpot_contribution_rate=float(str(self.contribution.value).replace(",", ".")) / 100.0,
                jackpot_payout_share=float(str(self.payout.value).replace(",", ".")) / 100.0,
            )
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.defer()
        await self.parent_view.cog.show_settings(interaction, self.parent_view.owner_id, channel_page=self.parent_view.channel_page)


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
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.cog.show_settings(interaction, self.owner_id, channel_page=self.channel_page)

    async def handle_channel_selection(self, interaction: discord.Interaction, selection_key: str, channels: list[discord.abc.GuildChannel]) -> None:
        if interaction.guild_id is None or not channels:
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.cog.settings.set_int(interaction.guild_id, CASINO_LOG_CHANNEL_KEY, channels[0].id)
        await self.cog.show_settings(interaction, self.owner_id, channel_page=self.channel_page)

    @discord.ui.button(label="Balance / Jackpot", emoji="🎚️", style=discord.ButtonStyle.primary, row=0)
    async def tuning(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        runtime = await self.cog.casino.gameplay_settings.casino(interaction.guild_id)
        await interaction.response.send_modal(CasinoTuningModal(self, runtime))

    @discord.ui.button(label="Default balance", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def reset_tuning(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self.cog.casino.gameplay_settings.reset_casino(interaction.guild_id)
        await self.cog.show_settings(interaction, self.owner_id, channel_page=self.channel_page)

    @discord.ui.button(label="Log kikapcsolása", emoji="🧹", style=discord.ButtonStyle.danger, row=0)
    async def clear_log(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild_id is None:
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.cog.settings.set_int(interaction.guild_id, CASINO_LOG_CHANNEL_KEY, None)
        await self.cog.show_settings(interaction, self.owner_id, channel_page=self.channel_page)

    @discord.ui.button(label="Vissza", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        settings_cog = self.cog.bot.get_cog("SettingsCog")
        if settings_cog is None:
            return await interaction.response.send_message("❌ A settings modul nem elérhető.", ephemeral=True)
        await settings_cog.show_home(interaction, self.owner_id)


class GambleRoomPanelView(discord.ui.View):
    def __init__(self, cog: "CasinoCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Privát gamble szoba", emoji="🎰", style=discord.ButtonStyle.success,
        custom_id="yoru:gamble-room:create",
    )
    async def create_room(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Ez csak szerveren használható.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.create_private_gamble_room(interaction)


class GambleRoomCloseView(discord.ui.View):
    def __init__(self, cog: "CasinoCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Szoba bezárása", emoji="🗑️", style=discord.ButtonStyle.danger,
        custom_id="yoru:gamble-room:close",
    )
    async def close_room(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        channel = interaction.channel
        owner_id = gamble_room_owner(channel)
        if owner_id is None or not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Ez nem Yoru privát gamble szoba.", ephemeral=True)
        is_staff = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild
        if interaction.user.id != owner_id and not is_staff:
            return await interaction.response.send_message("❌ Ezt a szobát csak a tulajdonosa vagy egy admin zárhatja be.", ephemeral=True)
        await interaction.response.send_message("🗑️ A privát gamble szoba bezárása…", ephemeral=True)
        await asyncio.sleep(0.8)
        try:
            await channel.delete(reason=f"Yoru gamble room closed by {interaction.user} ({interaction.user.id})")
        except (discord.Forbidden, discord.HTTPException):
            with contextlib.suppress(discord.HTTPException):
                await interaction.followup.send("❌ Nem tudtam törölni a csatornát. Ellenőrizd a Manage Channels jogot.", ephemeral=True)



class ExpansionOwnedView(discord.ui.View):
    def __init__(self, cog: "CasinoCog", owner: discord.abc.User, session: CasinoSession, *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner = owner
        self.owner_id = owner.id
        self.session = session
        self.message: discord.Message | None = None
        self.finished = False
        self._action_lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te Casino játékod.", ephemeral=True)
            return False
        return True


class PlinkoAutoModal(discord.ui.Modal):
    rounds = discord.ui.TextInput(
        label="Auto körök száma",
        placeholder="10 / 25 / 50 / 100 / inf",
        default="25",
        max_length=8,
    )
    balls_per_round = discord.ui.TextInput(
        label="Labda körönként",
        placeholder="1 / 2 / 3 / 5 / 10",
        default="3",
        max_length=2,
    )

    def __init__(self, view: "PlinkoPanelView") -> None:
        super().__init__(title="🔁 Plinko Auto", timeout=120)
        self.panel_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_rounds = str(self.rounds.value).strip().lower()
        if raw_rounds in {"inf", "infinite", "infinity", "∞", "vegtelen", "végtelen"}:
            rounds: int | None = None
        else:
            try:
                rounds = int(raw_rounds)
            except ValueError:
                return await interaction.response.send_message("❌ Auto körök: 10 / 25 / 50 / 100 / inf.", ephemeral=True)
            if rounds not in {10, 25, 50, 100}:
                return await interaction.response.send_message("❌ Auto körök: 10 / 25 / 50 / 100 / inf.", ephemeral=True)

        raw_balls = str(self.balls_per_round.value).strip().lower().replace("ball", "").replace("labda", "").strip()
        try:
            balls_per_round = int(raw_balls)
        except ValueError:
            return await interaction.response.send_message("❌ Labda körönként: 1 / 2 / 3 / 5 / 10.", ephemeral=True)
        if balls_per_round not in {1, 2, 3, 5, 10}:
            return await interaction.response.send_message("❌ Labda körönként: 1 / 2 / 3 / 5 / 10.", ephemeral=True)
        await self.panel_view.start_auto(interaction, rounds, balls_per_round)


class PlinkoPanelView(discord.ui.LayoutView):
    """Simple proven Plinko playback controller.

    v3.25.12 deliberately mirrors the existing Slots/Candy Rush lifecycle:
    static PNG -> one GIF -> wait -> final PNG -> short safety wait -> unlock.

    No render queue, no pending-batch worker, no GIF-idle state, no speculative
    renderer. Money is atomically settled before any result media is published.
    """

    QUICK_BALL_COUNTS = (1, 2, 3, 5, 10)
    PLAYBACK_GRACE_SECONDS = 0.35
    STATIC_CONFIRM_SECONDS = 0.45

    def __init__(self, cog: "CasinoCog", owner: discord.abc.User, guild_id: int, selected_bet: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.owner = owner
        self.owner_id = int(owner.id)
        self.guild_id = int(guild_id)
        self.selected_bet = max(1, int(selected_bet))
        self.total_bet = 0
        self.total_payout = 0
        self.profit = 0
        self.fast = False
        self.display_message: discord.Message | None = None
        self.control_message: discord.Message | None = None
        self.closed = False
        self.status_text = ""

        self._state_lock = asyncio.Lock()
        self._playing = False
        self._display_active_limit = 10
        self._media_generation = 0
        self._auto_task: asyncio.Task | None = None
        self._auto_stop = asyncio.Event()
        self._auto_target: int | None = 0
        self._auto_done = 0
        self._auto_balls_per_round = 1

        self.bet_row = discord.ui.ActionRow()
        self.all_button = discord.ui.Button(label="ALL", style=discord.ButtonStyle.primary)
        self.half_button = discord.ui.Button(label="1/2", style=discord.ButtonStyle.secondary)
        self.minus_button = discord.ui.Button(label="-", style=discord.ButtonStyle.secondary)
        self.plus_button = discord.ui.Button(label="+", style=discord.ButtonStyle.secondary)
        self.double_button = discord.ui.Button(label="x2", style=discord.ButtonStyle.secondary)
        self.all_button.callback = self._all_callback
        self.half_button.callback = self._half_callback
        self.minus_button.callback = self._minus_callback
        self.plus_button.callback = self._plus_callback
        self.double_button.callback = self._double_callback
        for button in (self.all_button, self.half_button, self.minus_button, self.plus_button, self.double_button):
            self.bet_row.add_item(button)
        self.add_item(self.bet_row)

        self.ball_row = discord.ui.ActionRow()
        self.ball_buttons: list[discord.ui.Button] = []
        for count in self.QUICK_BALL_COUNTS:
            button = discord.ui.Button(label=f"{count} BALL", style=discord.ButtonStyle.primary)
            button.callback = self._make_ball_callback(count)
            self.ball_buttons.append(button)
            self.ball_row.add_item(button)
        self.add_item(self.ball_row)

        self.utility_row = discord.ui.ActionRow()
        self.fast_button = discord.ui.Button(label="FAST", emoji="⚡", style=discord.ButtonStyle.secondary)
        self.auto_button = discord.ui.Button(label="AUTO", emoji="🔁", style=discord.ButtonStyle.secondary)
        self.info_button = discord.ui.Button(label="INFO", emoji="ℹ️", style=discord.ButtonStyle.secondary)
        self.fast_button.callback = self._fast_callback
        self.auto_button.callback = self._auto_callback
        self.info_button.callback = self._info_callback
        for button in (self.fast_button, self.auto_button, self.info_button):
            self.utility_row.add_item(button)
        self.add_item(self.utility_row)
        self._sync_buttons()

    def set_media(self, filename: str) -> None:
        # Compatibility hook used by the panel open path. The display is a plain
        # attachment-only message; there is intentionally no MediaGallery/View.
        return None

    def _next_media_filename(self, kind: str, extension: str) -> str:
        self._media_generation += 1
        safe_kind = "".join(ch for ch in str(kind).lower() if ch.isalnum() or ch in {"_", "-"}) or "media"
        safe_ext = str(extension).lower().lstrip(".")
        return f"plinko_{self.owner_id}_{self._media_generation}_{safe_kind}.{safe_ext}"

    def _auto_running(self) -> bool:
        return self._auto_task is not None and not self._auto_task.done()

    def _busy(self) -> bool:
        return bool(self._playing or self._auto_running())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Ez nem a te Plinko paneled.", ephemeral=True)
            return False
        if self.closed:
            await interaction.response.send_message("❌ Ez a Plinko panel már lejárt. Nyiss újat.", ephemeral=True)
            return False
        return True

    def _sync_buttons(self) -> None:
        running_auto = self._auto_running()
        locked = bool(self.closed or self._playing or running_auto)

        self.fast_button.style = discord.ButtonStyle.primary if self.fast else discord.ButtonStyle.secondary
        self.fast_button.label = "FAST ✓" if self.fast else "FAST"
        self.auto_button.style = discord.ButtonStyle.danger if running_auto else discord.ButtonStyle.secondary
        self.auto_button.label = "STOP AUTO" if running_auto else "AUTO"

        for item in (self.all_button, self.half_button, self.minus_button, self.plus_button, self.double_button):
            item.disabled = locked
        for item in self.ball_buttons:
            item.disabled = locked
        self.fast_button.disabled = locked
        # While Auto is running this remains clickable as STOP AUTO.
        self.auto_button.disabled = bool(self.closed or (self._playing and not running_auto))
        self.info_button.disabled = locked

    async def _edit_controls(self) -> None:
        if self.control_message is None:
            return
        with contextlib.suppress(discord.HTTPException, discord.NotFound, discord.Forbidden):
            await self.control_message.edit(view=self)

    async def _edit_display(self, payload: bytes, filename: str) -> bool:
        """One direct attachment edit. No queue and no hidden retry loop."""
        if self.display_message is None or self.closed:
            return False
        fp = BytesIO(payload)
        fp.name = filename
        try:
            await self.display_message.edit(attachments=[discord.File(fp=fp, filename=filename)])
        except (discord.HTTPException, discord.NotFound, discord.Forbidden):
            return False
        return True

    async def _runtime_minimum(self) -> int:
        runtime = await self.cog.casino.gameplay_settings.casino(self.guild_id)
        return max(1, int(runtime.min_bet))

    async def _current_wallet(self) -> int:
        wallet, _ = await self.cog.casino.db.get_balance(self.guild_id, self.owner_id)
        return int(wallet)

    async def refresh_static(self) -> bool:
        if self.display_message is None or self.closed or self._playing:
            return False
        try:
            fp = await self.cog._render_expansion(
                render_plinko_panel,
                selected_bet=self.selected_bet,
                active_balls=0,
                active_limit=max(1, self._display_active_limit),
                total_bet=self.total_bet,
                profit=self.profit,
                results=(),
            )
        except Exception:
            return False
        return await self._edit_display(fp.getvalue(), self._next_media_filename("idle", "png"))

    async def _change_bet(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.defer()
        async with self._state_lock:
            if self._busy():
                return await interaction.followup.send("❌ Várd meg az aktuális Plinko kört.", ephemeral=True)
            try:
                wallet = await self._current_wallet()
                minimum = await self._runtime_minimum()
                self.selected_bet = adjust_bet(self.selected_bet, wallet, action, minimum=minimum)
                self.status_text = ""
            except ValueError as exc:
                return await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            selected = self.selected_bet
        await self.refresh_static()
        await interaction.followup.send(f"✅ Tét/labda: `{compact_amount(selected)}`.", ephemeral=True)

    async def _settle_batch(self, count: int) -> dict:
        """Resolve + atomically settle one fixed batch. No Discord/render calls."""
        count = max(1, min(10, int(count)))
        selected_bet = int(self.selected_bet)
        base_total_bet = int(self.total_bet)
        base_profit = int(self.profit)

        results = tuple(run_plinko() for _ in range(count))
        payouts = [max(0, int(round(selected_bet * float(result.multiplier)))) for result in results]
        labels = [f"Plinko • slot {result.slot + 1} • x{result.multiplier:g}" for result in results]
        multipliers = [float(result.multiplier) for result in results]

        settlements = await self.cog.casino.settle_immediate_batch(
            self.guild_id,
            self.owner_id,
            "plinko",
            selected_bet,
            payouts=payouts,
            results=labels,
            multipliers=multipliers,
            config={"engine": "plinko_batch_v5_simple", "visual": "generic_dark_v2_fullwidth", "fixed_paytable": True},
        )

        ball_bets = tuple(int(s.bet) for s in settlements)
        ball_profits = tuple(int(s.profit) for s in settlements)
        batch_bet = sum(ball_bets)
        batch_payout = sum(int(s.payout) for s in settlements)
        batch_profit = sum(ball_profits)

        self.total_bet = base_total_bet + batch_bet
        self.total_payout += batch_payout
        self.profit = base_profit + batch_profit
        self.status_text = f"Utolsó batch: {count} labda • {_signed_money(batch_profit)}"

        return {
            "results": results,
            "selected_bet": selected_bet,
            "base_total_bet": base_total_bet,
            "base_profit": base_profit,
            "final_total_bet": int(self.total_bet),
            "final_profit": int(self.profit),
            "ball_bets": ball_bets,
            "ball_profits": ball_profits,
            "fast": bool(self.fast),
        }

    async def _play_batch(self, count: int) -> bool:
        """The entire visual lifecycle for exactly one round.

        Proven pattern copied from Slots/Candy Rush:
        settle -> render -> GIF -> wait full duration -> PNG -> safety wait.
        The method returns only after the display is confirmed back on PNG.
        """
        count = max(1, min(10, int(count)))
        batch = await self._settle_batch(count)
        self._display_active_limit = count

        if batch["fast"]:
            try:
                final_fp = await self.cog._render_expansion(
                    render_plinko_panel,
                    selected_bet=batch["selected_bet"],
                    active_balls=0,
                    active_limit=count,
                    total_bet=batch["final_total_bet"],
                    profit=batch["final_profit"],
                    results=(),
                )
            except Exception:
                self.status_text = "⚠️ A kör settle-ölve lett, de a Plinko PNG renderelése nem sikerült."
                return False
            if not await self._edit_display(final_fp.getvalue(), self._next_media_filename("idle", "png")):
                self.status_text = "⚠️ A kör kész, de a statikus Plinko kijelző frissítése nem sikerült."
                return False
            await asyncio.sleep(self.STATIC_CONFIRM_SECONDS)
            return True

        try:
            animation_payload, final_payload = await self.cog._render_expansion(
                render_plinko_round_media,
                batch["results"],
                selected_bet=batch["selected_bet"],
                active_limit=count,
                total_bet=batch["final_total_bet"],
                profit=batch["final_profit"],
                base_total_bet=batch["base_total_bet"],
                base_profit=batch["base_profit"],
                ball_bets=batch["ball_bets"],
                ball_profits=batch["ball_profits"],
            )
        except Exception:
            # Money is already final. Show the authoritative static result if the
            # animation renderer fails, and stop Auto rather than invent playback.
            try:
                final_fp = await self.cog._render_expansion(
                    render_plinko_panel,
                    selected_bet=batch["selected_bet"],
                    active_balls=0,
                    active_limit=count,
                    total_bet=batch["final_total_bet"],
                    profit=batch["final_profit"],
                    results=(),
                )
            except Exception:
                self.status_text = "⚠️ A kör settle-ölve lett, de a Plinko renderelése nem sikerült."
                return False
            ok = await self._edit_display(final_fp.getvalue(), self._next_media_filename("idle", "png"))
            if ok:
                await asyncio.sleep(self.STATIC_CONFIRM_SECONDS)
            self.status_text = "⚠️ A kör settle-ölve lett, de az animáció kimaradt."
            return False

        # 1) Replace the current idle PNG with exactly one new GIF.
        if not await self._edit_display(animation_payload, self._next_media_filename("round", "gif")):
            # No confirmed GIF upload: immediately install the already prepared
            # final PNG. Never leave the panel in an unknown animated state.
            ok = await self._edit_display(final_payload, self._next_media_filename("idle", "png"))
            if ok:
                await asyncio.sleep(self.STATIC_CONFIRM_SECONDS)
            self.status_text = "⚠️ A kör settle-ölve lett, de a GIF feltöltése nem sikerült."
            return False

        # 2) Do absolutely nothing to the display while the GIF is playing.
        await asyncio.sleep(plinko_animation_duration_seconds(count) + self.PLAYBACK_GRACE_SECONDS)

        # 3) Replace finished GIF with the exact pre-generated final PNG.
        if not await self._edit_display(final_payload, self._next_media_filename("idle", "png")):
            self.status_text = "⚠️ A kör kész, de a PNG visszaállítás nem sikerült. Nyiss új Plinko panelt."
            return False

        # 4) Explicit static confirmation delay before another round may unlock.
        await asyncio.sleep(self.STATIC_CONFIRM_SECONDS)
        return True

    async def drop_batch(self, interaction: discord.Interaction, count: int) -> None:
        count = max(1, min(10, int(count)))
        async with self._state_lock:
            if self._auto_running():
                return await interaction.response.send_message("❌ Auto közben a kézi labdagombok le vannak tiltva.", ephemeral=True)
            if self._playing:
                return await interaction.response.send_message("❌ Várd meg, amíg lefut az aktuális Plinko kör.", ephemeral=True)
            self._playing = True
            self._display_active_limit = count
            self.status_text = f"🎯 Batch indítva: {count} labda."
            self._sync_buttons()

        await interaction.response.defer()
        await self._edit_controls()
        success = False
        try:
            success = await self._play_batch(count)
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except Exception:
            await interaction.followup.send(
                "❌ A Plinko batch nem indult el. Az atomikus batch tranzakció miatt részleges levonás nem maradhatott bent.",
                ephemeral=True,
            )
        finally:
            async with self._state_lock:
                self._playing = False
                if not success and "PNG visszaállítás" in self.status_text:
                    # Do not allow another round from an unconfirmed GIF display.
                    self.closed = True
                self._sync_buttons()
            await self._edit_controls()

    async def start_auto(self, interaction: discord.Interaction, count: int | None, balls_per_round: int) -> None:
        async with self._state_lock:
            if self._auto_running():
                return await interaction.response.send_message("❌ Már fut Auto.", ephemeral=True)
            if self._playing:
                return await interaction.response.send_message("❌ Várd meg, amíg lefut az aktuális Plinko kör.", ephemeral=True)
            self._auto_stop = asyncio.Event()
            self._auto_target = count
            self._auto_done = 0
            self._auto_balls_per_round = max(1, min(10, int(balls_per_round)))
            self._display_active_limit = self._auto_balls_per_round
            self.status_text = ""
            self._auto_task = asyncio.create_task(self._auto_loop(count, self._auto_balls_per_round))
            self._sync_buttons()
        await interaction.response.defer()
        await self._edit_controls()
        target_text = "∞" if count is None else str(count)
        await interaction.followup.send(
            f"▶️ Auto elindult: `{target_text}` kör • `{self._auto_balls_per_round}` labda/kör. Ugyanezzel az AUTO gombbal állíthatod le.",
            ephemeral=True,
        )

    async def stop_auto(self) -> None:
        self._auto_stop.set()

    async def _auto_loop(self, count: int | None, balls_per_round: int) -> None:
        try:
            while not self.closed and not self._auto_stop.is_set():
                if count is not None and self._auto_done >= count:
                    break
                async with self._state_lock:
                    self._playing = True
                    self._sync_buttons()
                try:
                    success = await self._play_batch(balls_per_round)
                except ValueError as exc:
                    self.status_text = f"⏹️ Auto leállt: {exc}"
                    break
                except Exception:
                    self.status_text = "⏹️ Auto leállt egy backend hibánál. Részleges batch nem maradhatott bent."
                    break
                finally:
                    async with self._state_lock:
                        self._playing = False
                if not success:
                    self._auto_stop.set()
                    break
                self._auto_done += 1
                # No extra playback engine: next loop iteration starts only after
                # _play_batch returned from PNG + static-confirm delay.
        finally:
            current = asyncio.current_task()
            if self._auto_task is current:
                self._auto_task = None
            if not self.status_text:
                self.status_text = f"✅ Auto kész: {self._auto_done} kör • {balls_per_round} labda/kör."
            self._sync_buttons()
            await self._edit_controls()

    async def close_panel(self, reason: str = "Panel lezárva.") -> None:
        if self.closed:
            return
        self.closed = True
        self.status_text = reason
        self._auto_stop.set()
        self._sync_buttons()
        if self.control_message is not None:
            with contextlib.suppress(discord.HTTPException, discord.NotFound, discord.Forbidden):
                await self.control_message.edit(view=self)
        key = (self.guild_id, self.owner_id)
        if self.cog._plinko_panels.get(key) is self:
            self.cog._plinko_panels.pop(key, None)

    async def on_timeout(self) -> None:
        await self.close_panel("⏱️ A Plinko panel lejárt. Nyiss újat a folytatáshoz.")

    def _make_ball_callback(self, count: int):
        async def _callback(interaction: discord.Interaction) -> None:
            await self.drop_batch(interaction, count)
        return _callback

    async def _all_callback(self, interaction: discord.Interaction) -> None:
        await self._change_bet(interaction, "all")

    async def _half_callback(self, interaction: discord.Interaction) -> None:
        await self._change_bet(interaction, "half")

    async def _minus_callback(self, interaction: discord.Interaction) -> None:
        await self._change_bet(interaction, "minus")

    async def _plus_callback(self, interaction: discord.Interaction) -> None:
        await self._change_bet(interaction, "plus")

    async def _double_callback(self, interaction: discord.Interaction) -> None:
        await self._change_bet(interaction, "double")

    async def _fast_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        async with self._state_lock:
            if self._busy():
                return await interaction.followup.send("❌ A FAST csak két kör között állítható.", ephemeral=True)
            self.fast = not self.fast
            fast_now = self.fast
            self._sync_buttons()
        await self._edit_controls()
        await interaction.followup.send(f"⚡ FAST: `{'ON' if fast_now else 'OFF'}`.", ephemeral=True)

    async def _auto_callback(self, interaction: discord.Interaction) -> None:
        if self._auto_running():
            await interaction.response.defer()
            await self.stop_auto()
            self.status_text = f"⏹️ Auto leállítás kérve {self._auto_done} kör után."
            return await interaction.followup.send("⏹️ Auto leállítás kérve. Az aktuális kör biztonságosan befejeződik.", ephemeral=True)
        await interaction.response.send_modal(PlinkoAutoModal(self))

    async def _info_callback(self, interaction: discord.Interaction) -> None:
        running_auto = self._auto_running()
        text = (
            f"🎯 Tét/labda: `{compact_amount(self.selected_bet)}`\n"
            f"🟣 Gyors választók: `1 / 2 / 3 / 5 / 10 BALL`\n"
            f"💸 Összes feltett: `{compact_amount(self.total_bet)}`\n"
            f"📈 Profit/Loss: `{compact_amount(self.profit)}`\n"
            f"⚡ FAST: `{'ON' if self.fast else 'OFF'}`\n"
            f"🔁 Auto: `{'FUT' if running_auto else 'OFF'}`"
        )
        if running_auto:
            text += f"\n🔁 Auto körök: `{self._auto_done}` kész • `{self._auto_balls_per_round}` labda/kör"
        if self.status_text:
            text += f"\n📝 Állapot: {self.status_text}"
        await interaction.response.send_message(text, ephemeral=True)


class MinesCellButton(discord.ui.Button):
    def __init__(self, parent: "MinesView", index: int) -> None:
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.secondary, row=index // 5, disabled=index in parent.state.revealed)
        self.parent_view = parent
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.pick(interaction, self.index)


class MinesView(ExpansionOwnedView):
    def __init__(self, cog: "CasinoCog", owner: discord.abc.User, session: CasinoSession, state: MinesState) -> None:
        super().__init__(cog, owner, session, timeout=120.0)
        self.state = state
        for index in range(20):
            self.add_item(MinesCellButton(self, index))
        cashout = discord.ui.Button(label="Cashout", emoji="💰", style=discord.ButtonStyle.success, row=4, disabled=state.safe_reveals <= 0)
        cashout.callback = self.cashout
        self.add_item(cashout)

    async def pick(self, interaction: discord.Interaction, index: int) -> None:
        async with self._action_lock:
            if self.finished:
                return
            await interaction.response.defer()
            self.stop()
            await self.cog.mines_pick(interaction, self, index)

    async def cashout(self, interaction: discord.Interaction) -> None:
        async with self._action_lock:
            if self.finished:
                return
            if self.state.safe_reveals <= 0:
                return await interaction.response.send_message("❌ Előbb fedj fel legalább egy biztonságos mezőt.", ephemeral=True)
            await interaction.response.defer()
            self.finished = True
            self.stop()
            await self.cog.finish_mines(interaction, self, reason="cashout")

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.finished = True
        await self.cog.timeout_mines(self)


class ChickenRoadView(ExpansionOwnedView):
    def __init__(self, cog: "CasinoCog", owner: discord.abc.User, session: CasinoSession, state: ChickenRoadState) -> None:
        super().__init__(cog, owner, session, timeout=120.0)
        self.state = state
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label == "Cashout":
                child.disabled = state.step <= 0

    @discord.ui.button(label="Tovább", emoji="➡️", style=discord.ButtonStyle.primary, row=0)
    async def advance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.finished:
                return
            await interaction.response.defer()
            self.stop()
            await self.cog.chicken_road_advance(interaction, self)

    @discord.ui.button(label="Cashout", emoji="💰", style=discord.ButtonStyle.success, row=0)
    async def cashout(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self._action_lock:
            if self.finished:
                return
            if self.state.step <= 0:
                return await interaction.response.send_message("❌ Előbb juss át legalább egy sávon.", ephemeral=True)
            await interaction.response.defer()
            self.finished = True
            self.stop()
            await self.cog.finish_chicken_road(interaction, self, reason="cashout")

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.finished = True
        await self.cog.timeout_chicken_road(self)


class CasinoCog(commands.GroupCog, group_name="casino", group_description="Yoru Casino lobby, játékok, statok és előzmények."):
    def __init__(self, bot: commands.Bot, casino: CasinoService, gambling: GamblingService | None = None) -> None:
        self.bot = bot
        self.casino = casino
        self.gambling = gambling
        self.settings = getattr(casino.guild_settings, "state", ServerSettingsService(casino.db))
        self.casino.set_settlement_listener(self._log_settlement)
        self._jackpot_task: asyncio.Task | None = None
        self._expansion_render_semaphore = asyncio.Semaphore(2)
        self._plinko_panels: dict[tuple[int, int], PlinkoPanelView] = {}
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_view(GambleRoomPanelView(self))
        self.bot.add_view(GambleRoomCloseView(self))
        self._jackpot_task = asyncio.create_task(self._jackpot_loop())

    async def cog_unload(self) -> None:
        if self._jackpot_task:
            self._jackpot_task.cancel()
        auto_tasks = []
        for view in list(self._plinko_panels.values()):
            view._auto_stop.set()
            if view._auto_task is not None and not view._auto_task.done():
                auto_tasks.append(view._auto_task)
        # Let an in-flight atomic Drop finish before force-cancelling during a
        # cog reload. A full process restart is still covered by Casino recovery.
        if auto_tasks:
            done, pending = await asyncio.wait(auto_tasks, timeout=2.0)
            for task in pending:
                task.cancel()
        self._plinko_panels.clear()

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
        runtime = await self.casino.gameplay_settings.casino(guild.id)
        embed = base_embed("🎰 Casino beállítások", "A Yoru DB settings az elsődleges balance source; a kódbeli Casino értékek csak fallback defaultok.", BRAND)
        embed.add_field(name="🎚️ Casino balance", value=f"Minimum tét: **{money(runtime.min_bet)}**", inline=True)
        embed.add_field(name="💰 Monthly Jackpot", value=f"Jogosultság: **{runtime.jackpot_min_games} game** VAGY **{money(runtime.jackpot_min_wager)} wager**\nHouse-loss contribution: **{runtime.jackpot_contribution_rate*100:g}%** • payout: **{runtime.jackpot_payout_share*100:g}%**", inline=False)
        embed.add_field(name="🧾 Casino log", value=channel.mention if channel else "**Nincs beállítva**", inline=False)
        embed.add_field(name="Mit ment?", value="Game ID • játékos • játék • tét • payout • P/L • multiplier • eredmény", inline=False)
        embed.set_footer(text="Yoru • Settings • Casino")
        return embed

    async def show_settings(self, interaction: discord.Interaction, owner_id: int, *, channel_page: int = 0) -> None:
        if interaction.guild is None:
            return
        # A DB/settings lekérés előtt azonnal acknowledge-oljuk a component interactiont,
        # különben lassabb hoston Discord "didn't respond in time" hibát mutat.
        if not interaction.response.is_done():
            await interaction.response.defer()
        view = CasinoSettingsView(self, owner_id)
        view.channel_page = max(0, int(channel_page))
        view.add_channel_selector(interaction.guild)
        embed = await self.settings_embed(interaction.guild)
        await interaction.edit_original_response(embed=embed, view=view, attachments=[])

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            return False
        try:
            await self.casino.guild_settings.prepare_currency(interaction.guild_id)
            await self.casino.guild_settings.require_feature(interaction.guild_id, "gambling")
            if not is_gamble_room(interaction.channel):
                await self.casino.guild_settings.require_channel(
                    interaction.guild_id,
                    interaction.channel_id,
                    getattr(interaction.channel, "category_id", None),
                )
        except ValueError as exc:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(exc)), ephemeral=True)
            return False
        return True

    async def _render_expansion(self, func, *args, **kwargs):
        async with self._expansion_render_semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)

    @staticmethod
    def _scaled_multiplier(session: CasinoSession, raw_multiplier: float) -> float:
        raw = max(0.0, float(raw_multiplier))
        if raw <= 1.0:
            return raw
        scale = float(session.config.get("payout_scale", 1.0))
        return 1.0 + (raw - 1.0) * scale

    def _scaled_payout(self, session: CasinoSession, raw_multiplier: float) -> tuple[int, float]:
        multiplier = self._scaled_multiplier(session, raw_multiplier)
        return max(0, int(round(session.bet * multiplier))), multiplier

    def _expansion_embed(self, title: str, user: discord.abc.User, session: CasinoSession, *, description: str, multiplier: float | None = None, final=None, image: str) -> discord.Embed:
        color = BRAND
        if final is not None:
            color = SUCCESS if final.profit > 0 else (DANGER if final.profit < 0 else GOLD)
        embed = base_embed(title, description, color)
        embed.set_author(name=getattr(user, "display_name", user.name), icon_url=getattr(getattr(user, "display_avatar", None), "url", None))
        embed.set_image(url=f"attachment://{image}")
        embed.add_field(name="🎟️ Tét", value=f"**{money(session.bet)}**", inline=True)
        if final is None:
            embed.add_field(name="✖️ Cashout", value=(f"**x{multiplier:.2f}**" if multiplier is not None else "**…**"), inline=True)
            embed.add_field(name="💰 Állapot", value="**Aktív**", inline=True)
        else:
            pnl = _signed_money(final.profit)
            embed.add_field(name="💸 Kifizetés", value=f"**{money(final.payout)}**", inline=True)
            embed.add_field(name="📈 P/L", value=f"**{pnl}**", inline=True)
            embed.add_field(name="💰 Egyenleg", value=f"**{money(final.wallet)}**", inline=True)
            embed.add_field(name="✖️ Multiplier", value=f"**x{final.multiplier:.2f}**", inline=True)
        embed.set_footer(text="Yoru • Casino Expansion")
        return embed

    async def _guard_prefix(self, ctx: commands.Context) -> bool:
        try:
            await self.casino.guild_settings.prepare_currency(ctx.guild.id)
            await self.casino.guild_settings.require_feature(ctx.guild.id, "gambling")
            if not is_gamble_room(ctx.channel):
                await self.casino.guild_settings.require_channel(ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None))
        except ValueError as exc:
            await ctx.send(embed=error_embed(ctx.author, str(exc)))
            return False
        return True

    # ------------------------------------------------------- Casino Expansion
    async def start_mines_interaction(self, interaction: discord.Interaction, bet: int, mine_count: int) -> None:
        if interaction.guild_id is None:
            return
        if mine_count not in MINES_ALLOWED_COUNTS:
            return await interaction.response.send_message(f"❌ Bombák: {', '.join(map(str, MINES_ALLOWED_COUNTS))}.", ephemeral=True)
        await interaction.response.defer()
        session = None
        try:
            session = await self.casino.begin(interaction.guild_id, interaction.user.id, "mines", bet, config={"engine":"mines_v1","mines":mine_count,"defer_player_lock_release":True})
            state = new_mines_state(mine_count)
            shown = self._scaled_multiplier(session, state.multiplier)
            fp = await self._render_expansion(render_mines, state, player_name=interaction.user.display_name, cashout_multiplier=shown)
            view = MinesView(self, interaction.user, session, state)
            embed = self._expansion_embed("💣 MINES", interaction.user, session, description="Fedj fel biztonságos mezőket, majd cashoutolj. Több bomba = gyorsabban növekvő szorzó.", multiplier=shown, image="mines.png")
            await interaction.edit_original_response(embed=embed, attachments=[discord.File(fp=fp, filename="mines.png")], view=view)
            view.message = await interaction.original_response()
        except ValueError as exc:
            if session is not None:
                with contextlib.suppress(ValueError): await self.casino.refund(session, "mines_start_error")
            await interaction.edit_original_response(embed=error_embed(interaction.user, str(exc)), attachments=[], view=None)

    async def start_mines_prefix(self, ctx: commands.Context, bet: int, mine_count: int) -> None:
        session = None
        try:
            session = await self.casino.begin(ctx.guild.id, ctx.author.id, "mines", bet, config={"engine":"mines_v1","mines":mine_count,"defer_player_lock_release":True})
            state = new_mines_state(mine_count)
            shown = self._scaled_multiplier(session, state.multiplier)
            fp = await self._render_expansion(render_mines, state, player_name=ctx.author.display_name, cashout_multiplier=shown)
            view = MinesView(self, ctx.author, session, state)
            msg = await ctx.send(embed=self._expansion_embed("💣 MINES", ctx.author, session, description="Fedj fel biztonságos mezőket, majd cashoutolj.", multiplier=shown, image="mines.png"), file=discord.File(fp=fp,filename="mines.png"), view=view)
            view.message = msg
        except ValueError as exc:
            if session is not None:
                with contextlib.suppress(ValueError): await self.casino.refund(session, "mines_start_error")
            await ctx.send(embed=error_embed(ctx.author, str(exc)))

    async def mines_pick(self, interaction: discord.Interaction, view: MinesView, index: int) -> None:
        state = view.state
        settlement = None
        try:
            safe = reveal_mines_cell(state, index)
        except ValueError as exc:
            return await interaction.followup.send(embed=error_embed(interaction.user, str(exc)), ephemeral=True)

        shown = self._scaled_multiplier(view.session, state.multiplier)
        # Terminal outcomes are committed before client animation.  A Discord
        # image/edit failure must never turn a decided loss into a restart refund.
        if not safe:
            view.finished = True
            settlement = await self.casino.settle(
                view.session, 0,
                result=f"Mines lose • {state.mine_count} mines • {state.safe_reveals} safe",
                multiplier=0.0,
            )
        elif state.finished:
            view.finished = True
            payout, _ = self._scaled_payout(view.session, state.multiplier)
            settlement = await self.casino.settle(
                view.session, payout,
                result=f"Mines full clear • {state.mine_count} mines • {state.safe_reveals} safe",
            )

        try:
            gif = await self._render_expansion(
                render_mines_transition, state, index,
                player_name=interaction.user.display_name, cashout_multiplier=shown,
            )
            await interaction.message.edit(
                embed=self._expansion_embed(
                    "💣 MINES", interaction.user, view.session,
                    description="💥 Bomba!" if not safe else "✅ Biztonságos mező.",
                    multiplier=shown, image="mines.gif",
                ),
                attachments=[discord.File(fp=gif, filename="mines.gif")], view=None,
            )
            await asyncio.sleep(1.35)

            if not safe:
                fp = await self._render_expansion(
                    render_mines, state, player_name=interaction.user.display_name,
                    reveal_all=True, phase="BOMBA", cashout_multiplier=0.0,
                )
                await interaction.message.edit(
                    embed=self._expansion_embed(
                        "💣 MINES", interaction.user, view.session,
                        description="A run véget ért.", final=settlement, image="mines.png",
                    ),
                    attachments=[discord.File(fp=fp, filename="mines.png")], view=None,
                )
                return

            if state.finished:
                fp = await self._render_expansion(
                    render_mines, state, player_name=interaction.user.display_name,
                    reveal_all=True, phase="TELJES TISZTÍTÁS",
                    cashout_multiplier=settlement.multiplier,
                )
                await interaction.message.edit(
                    embed=self._expansion_embed(
                        "💣 MINES", interaction.user, view.session,
                        description="🏆 Minden biztonságos mezőt megtaláltál.",
                        final=settlement, image="mines.png",
                    ),
                    attachments=[discord.File(fp=fp, filename="mines.png")], view=None,
                )
                return

            new_view = MinesView(self, interaction.user, view.session, state)
            fp = await self._render_expansion(
                render_mines, state, player_name=interaction.user.display_name,
                cashout_multiplier=shown,
            )
            await interaction.message.edit(
                embed=self._expansion_embed(
                    "💣 MINES", interaction.user, view.session,
                    description="Tovább kockáztatsz vagy cashoutolsz?",
                    multiplier=shown, image="mines.png",
                ),
                attachments=[discord.File(fp=fp, filename="mines.png")], view=new_view,
            )
            new_view.message = interaction.message
        except Exception:
            # Non-terminal UI failures cannot leave a reserved bet with no
            # controls. Terminal sessions are already settled and must stand.
            if settlement is None:
                with contextlib.suppress(ValueError):
                    await self.casino.refund(view.session, "mines_ui_error")
            raise
        finally:
            if settlement is not None:
                await self.casino.release_player_game(view.session.game_id)

    async def finish_mines(self, interaction: discord.Interaction, view: MinesView, *, reason: str) -> None:
        state = view.state; state.finished = True
        payout, shown = self._scaled_payout(view.session, state.multiplier)
        settlement = await self.casino.settle(view.session, payout, result=f"Mines {reason} • {state.mine_count} mines • {state.safe_reveals} safe")
        try:
            fp = await self._render_expansion(render_mines, state, player_name=interaction.user.display_name, phase="CASHOUT", cashout_multiplier=shown)
            await interaction.message.edit(embed=self._expansion_embed("💣 MINES", interaction.user, view.session, description="💰 Cashout sikeres.", final=settlement, image="mines.png"), attachments=[discord.File(fp=fp,filename="mines.png")], view=None)
        finally:
            await self.casino.release_player_game(view.session.game_id)

    async def timeout_mines(self, view: MinesView) -> None:
        if view.message is None:
            with contextlib.suppress(ValueError):
                await self.casino.refund(view.session, "mines_timeout")
            return
        settled = False
        try:
            if view.state.safe_reveals <= 0:
                await self.casino.refund(view.session, "mines_timeout_no_move")
                await view.message.edit(
                    embed=base_embed("💣 Mines • timeout", "Nem történt felfedés, ezért a tét visszajárt.", GOLD),
                    attachments=[], view=None,
                )
                return
            view.state.finished = True
            payout, shown = self._scaled_payout(view.session, view.state.multiplier)
            settlement = await self.casino.settle(
                view.session, payout, result=f"Mines timeout cashout • {view.state.safe_reveals} safe"
            )
            settled = True
            fp = await self._render_expansion(
                render_mines, view.state, player_name=view.owner.display_name,
                phase="AUTO CASHOUT", cashout_multiplier=shown,
            )
            await view.message.edit(
                embed=self._expansion_embed(
                    "💣 MINES", view.owner, view.session,
                    description="⏱️ Lejárt az idő: automatikus cashout.",
                    final=settlement, image="mines.png",
                ),
                attachments=[discord.File(fp=fp, filename="mines.png")], view=None,
            )
        except (ValueError, discord.HTTPException):
            if not settled:
                with contextlib.suppress(ValueError):
                    await self.casino.refund(view.session, "mines_timeout_error")
        finally:
            if settled:
                await self.casino.release_player_game(view.session.game_id)

    async def start_chicken_road_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        if interaction.guild_id is None: return
        await interaction.response.defer()
        session=None
        try:
            session=await self.casino.begin(interaction.guild_id,interaction.user.id,"chickenroad",bet,config={"engine":"chicken_road_v1","defer_player_lock_release":True})
            state=ChickenRoadState(); shown=self._scaled_multiplier(session,state.multiplier)
            fp=await self._render_expansion(render_chicken_road,state,player_name=interaction.user.display_name,cashout_multiplier=shown)
            view=ChickenRoadView(self,interaction.user,session,state)
            await interaction.edit_original_response(embed=self._expansion_embed("🐔 CHICKEN ROAD",interaction.user,session,description="Menj át sávonként. Minden siker után nő a cashout szorzó.",multiplier=shown,image="chicken_road.png"),attachments=[discord.File(fp=fp,filename="chicken_road.png")],view=view)
            view.message=await interaction.original_response()
        except ValueError as exc:
            if session is not None:
                with contextlib.suppress(ValueError): await self.casino.refund(session,"chickenroad_start_error")
            await interaction.edit_original_response(embed=error_embed(interaction.user,str(exc)),attachments=[],view=None)

    async def start_chicken_road_prefix(self, ctx: commands.Context, bet: int) -> None:
        session=None
        try:
            session=await self.casino.begin(ctx.guild.id,ctx.author.id,"chickenroad",bet,config={"engine":"chicken_road_v1","defer_player_lock_release":True})
            state=ChickenRoadState(); shown=self._scaled_multiplier(session,state.multiplier)
            fp=await self._render_expansion(render_chicken_road,state,player_name=ctx.author.display_name,cashout_multiplier=shown)
            view=ChickenRoadView(self,ctx.author,session,state)
            msg=await ctx.send(embed=self._expansion_embed("🐔 CHICKEN ROAD",ctx.author,session,description="Menj át sávonként. Minden siker után nő a cashout szorzó.",multiplier=shown,image="chicken_road.png"),file=discord.File(fp=fp,filename="chicken_road.png"),view=view);view.message=msg
        except ValueError as exc:
            if session is not None:
                with contextlib.suppress(ValueError): await self.casino.refund(session,"chickenroad_start_error")
            await ctx.send(embed=error_embed(ctx.author,str(exc)))

    async def chicken_road_advance(self, interaction: discord.Interaction, view: ChickenRoadView) -> None:
        before = view.state.step
        survived = advance_chicken(view.state)
        shown = self._scaled_multiplier(view.session, view.state.multiplier)
        settlement = None

        # Commit terminal RNG results before the animation, exactly like the
        # rest of Casino V2. Visual delivery must not decide money state.
        if not survived:
            view.finished = True
            settlement = await self.casino.settle(
                view.session, 0, result=f"Chicken Road lose • step {before + 1}", multiplier=0.0
            )
        elif view.state.finished:
            view.finished = True
            payout, shown = self._scaled_payout(view.session, view.state.multiplier)
            settlement = await self.casino.settle(
                view.session, payout, result=f"Chicken Road full clear • {view.state.step} steps"
            )

        try:
            gif = await self._render_expansion(
                render_chicken_road_transition, before, view.state,
                player_name=interaction.user.display_name, cashout_multiplier=shown,
            )
            await interaction.message.edit(
                embed=self._expansion_embed(
                    "🐔 CHICKEN ROAD", interaction.user, view.session,
                    description="🚗 Átkelés folyamatban…", multiplier=shown, image="chicken_road.gif",
                ),
                attachments=[discord.File(fp=gif, filename="chicken_road.gif")], view=None,
            )
            await asyncio.sleep(0.82)

            if not survived:
                fp = await self._render_expansion(
                    render_chicken_road, view.state, player_name=interaction.user.display_name,
                    phase="ELÜTÖTTEK", cashout_multiplier=0.0,
                )
                await interaction.message.edit(
                    embed=self._expansion_embed(
                        "🐔 CHICKEN ROAD", interaction.user, view.session,
                        description="💥 Nem jutottál át a következő sávon.",
                        final=settlement, image="chicken_road.png",
                    ),
                    attachments=[discord.File(fp=fp, filename="chicken_road.png")], view=None,
                )
                return

            if view.state.finished:
                fp = await self._render_expansion(
                    render_chicken_road, view.state, player_name=interaction.user.display_name,
                    phase="ÚT TELJESÍTVE", cashout_multiplier=shown,
                )
                await interaction.message.edit(
                    embed=self._expansion_embed(
                        "🐔 CHICKEN ROAD", interaction.user, view.session,
                        description="🏆 Végigértél az úton.", final=settlement, image="chicken_road.png",
                    ),
                    attachments=[discord.File(fp=fp, filename="chicken_road.png")], view=None,
                )
                return

            new_view = ChickenRoadView(self, interaction.user, view.session, view.state)
            fp = await self._render_expansion(
                render_chicken_road, view.state, player_name=interaction.user.display_name,
                cashout_multiplier=shown,
            )
            await interaction.message.edit(
                embed=self._expansion_embed(
                    "🐔 CHICKEN ROAD", interaction.user, view.session,
                    description="Tovább mész vagy cashoutolsz?", multiplier=shown, image="chicken_road.png",
                ),
                attachments=[discord.File(fp=fp, filename="chicken_road.png")], view=new_view,
            )
            new_view.message = interaction.message
        except Exception:
            if settlement is None:
                with contextlib.suppress(ValueError):
                    await self.casino.refund(view.session, "chickenroad_ui_error")
            raise
        finally:
            if settlement is not None:
                await self.casino.release_player_game(view.session.game_id)

    async def finish_chicken_road(self, interaction: discord.Interaction, view: ChickenRoadView, *, reason: str) -> None:
        view.state.finished=True
        payout,shown=self._scaled_payout(view.session,view.state.multiplier)
        settlement=await self.casino.settle(view.session,payout,result=f"Chicken Road {reason} • {view.state.step} steps")
        try:
            fp=await self._render_expansion(render_chicken_road,view.state,player_name=interaction.user.display_name,phase="CASHOUT",cashout_multiplier=shown)
            await interaction.message.edit(embed=self._expansion_embed("🐔 CHICKEN ROAD",interaction.user,view.session,description="💰 Cashout sikeres.",final=settlement,image="chicken_road.png"),attachments=[discord.File(fp=fp,filename="chicken_road.png")],view=None)
        finally: await self.casino.release_player_game(view.session.game_id)

    async def timeout_chicken_road(self, view: ChickenRoadView) -> None:
        if view.message is None:
            with contextlib.suppress(ValueError):
                await self.casino.refund(view.session, "chickenroad_timeout")
            return
        settled = False
        try:
            if view.state.step <= 0:
                await self.casino.refund(view.session, "chickenroad_timeout_no_move")
                await view.message.edit(
                    embed=base_embed("🐔 Chicken Road • timeout", "Nem léptél, ezért a tét visszajárt.", GOLD),
                    attachments=[], view=None,
                )
                return
            view.state.finished = True
            payout, shown = self._scaled_payout(view.session, view.state.multiplier)
            settlement = await self.casino.settle(
                view.session, payout, result=f"Chicken Road timeout cashout • {view.state.step} steps"
            )
            settled = True
            fp = await self._render_expansion(
                render_chicken_road, view.state, player_name=view.owner.display_name,
                phase="AUTO CASHOUT", cashout_multiplier=shown,
            )
            await view.message.edit(
                embed=self._expansion_embed(
                    "🐔 CHICKEN ROAD", view.owner, view.session,
                    description="⏱️ Lejárt az idő: automatikus cashout.",
                    final=settlement, image="chicken_road.png",
                ),
                attachments=[discord.File(fp=fp, filename="chicken_road.png")], view=None,
            )
        except (ValueError, discord.HTTPException):
            if not settled:
                with contextlib.suppress(ValueError):
                    await self.casino.refund(view.session, "chickenroad_timeout_error")
        finally:
            if settled:
                await self.casino.release_player_game(view.session.game_id)

    async def _register_plinko_panel(self, guild_id: int, owner: discord.abc.User, bet: int) -> PlinkoPanelView:
        await self.casino.validate_bet(guild_id, bet)
        key = (int(guild_id), int(owner.id))
        old = self._plinko_panels.get(key)
        if old is not None and not old.closed:
            await old.close_panel("🔄 Új Plinko panel nyílt.")
        view = PlinkoPanelView(self, owner, guild_id, bet)
        self._plinko_panels[key] = view
        return view

    async def open_plinko_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        if interaction.guild_id is None:
            return
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            view = await self._register_plinko_panel(interaction.guild_id, interaction.user, bet)
            fp = await self._render_expansion(render_plinko_panel, selected_bet=bet)
            view.set_media("plinko.png")

            # Message 1: plain attachment-only display. This intentionally uses
            # the same proven GIF -> PNG primitive as the existing Slots flow.
            display_message = await interaction.edit_original_response(
                attachments=[discord.File(fp=fp, filename="plinko.png")],
            )
            view.display_message = display_message

            # Message 2: CONTROLS ONLY. Button ACKs can never rerender/replay the
            # GIF above because they target a physically separate Discord message.
            control_message = await interaction.followup.send(view=view, wait=True)
            view.control_message = control_message
        except ValueError as exc:
            await interaction.edit_original_response(embed=error_embed(interaction.user, str(exc)), attachments=[], view=None)

    async def open_plinko_prefix(self, ctx: commands.Context, bet: int) -> None:
        try:
            view = await self._register_plinko_panel(ctx.guild.id, ctx.author, bet)
            fp = await self._render_expansion(render_plinko_panel, selected_bet=bet)
            view.set_media("plinko.png")

            # Message 1: plain attachment-only display, no components/View.
            display_message = await ctx.send(
                file=discord.File(fp=fp, filename="plinko.png"),
            )
            view.display_message = display_message

            # Message 2: controls-only view.
            control_message = await ctx.send(view=view)
            view.control_message = control_message
        except ValueError as exc:
            await ctx.send(embed=error_embed(ctx.author, str(exc)))

    # Compatibility aliases for old internal callers. Risk is intentionally ignored:
    # v3.25 has one audited standard board and no Low/Medium/High selector.
    async def run_plinko_interaction(self, interaction: discord.Interaction, bet: int, _legacy_option: str | None = None) -> None:
        await self.open_plinko_interaction(interaction, bet)

    async def run_plinko_prefix(self, ctx: commands.Context, bet: int, _legacy_option: str | None = None) -> None:
        await self.open_plinko_prefix(ctx, bet)

    async def run_candy_rush_interaction(self, interaction: discord.Interaction, bet: int) -> None:
        if interaction.guild_id is None:return
        await interaction.response.defer();session=None
        try:
            session=await self.casino.begin(interaction.guild_id,interaction.user.id,"candyrush",bet,config={"engine":"candy_rush_v1","defer_player_lock_release":True})
            result=run_candy_rush();payout,shown=self._scaled_payout(session,result.multiplier)
            settlement=await self.casino.settle(session,payout,result=f"Candy Rush • {len(result.cascades)} cascades • x{shown:.2f}")
            gif=await self._render_expansion(render_candy_rush_animation,result,player_name=interaction.user.display_name)
            await interaction.edit_original_response(embed=self._expansion_embed("🍬 CANDY RUSH",interaction.user,session,description="A cascade-ek lefutnak…",image="candy_rush.gif"),attachments=[discord.File(fp=gif,filename="candy_rush.gif")],view=None)
            await asyncio.sleep(max(1.35, 1.20 + len(result.cascades) * 0.70))
            fp=await self._render_expansion(render_candy_rush,result,player_name=interaction.user.display_name)
            await interaction.edit_original_response(embed=self._expansion_embed("🍬 CANDY RUSH",interaction.user,session,description=f"**{len(result.cascades)} cascade** • x{shown:.2f}",final=settlement,image="candy_rush.png"),attachments=[discord.File(fp=fp,filename="candy_rush.png")],view=None)
        except ValueError as exc:
            if session is not None:
                with contextlib.suppress(ValueError): await self.casino.refund(session,"candyrush_error")
            await interaction.edit_original_response(embed=error_embed(interaction.user,str(exc)),attachments=[],view=None)
        finally:
            if session is not None: await self.casino.release_player_game(session.game_id)

    async def run_candy_rush_prefix(self, ctx: commands.Context, bet: int) -> None:
        session=None
        try:
            session=await self.casino.begin(ctx.guild.id,ctx.author.id,"candyrush",bet,config={"engine":"candy_rush_v1","defer_player_lock_release":True})
            result=run_candy_rush();payout,shown=self._scaled_payout(session,result.multiplier)
            settlement=await self.casino.settle(session,payout,result=f"Candy Rush • {len(result.cascades)} cascades • x{shown:.2f}")
            gif=await self._render_expansion(render_candy_rush_animation,result,player_name=ctx.author.display_name)
            msg=await ctx.send(embed=self._expansion_embed("🍬 CANDY RUSH",ctx.author,session,description="A cascade-ek lefutnak…",image="candy_rush.gif"),file=discord.File(fp=gif,filename="candy_rush.gif"));await asyncio.sleep(max(1.35, 1.20 + len(result.cascades) * 0.70))
            fp=await self._render_expansion(render_candy_rush,result,player_name=ctx.author.display_name)
            await msg.edit(embed=self._expansion_embed("🍬 CANDY RUSH",ctx.author,session,description=f"**{len(result.cascades)} cascade** • x{shown:.2f}",final=settlement,image="candy_rush.png"),attachments=[discord.File(fp=fp,filename="candy_rush.png")])
        except ValueError as exc:
            if session is not None:
                with contextlib.suppress(ValueError): await self.casino.refund(session,"candyrush_error")
            await ctx.send(embed=error_embed(ctx.author,str(exc)))
        finally:
            if session is not None: await self.casino.release_player_game(session.game_id)

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
                "💣 **Mines** — reveal + cashout • 🐔 **Chicken Road** — push-your-luck\n"
                "🔵 **Plinko** — 1/2/3/5/10 Ball batch • Fast/Auto • 🍬 **Candy Rush** — cascade\n"
                "🪙 **Coinflip** • 🎲 **Dice** • 🃏 **High/Low** • ✂️ **RPS** • 🐔 **Chicken Fight**"
            ),
            inline=False,
        )
        embed.add_field(
            name="⌨️ Shortcutok",
            value=(
                "`!mines <tét> [3|5|7|9]` • `!chickenroad <tét>` • `!plinko <tét>` • `!candyrush <tét>`\n"
                "`!bj <tét>` • `!sl <tét>` • `!r` • `!cf fej <tét>` • `!dice odd <tét>`"
            ),
            inline=False,
        )
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
        runtime = await self.casino.gameplay_settings.casino(guild_id)
        eligible = summary["month_games"] >= runtime.jackpot_min_games or summary["month_wagered"] >= runtime.jackpot_min_wager
        now = datetime.now(timezone.utc)
        if now.month == 12: next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else: next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        embed = base_embed("💰 MONTHLY GLOBAL JACKPOT", "A house-game veszteségek egy része automatikusan a havi közösségi poolba kerül.", GOLD)
        embed.add_field(name="🏦 Aktuális pool", value=f"# **{money(j['pool'])}**", inline=False)
        embed.add_field(name="⏳ Következő húzás", value=f"<t:{int(next_month.timestamp())}:R>", inline=True)
        embed.add_field(name="👤 Jogosultság", value=("✅ **Jogosult vagy**" if eligible else f"❌ {summary['month_games']}/{runtime.jackpot_min_games} game • {money(summary['month_wagered'])}/{money(runtime.jackpot_min_wager)} wager"), inline=False)
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
        lottery_settings = await self.casino.gameplay_settings.community_economy(guild_id)
        pot = max(
            int(lottery_settings.lottery_min_pot),
            int(total_tickets * lottery_settings.lottery_ticket_price * lottery_settings.lottery_payout_share),
        ) if total_tickets else 0
        history = await self.casino.db.get_lottery_history(guild_id, 1)
        embed = base_embed("🎟️ YORU LOTTERY", "Kisebb, gyakrabban húzott ticket-alapú játék. A Monthly Jackpot ettől teljesen külön rendszer.", GOLD)
        embed.set_author(name=getattr(user, "display_name", user.name), icon_url=getattr(getattr(user, "display_avatar", None), "url", None))
        embed.add_field(name="💰 Aktuális pot", value=f"# **{money(pot)}**", inline=False)
        embed.add_field(name="🎟️ Összes jegy", value=f"**{total_tickets}**", inline=True)
        embed.add_field(name="👤 Saját jegy", value=f"**{own}**", inline=True)
        embed.add_field(name="💵 Jegyár", value=f"**{money(lottery_settings.lottery_ticket_price)}**", inline=True)
        embed.add_field(name="⏳ Következő húzás", value=f"<t:{int(community.next_lottery_at.timestamp())}:R>", inline=False)
        if history:
            last=history[0]
            embed.add_field(name="🏆 Legutóbbi nyertes", value=f"<@{last['winner_id']}> • **{money(last['payout'])}**", inline=False)
        embed.set_footer(text="Yoru • Lottery")
        return embed

    @staticmethod
    def gamble_room_panel_embed() -> discord.Embed:
        embed = base_embed(
            "🎰 Privát Gamble Szoba",
            "Nyomd meg a gombot, és Yoru létrehoz neked egy **privát text szobát** a szerencsejátékokhoz.",
            BRAND,
        )
        embed.add_field(name="🔒 Privát", value="A szobát csak te látod (a szerver adminjai természetesen továbbra is hozzáférhetnek).", inline=False)
        embed.add_field(name="♻️ Állandó panel", value="Ez a panel restart után is működik. Játékosonként egyszerre **1 aktív gamble szoba** lehet.", inline=False)
        embed.set_footer(text="Yoru • Private Gamble Rooms")
        return embed

    def _find_private_gamble_room(self, guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
        for channel in guild.text_channels:
            if gamble_room_owner(channel) == int(user_id):
                return channel
        return None

    async def create_private_gamble_room(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return await interaction.followup.send("❌ Ez csak szerveren használható.", ephemeral=True)
        existing = self._find_private_gamble_room(guild, member.id)
        if existing is not None:
            return await interaction.followup.send(f"🎰 Már van privát gamble szobád: {existing.mention}", ephemeral=True)
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await interaction.followup.send("❌ Yoru-nak **Csatornák kezelése** jogosultság kell a privát szobákhoz.", ephemeral=True)
        panel_channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        category = panel_channel.category if panel_channel is not None else None
        try:
            room = await guild.create_text_channel(
                gamble_room_name(member.display_name, member.id),
                category=category,
                overwrites=private_room_overwrites(guild, member),
                topic=make_gamble_room_topic(member.id, getattr(panel_channel, "id", None)),
                reason=f"Yoru private gamble room for {member} ({member.id})",
            )
            intro = base_embed(
                "🎰 Saját Gamble Szobád",
                "Ez a csatorna átengedi a Yoru gambling/casino parancsokat akkor is, ha az economy más csatornákra van korlátozva.",
                BRAND,
            )
            intro.add_field(name="🎮 Használat", value="Használd a `/casino` és gambling parancsokat ugyanúgy, mint máshol.", inline=False)
            intro.add_field(name="🗑️ Bezárás", value="Ha végeztél, az alábbi gombbal törölheted a szobát. Újat ezután bármikor kérhetsz a panelről.", inline=False)
            intro.set_footer(text=f"Yoru • privát szoba • {member.display_name}")
            await room.send(
                content=member.mention, embed=intro, view=GambleRoomCloseView(self),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ Nem tudtam létrehozni a szobát. Ellenőrizd Yoru **Csatornák kezelése** jogosultságát és role hierarchy-ját.", ephemeral=True)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"❌ Discord hiba a szoba létrehozásakor: `{exc}`", ephemeral=True)
        await interaction.followup.send(f"✅ Elkészült a privát gamble szobád: {room.mention}", ephemeral=True)

    async def _post_gamble_room_panel(self, destination: discord.abc.Messageable) -> discord.Message:
        return await destination.send(embed=self.gamble_room_panel_embed(), view=GambleRoomPanelView(self))

    @app_commands.command(name="roompanel", description="Admin: állandó privát gamble-szoba panel kirakása ebbe a csatornába.")
    @app_commands.default_permissions(manage_guild=True)
    async def roompanel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Ehhez **Szerver kezelése** jogosultság kell.", ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ A panelt szöveges csatornában használd.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        message = await self._post_gamble_room_panel(interaction.channel)
        await interaction.followup.send(f"✅ A Gamble Room panel kirakva: {message.jump_url}", ephemeral=True)

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

    @app_commands.command(name="mines", description="Mines: mező reveal + push-your-luck cashout.")
    @app_commands.describe(osszeg="Tét", bombak="3 / 5 / 7 / 9")
    @app_commands.choices(bombak=[app_commands.Choice(name="3",value=3),app_commands.Choice(name="5",value=5),app_commands.Choice(name="7",value=7),app_commands.Choice(name="9",value=9)])
    async def mines_game(self, interaction: discord.Interaction, osszeg: str, bombak: app_commands.Choice[int] | None = None) -> None:
        if not await self._guard(interaction): return
        wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        count=int(bombak.value) if bombak is not None else 3
        await self.start_mines_interaction(interaction,bet,count)

    @app_commands.command(name="chickenroad", description="Chicken Road: sávonként tovább vagy cashout.")
    async def chickenroad_game(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction): return
        wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await self.start_chicken_road_interaction(interaction,bet)

    @app_commands.command(name="plinko", description="Plinko panel: tét/labda, 1/2/3/5/10 Ball batch, Fast és Auto.")
    @app_commands.describe(osszeg="Kezdő tét (később a panelen módosítható)")
    async def plinko_game(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction): return
        wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await self.open_plinko_interaction(interaction,bet)

    @app_commands.command(name="candyrush", description="Candy Rush: 6×6 cascade játék.")
    async def candyrush_game(self, interaction: discord.Interaction, osszeg: str) -> None:
        if not await self._guard(interaction): return
        wallet,_=await self.casino.db.get_balance(interaction.guild_id,interaction.user.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await interaction.response.send_message(embed=error_embed(interaction.user,str(exc)),ephemeral=True)
        await self.run_candy_rush_interaction(interaction,bet)

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

    @commands.command(name="mines", aliases=["mine"])
    @commands.guild_only()
    async def mines_prefix(self, ctx: commands.Context, osszeg: str, bombak: int = 3) -> None:
        if not await self._guard_prefix(ctx): return
        wallet,_=await self.casino.db.get_balance(ctx.guild.id,ctx.author.id)
        try:
            bet=parse_amount(osszeg,wallet)
            if int(bombak) not in MINES_ALLOWED_COUNTS: raise ValueError(f"Bombák: {', '.join(map(str, MINES_ALLOWED_COUNTS))}.")
        except ValueError as exc: return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await self.start_mines_prefix(ctx,bet,int(bombak))

    @commands.command(name="chickenroad", aliases=["croad","roadchicken"])
    @commands.guild_only()
    async def chickenroad_prefix(self, ctx: commands.Context, osszeg: str) -> None:
        if not await self._guard_prefix(ctx): return
        wallet,_=await self.casino.db.get_balance(ctx.guild.id,ctx.author.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await self.start_chicken_road_prefix(ctx,bet)

    @commands.command(name="plinko", aliases=["plink"])
    @commands.guild_only()
    async def plinko_prefix(self, ctx: commands.Context, osszeg: str, _legacy_legacy_option: str | None = None) -> None:
        if not await self._guard_prefix(ctx): return
        wallet,_=await self.casino.db.get_balance(ctx.guild.id,ctx.author.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await self.open_plinko_prefix(ctx,bet)

    @commands.command(name="candyrush", aliases=["candy","rush"])
    @commands.guild_only()
    async def candyrush_prefix(self, ctx: commands.Context, osszeg: str) -> None:
        if not await self._guard_prefix(ctx): return
        wallet,_=await self.casino.db.get_balance(ctx.guild.id,ctx.author.id)
        try: bet=parse_amount(osszeg,wallet)
        except ValueError as exc: return await ctx.send(embed=error_embed(ctx.author,str(exc)))
        await self.run_candy_rush_prefix(ctx,bet)

    @commands.command(name="casino", aliases=["kaszino", "kaszinó"])
    @commands.guild_only()
    async def casino_prefix(self, ctx: commands.Context) -> None:
        try:
            await self.casino.guild_settings.prepare_currency(ctx.guild.id)
            await self.casino.guild_settings.require_feature(ctx.guild.id, "gambling")
        except ValueError as exc:
            return await ctx.send(embed=error_embed(ctx.author, str(exc)))
        if not is_gamble_room(ctx.channel):
            try:
                await self.casino.guild_settings.require_channel(ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None))
            except ValueError:
                await handle_wrong_gambling_channel(ctx, self.casino)
                return
        await ctx.send(embed=await self.lobby_embed(ctx.guild.id, ctx.author), view=CasinoLobbyView(self, ctx.author.id))


    @commands.command(name="gamblepanel", aliases=["gpanel", "gamblingpanel"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def gamblepanel_prefix(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.send(embed=error_embed(ctx.author, "A panelt szöveges csatornában használd."))
        await self._post_gamble_room_panel(ctx.channel)
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass
