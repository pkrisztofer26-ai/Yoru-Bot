from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from app.amounts import parse_amount
from app.database import Database
from app.services.economy import EconomyService
from app.services.server_settings import ServerSettingsService
from app.cogs.access_utils import handle_wrong_economy_channel
from app.ui import base_embed, money, GOLD, SUCCESS
from app import economy_config as eco
from app import community_config as communitycfg


@dataclass
class JackpotRound:
    guild_id: int
    channel_id: int
    end_at: datetime
    entries: dict[int, int] = field(default_factory=dict)
    message_id: int | None = None
    task: asyncio.Task | None = None


@dataclass
class BlackMarketState:
    expires_at: datetime
    items: dict[str, tuple[int, int]]  # item_id -> (discounted price, stock)


class BlackMarketBuyButton(discord.ui.Button):
    def __init__(self, cog, guild_id: int, item_id: str, price: int) -> None:
        super().__init__(
            label=money(price),
            emoji="💰",
            style=discord.ButtonStyle.success,
            custom_id=f"yoru_bm_buy:{guild_id}:{item_id}",
        )
        self.cog = cog
        self.guild_id = guild_id
        self.item_id = item_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id != self.guild_id:
            return await interaction.response.send_message(
                "❌ Ez a Feketepiac nem ehhez a szerverhez tartozik.", ephemeral=True
            )

        state = self.cog.black_markets.get(self.guild_id)
        if not state or state.expires_at <= datetime.now(timezone.utc):
            return await interaction.response.send_message(
                "🌑 A Feketepiac már bezárt.", ephemeral=True
            )

        if self.item_id not in state.items:
            return await interaction.response.send_message(
                "❌ Ez a tárgy már nem érhető el.", ephemeral=True
            )

        price, stock = state.items[self.item_id]
        if stock <= 0:
            return await interaction.response.send_message(
                "❌ Ez a tárgy elfogyott.", ephemeral=True
            )

        wallet, _ = await self.cog.db.get_balance(self.guild_id, interaction.user.id)
        if wallet < price:
            return await interaction.response.send_message(
                f"❌ Nincs elég pénzed. Szükséges: **{money(price)}**", ephemeral=True
            )

        await self.cog.db.add_wallet(
            self.guild_id, interaction.user.id, -price, f"black_market:{self.item_id}x1"
        )
        await self.cog.db.add_item(self.guild_id, interaction.user.id, self.item_id, 1)
        await self.cog.bot.statistics.increment(self.guild_id, interaction.user.id, "market.black_market.purchases")
        await self.cog.bot.statistics.add(self.guild_id, interaction.user.id, "market.black_market.spent", price)
        await self.cog.bot.statistics.increment(self.guild_id, interaction.user.id, f"market.black_market.item.{self.item_id}.bought")
        state.items[self.item_id] = (price, stock - 1)

        info = await self.cog.db.get_shop_item(self.item_id)
        if info:
            name, emoji = info[0], info[1]
        else:
            name, emoji = self.item_id, "📦"

        new_wallet, _ = await self.cog.db.get_balance(self.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"✅ Megvetted: **{emoji} {name}**\n"
            f"💰 Ár: **{money(price)}**\n"
            f"👛 Maradék: **{money(new_wallet)}**\n"
            f"📦 Készlet: **{stock - 1} db**",
            ephemeral=True,
        )

        if interaction.message is not None:
            try:
                view = await self.cog._build_black_market_view(self.guild_id)
                await interaction.message.edit(view=view)
            except discord.HTTPException:
                pass


class BlackMarketRefreshButton(discord.ui.Button):
    def __init__(self, cog, guild_id: int) -> None:
        super().__init__(
            label="Frissítés",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            custom_id=f"yoru_bm_refresh:{guild_id}",
        )
        self.cog = cog
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        state = self.cog.black_markets.get(self.guild_id)
        if not state or state.expires_at <= datetime.now(timezone.utc):
            return await interaction.response.send_message("🌑 A Feketepiac már bezárt.", ephemeral=True)
        view = await self.cog._build_black_market_view(self.guild_id)
        await interaction.response.edit_message(view=view)



LOGGER = logging.getLogger("yoru.community")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_duration_minutes(raw: str, *, minimum: int, maximum: int) -> int:
    value = str(raw).strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)([mhd]?)", value)
    if not match:
        raise ValueError("Időtartam példa: `30m`, `2h`, `1d` vagy `90` (perc).")
    amount = int(match.group(1))
    unit = match.group(2) or "m"
    multiplier = {"m": 1, "h": 60, "d": 1440}[unit]
    minutes = amount * multiplier
    if minutes < minimum or minutes > maximum:
        raise ValueError(f"Az időtartam {minimum} és {maximum} perc között lehet.")
    return minutes


class SuggestionVoteButton(discord.ui.Button):
    def __init__(self, cog: "CommunityCog", suggestion_id: int, vote: int, count: int, *, disabled: bool = False) -> None:
        emoji = "👍" if vote > 0 else "👎"
        super().__init__(
            label=str(count),
            emoji=emoji,
            style=discord.ButtonStyle.success if vote > 0 else discord.ButtonStyle.danger,
            custom_id=f"yoru:suggestion:{suggestion_id}:vote:{'up' if vote > 0 else 'down'}",
            disabled=disabled,
        )
        self.cog = cog
        self.suggestion_id = suggestion_id
        self.vote = 1 if vote > 0 else -1

    async def callback(self, interaction: discord.Interaction) -> None:
        row = await self.cog.db.get_community_suggestion(self.suggestion_id)
        if row is None or row["status"] != "pending":
            return await interaction.response.send_message("ℹ️ Ez a javaslat már lezárult.", ephemeral=True)
        if interaction.guild_id != row["guild_id"]:
            return await interaction.response.send_message("❌ Ez a javaslat nem ehhez a szerverhez tartozik.", ephemeral=True)
        up, down, current = await self.cog.db.toggle_community_suggestion_vote(
            self.suggestion_id, interaction.user.id, self.vote
        )
        await interaction.response.edit_message(
            embed=self.cog._suggestion_embed({**row, "upvotes": up, "downvotes": down}),
            view=SuggestionView(self.cog, self.suggestion_id, up, down),
        )
        label = "szavazatod törölve" if current == 0 else ("pozitív szavazat" if current > 0 else "negatív szavazat")
        try:
            await interaction.followup.send(f"✅ {label.capitalize()}.", ephemeral=True)
        except discord.HTTPException:
            pass


class SuggestionStaffButton(discord.ui.Button):
    def __init__(self, cog: "CommunityCog", suggestion_id: int, status: str, *, disabled: bool = False) -> None:
        approved = status == "approved"
        super().__init__(
            label="Elfogadás" if approved else "Elutasítás",
            emoji="✅" if approved else "❌",
            style=discord.ButtonStyle.success if approved else discord.ButtonStyle.danger,
            custom_id=f"yoru:suggestion:{suggestion_id}:status:{status}",
            disabled=disabled,
        )
        self.cog = cog
        self.suggestion_id = suggestion_id
        self.status = status

    async def callback(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Ehhez **Üzenetek kezelése** jogosultság kell.", ephemeral=True)
        row = await self.cog.db.get_community_suggestion(self.suggestion_id)
        if row is None:
            return await interaction.response.send_message("❌ A javaslat nem található.", ephemeral=True)
        if interaction.guild_id != row["guild_id"]:
            return await interaction.response.send_message("❌ Ez a javaslat nem ehhez a szerverhez tartozik.", ephemeral=True)
        if row["status"] != "pending":
            return await interaction.response.send_message("ℹ️ Ez a javaslat már lezárult.", ephemeral=True)
        await self.cog.db.set_community_suggestion_status(self.suggestion_id, self.status, interaction.user.id)
        row = await self.cog.db.get_community_suggestion(self.suggestion_id)
        await interaction.response.edit_message(embed=self.cog._suggestion_embed(row), view=SuggestionView.from_row(self.cog, row, disabled=True))


class SuggestionView(discord.ui.View):
    def __init__(self, cog: "CommunityCog", suggestion_id: int, upvotes: int, downvotes: int, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.add_item(SuggestionVoteButton(cog, suggestion_id, 1, upvotes, disabled=disabled))
        self.add_item(SuggestionVoteButton(cog, suggestion_id, -1, downvotes, disabled=disabled))
        self.add_item(SuggestionStaffButton(cog, suggestion_id, "approved", disabled=disabled))
        self.add_item(SuggestionStaffButton(cog, suggestion_id, "denied", disabled=disabled))

    @classmethod
    def from_row(cls, cog: "CommunityCog", row: dict, *, disabled: bool | None = None) -> "SuggestionView":
        if disabled is None:
            disabled = row["status"] != "pending"
        return cls(cog, row["suggestion_id"], row["upvotes"], row["downvotes"], disabled=disabled)


class PollVoteButton(discord.ui.Button):
    NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    def __init__(self, cog: "CommunityCog", poll_id: int, option_index: int, count: int, *, disabled: bool = False) -> None:
        super().__init__(
            label=str(count),
            emoji=self.NUMBERS[option_index],
            style=discord.ButtonStyle.primary,
            custom_id=f"yoru:poll:{poll_id}:vote:{option_index}",
            disabled=disabled,
        )
        self.cog = cog
        self.poll_id = poll_id
        self.option_index = option_index

    async def callback(self, interaction: discord.Interaction) -> None:
        row = await self.cog.db.get_community_poll(self.poll_id)
        if row is None or row["closed"]:
            return await interaction.response.send_message("ℹ️ Ez a szavazás már lezárult.", ephemeral=True)
        if interaction.guild_id != row["guild_id"]:
            return await interaction.response.send_message("❌ Ez a szavazás nem ehhez a szerverhez tartozik.", ephemeral=True)
        closes_at = datetime.fromisoformat(row["closes_at"])
        if closes_at <= _utcnow():
            await self.cog._finish_poll(self.poll_id)
            return await interaction.response.send_message("ℹ️ Ez a szavazás épp most zárult le.", ephemeral=True)
        current, counts = await self.cog.db.toggle_community_poll_vote(self.poll_id, interaction.user.id, self.option_index)
        row["counts"] = counts
        await interaction.response.edit_message(embed=self.cog._poll_embed(row), view=PollView.from_row(self.cog, row))
        text = "Szavazatod törölve." if current < 0 else f"Szavazatod: **{row['options'][current]}**"
        try:
            await interaction.followup.send(f"✅ {text}", ephemeral=True)
        except discord.HTTPException:
            pass


class PollView(discord.ui.View):
    def __init__(self, cog: "CommunityCog", poll_id: int, option_count: int, counts: dict[int, int], *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        for index in range(option_count):
            self.add_item(PollVoteButton(cog, poll_id, index, int(counts.get(index, 0)), disabled=disabled))

    @classmethod
    def from_row(cls, cog: "CommunityCog", row: dict, *, disabled: bool | None = None) -> "PollView":
        if disabled is None:
            disabled = bool(row["closed"])
        return cls(cog, row["poll_id"], len(row["options"]), row.get("counts", {}), disabled=disabled)


class GiveawayJoinButton(discord.ui.Button):
    def __init__(self, cog: "CommunityCog", giveaway_id: int, count: int, *, disabled: bool = False) -> None:
        super().__init__(
            label=f"Jelentkezés • {count}",
            emoji="🎉",
            style=discord.ButtonStyle.success,
            custom_id=f"yoru:giveaway:{giveaway_id}:join",
            disabled=disabled,
        )
        self.cog = cog
        self.giveaway_id = giveaway_id

    async def callback(self, interaction: discord.Interaction) -> None:
        row = await self.cog.db.get_community_giveaway(self.giveaway_id)
        if row is None or row["ended"]:
            return await interaction.response.send_message("ℹ️ Ez a giveaway már lezárult.", ephemeral=True)
        if interaction.guild_id != row["guild_id"]:
            return await interaction.response.send_message("❌ Ez a giveaway nem ehhez a szerverhez tartozik.", ephemeral=True)
        if datetime.fromisoformat(row["ends_at"]) <= _utcnow():
            await self.cog._finish_giveaway(self.giveaway_id)
            return await interaction.response.send_message("ℹ️ Ez a giveaway épp most zárult le.", ephemeral=True)
        if interaction.user.bot:
            return await interaction.response.send_message("❌ Bot nem jelentkezhet giveawayre.", ephemeral=True)
        joined, count = await self.cog.db.toggle_community_giveaway_entry(self.giveaway_id, interaction.user.id)
        row["entries"] = [0] * count
        await interaction.response.edit_message(embed=self.cog._giveaway_embed(row), view=GiveawayView(self.cog, self.giveaway_id, count))
        try:
            await interaction.followup.send("✅ Jelentkeztél." if joined else "↩️ Visszavontad a jelentkezést.", ephemeral=True)
        except discord.HTTPException:
            pass


class GiveawayView(discord.ui.View):
    def __init__(self, cog: "CommunityCog", giveaway_id: int, count: int, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.add_item(GiveawayJoinButton(cog, giveaway_id, count, disabled=disabled))


class SuggestionModal(discord.ui.Modal, title="Új javaslat"):
    suggestion = discord.ui.TextInput(
        label="Javaslat",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=communitycfg.SUGGESTIONS_MAX_LENGTH,
        placeholder="Írd le az ötletedet…",
    )

    def __init__(self, cog: "CommunityCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            message = await self.cog._create_suggestion(interaction.guild, interaction.user, str(self.suggestion.value))
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(f"✅ Javaslat elküldve: {message.jump_url}", ephemeral=True)


class PollModal(discord.ui.Modal, title="Új szavazás"):
    question = discord.ui.TextInput(label="Kérdés", min_length=3, max_length=256)
    options = discord.ui.TextInput(
        label="Opciók – soronként egy",
        style=discord.TextStyle.paragraph,
        min_length=3,
        max_length=1000,
        placeholder="Igen\nNem\nTalán",
    )
    duration = discord.ui.TextInput(label="Időtartam", required=False, max_length=12, placeholder="pl. 30m / 2h / 1d")

    def __init__(self, cog: "CommunityCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Ezt normál szöveges szervercsatornában használd.", ephemeral=True)
        default_minutes = await self.cog.settings_service.get_poll_default_duration_minutes(interaction.guild.id)
        raw_duration = str(self.duration.value).strip() or str(default_minutes)
        try:
            minutes = _parse_duration_minutes(
                raw_duration,
                minimum=communitycfg.POLLS_MIN_DURATION_MINUTES,
                maximum=communitycfg.POLLS_MAX_DURATION_MINUTES,
            )
            options = [line.strip() for line in str(self.options.value).splitlines() if line.strip()]
            await self.cog._create_poll(interaction.guild, interaction.channel, interaction.user, str(self.question.value), options, minutes)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message("✅ Szavazás létrehozva.", ephemeral=True)


class GiveawayModal(discord.ui.Modal, title="Giveaway létrehozása"):
    prize = discord.ui.TextInput(label="Nyeremény", min_length=1, max_length=500, placeholder="pl. 1 hónap Discord Nitro")
    duration = discord.ui.TextInput(label="Időtartam", required=False, max_length=12, placeholder="pl. 1h / 1d")
    winners = discord.ui.TextInput(label="Nyertesek száma", required=False, max_length=2, placeholder="1")

    def __init__(self, cog: "CommunityCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Ez csak szöveges szervercsatornában használható.", ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Ehhez **Üzenetek kezelése** jogosultság kell.", ephemeral=True)
        default_minutes = await self.cog.settings_service.get_giveaway_default_duration_minutes(interaction.guild.id)
        raw_duration = str(self.duration.value).strip() or str(default_minutes)
        try:
            minutes = _parse_duration_minutes(
                raw_duration,
                minimum=communitycfg.GIVEAWAYS_MIN_DURATION_MINUTES,
                maximum=communitycfg.GIVEAWAYS_MAX_DURATION_MINUTES,
            )
            winner_count = int(str(self.winners.value).strip() or "1")
            if winner_count < 1 or winner_count > communitycfg.GIVEAWAYS_MAX_WINNERS:
                raise ValueError(f"A nyertesek száma 1–{communitycfg.GIVEAWAYS_MAX_WINNERS} lehet.")
            await self.cog._create_giveaway(interaction.guild, interaction.channel, interaction.user, str(self.prize.value), minutes, winner_count)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message("✅ Giveaway létrehozva.", ephemeral=True)


class CommunityCog(commands.GroupCog, group_name="community", group_description="Yoru közösségi eszközök és közösségi economy."):
    LOTTERY_TICKET_PRICE = eco.LOTTERY_TICKET_PRICE
    LOTTERY_INTERVAL = timedelta(hours=eco.LOTTERY_INTERVAL_HOURS)
    JACKPOT_SECONDS = eco.JACKPOT_SECONDS

    def __init__(self, bot: commands.Bot, db: Database, economy: EconomyService) -> None:
        self.bot = bot
        self.db = db
        self.economy = economy
        self.jackpots: dict[int, JackpotRound] = {}
        self.black_markets: dict[int, BlackMarketState] = {}
        self.lottery_task: asyncio.Task | None = None
        self.market_task: asyncio.Task | None = None
        self._next_market_event_at: dict[int, float] = {}
        self.next_lottery_at = datetime.now(timezone.utc) + self.LOTTERY_INTERVAL
        self.settings_service = ServerSettingsService(db)
        self.poll_tasks: dict[int, asyncio.Task] = {}
        self.giveaway_tasks: dict[int, asyncio.Task] = {}
        self._afk_notice_times: dict[tuple[int, int, int], float] = {}
        self._sticky_locks: set[tuple[int, int]] = set()

    async def cog_load(self) -> None:
        self.lottery_task = asyncio.create_task(self._lottery_loop())
        await self._restore_community_runtime()
        self.market_task = asyncio.create_task(self._market_loop())

    async def cog_unload(self) -> None:
        for task in [self.lottery_task, self.market_task, *self.poll_tasks.values(), *self.giveaway_tasks.values()]:
            if task:
                task.cancel()
        for round_ in self.jackpots.values():
            if round_.task:
                round_.task.cancel()

    def reschedule_event_config(self, guild_id: int) -> None:
        self._next_market_event_at.pop(guild_id, None)

    async def _jackpot_embed(self, round_: JackpotRound, finished: bool = False, winner_id: int | None = None, payout: int = 0) -> discord.Embed:
        total = sum(round_.entries.values())
        if finished:
            desc = f"🏆 Nyertes: <@{winner_id}>\n💰 Kifizetés: **{money(payout)}**\n🎟️ Teljes pot: **{money(total)}**"
            return base_embed("🎰 JACKPOT LEZÁRVA", desc, GOLD)
        lines = []
        for uid, amount in sorted(round_.entries.items(), key=lambda x: x[1], reverse=True)[:12]:
            chance = (amount / total * 100) if total else 0
            lines.append(f"<@{uid}> — **{money(amount)}** • `{chance:.1f}%`")
        desc = "\n".join(lines) if lines else "Még nincs játékos."
        embed = base_embed("🎰 KÖZÖSSÉGI JACKPOT", desc, GOLD)
        embed.add_field(name="💰 Pot", value=money(total), inline=True)
        embed.add_field(name="👥 Játékosok", value=str(len(round_.entries)), inline=True)
        embed.add_field(name="⏳ Sorsolás", value=f"<t:{int(round_.end_at.timestamp())}:R>", inline=False)
        embed.add_field(name="Beszállás", value="`!jackpot 25k` vagy `/community jackpot`", inline=False)
        return embed

    async def _edit_jackpot_message(self, round_: JackpotRound) -> None:
        if not round_.message_id:
            return
        channel = self.bot.get_channel(round_.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            msg = await channel.fetch_message(round_.message_id)
            await msg.edit(embed=await self._jackpot_embed(round_))
        except discord.HTTPException:
            pass

    async def _join_jackpot(self, guild_id: int, channel_id: int, user_id: int, amount: int, category_id: int | None = None) -> JackpotRound:
        await self.economy.require_access(guild_id, "economy", channel_id, category_id)
        await self.economy.require_not_jailed(guild_id, user_id)
        wallet, _ = await self.economy.balance(guild_id, user_id)
        if amount < eco.JACKPOT_MIN_ENTRY:
            raise ValueError(f"A minimum Jackpot beszálló {money(eco.JACKPOT_MIN_ENTRY)}.")
        if amount > wallet:
            raise ValueError("Nincs ennyi pénz a tárcádban.")
        await self.db.add_wallet(guild_id, user_id, -amount, "jackpot_entry")
        await self.bot.statistics.increment(guild_id, user_id, "community.jackpot.entries")
        await self.bot.statistics.add(guild_id, user_id, "community.jackpot.spent", amount)
        round_ = self.jackpots.get(guild_id)
        if round_ is None:
            round_ = JackpotRound(guild_id, channel_id, datetime.now(timezone.utc) + timedelta(seconds=self.JACKPOT_SECONDS))
            self.jackpots[guild_id] = round_
            round_.task = asyncio.create_task(self._finish_jackpot(round_))
        round_.entries[user_id] = round_.entries.get(user_id, 0) + amount
        await self._edit_jackpot_message(round_)
        return round_

    async def _finish_jackpot(self, round_: JackpotRound) -> None:
        delay = max(0, (round_.end_at - datetime.now(timezone.utc)).total_seconds())
        await asyncio.sleep(delay)
        current = self.jackpots.get(round_.guild_id)
        if current is not round_:
            return
        channel = self.bot.get_channel(round_.channel_id)
        if len(round_.entries) < 2:
            for uid, amount in round_.entries.items():
                await self.db.refund_wallet(round_.guild_id, uid, amount, "jackpot_refund")
            if isinstance(channel, discord.TextChannel):
                await channel.send("🎰 A Jackpot elmaradt, mert nem volt legalább 2 játékos. Minden tét visszajárt.")
            self.jackpots.pop(round_.guild_id, None)
            return
        users = list(round_.entries)
        weights = [round_.entries[u] for u in users]
        winner = random.choices(users, weights=weights, k=1)[0]
        total = sum(weights)
        payout = int(total * eco.JACKPOT_PAYOUT_SHARE)
        await self.db.add_wallet(round_.guild_id, winner, payout, "jackpot_win")
        await self.db.increment_stat(round_.guild_id, winner, "jackpot_wins")
        await self.bot.statistics.increment(round_.guild_id, winner, "community.jackpot.wins")
        await self.bot.statistics.add(round_.guild_id, winner, "community.jackpot.earned", payout)
        await self.bot.statistics.set_max(round_.guild_id, winner, "community.jackpot.biggest_win", payout)
        if isinstance(channel, discord.TextChannel):
            if round_.message_id:
                try:
                    msg = await channel.fetch_message(round_.message_id)
                    await msg.edit(embed=await self._jackpot_embed(round_, True, winner, payout))
                except discord.HTTPException:
                    await channel.send(embed=await self._jackpot_embed(round_, True, winner, payout))
            else:
                await channel.send(embed=await self._jackpot_embed(round_, True, winner, payout))
        self.jackpots.pop(round_.guild_id, None)

    @app_commands.command(name="jackpot", description="Megmutatja a Monthly Global Jackpotot.")
    async def jackpot_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        casino = self.bot.get_cog("CasinoCog")
        if casino is None:
            return await interaction.response.send_message("❌ A Casino modul nem elérhető.", ephemeral=True)
        await interaction.response.send_message(embed=await casino.jackpot_embed(interaction.guild_id, interaction.user))

    @commands.command(name="jackpot", aliases=["jp", "pot"])
    @commands.guild_only()
    async def jackpot_prefix(self, ctx: commands.Context, amount: str | None = None) -> None:
        casino = self.bot.get_cog("CasinoCog")
        if casino is None:
            return await ctx.send("❌ A Casino modul nem elérhető.")
        await ctx.send(embed=await casino.jackpot_embed(ctx.guild.id, ctx.author))

    async def _lottery_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            self.next_lottery_at = datetime.now(timezone.utc) + self.LOTTERY_INTERVAL
            await asyncio.sleep(self.LOTTERY_INTERVAL.total_seconds())
            for guild in self.bot.guilds:
                await self._draw_lottery(guild)

    async def _draw_lottery(self, guild: discord.Guild, force_channel: discord.TextChannel | None = None) -> None:
        await self.economy.prepare_context(guild.id)
        entries = await self.db.get_lottery_entries(guild.id)
        if not entries:
            return
        total_tickets = sum(t for _, t in entries)
        users = [u for u, _ in entries]
        weights = [t for _, t in entries]
        winner = random.choices(users, weights=weights, k=1)[0]
        pot = max(eco.LOTTERY_MIN_POT, int(total_tickets * self.LOTTERY_TICKET_PRICE * eco.LOTTERY_PAYOUT_SHARE))
        await self.db.add_wallet(guild.id, winner, pot, "lottery_win")
        await self.db.increment_stat(guild.id, winner, "lottery_wins")
        await self.bot.statistics.increment(guild.id, winner, "community.lottery.wins")
        await self.bot.statistics.add(guild.id, winner, "community.lottery.earned", pot)
        await self.bot.statistics.set_max(guild.id, winner, "community.lottery.biggest_win", pot)
        await self.db.add_lottery_history(guild.id, winner, total_tickets, pot)
        await self.db.clear_lottery(guild.id)
        channel = force_channel
        if channel is None:
            event_cfg = await self.economy.guild_settings.get_event_config(guild.id, self.bot.settings)
            if event_cfg.channel_id:
                candidate = guild.get_channel(event_cfg.channel_id)
                if isinstance(candidate, discord.TextChannel):
                    channel = candidate
        if channel:
            await channel.send(embed=base_embed("🎟️ YORU LOTTERY", f"🏆 Nyertes: <@{winner}>\n🎫 Jegyek: **{total_tickets} db**\n💰 Nyeremény: **{money(pot)}**", GOLD))

    async def _buy_lottery(self, guild_id: int, user_id: int, tickets: int, channel_id: int | None = None, category_id: int | None = None) -> int:
        await self.economy.require_access(guild_id, "economy", channel_id, category_id)
        if tickets < 1 or tickets > eco.LOTTERY_MAX_TICKETS_PER_BUY:
            raise ValueError(f"Egyszerre 1–{eco.LOTTERY_MAX_TICKETS_PER_BUY} jegyet vehetsz.")
        cost = tickets * self.LOTTERY_TICKET_PRICE
        wallet, _ = await self.db.get_balance(guild_id, user_id)
        if wallet < cost:
            raise ValueError("Nincs elég pénzed ennyi jegyre.")
        await self.db.add_wallet(guild_id, user_id, -cost, f"lottery_tickets:{tickets}")
        await self.db.add_lottery_tickets(guild_id, user_id, tickets)
        await self.bot.statistics.increment(guild_id, user_id, "community.lottery.tickets", tickets)
        await self.bot.statistics.add(guild_id, user_id, "community.lottery.spent", cost)
        return cost

    @app_commands.command(name="lottery", description="Yoru lottery jegyek vásárlása.")
    async def lottery_slash(self, interaction: discord.Interaction, jegyek: app_commands.Range[int, 1, 1000] = 1) -> None:
        if interaction.guild_id is None:
            return
        try:
            cost = await self._buy_lottery(interaction.guild_id, interaction.user.id, jegyek, interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        await interaction.response.send_message(f"🎟️ Vettél **{jegyek} db** lottery jegyet **{money(cost)}** összegért.\nSorsolás: <t:{int(self.next_lottery_at.timestamp())}:R>")

    @commands.command(name="lottery", aliases=["lotto", "lot", "lottó"])
    @commands.guild_only()
    async def lottery_prefix(self, ctx: commands.Context, tickets: int = 1) -> None:
        try:
            cost = await self._buy_lottery(ctx.guild.id, ctx.author.id, tickets, ctx.channel.id, getattr(ctx.channel, "category_id", None))
        except ValueError as error:
            return await ctx.send(f"❌ {error}")
        await ctx.send(f"🎟️ Vettél **{tickets} db** lottery jegyet **{money(cost)}** összegért. Sorsolás: <t:{int(self.next_lottery_at.timestamp())}:R>")

    @commands.command(name="drawlottery", aliases=["drawlot"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def drawlottery(self, ctx: commands.Context) -> None:
        await self._draw_lottery(ctx.guild, ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None)
        await ctx.message.add_reaction("✅")

    async def _market_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = time.monotonic()
            for guild in list(self.bot.guilds):
                try:
                    event_cfg = await self.economy.guild_settings.get_event_config(guild.id, self.bot.settings)
                    if not event_cfg.auto_enabled or not event_cfg.channel_id:
                        self._next_market_event_at.pop(guild.id, None)
                        continue
                    channel = guild.get_channel(event_cfg.channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        continue
                    due = self._next_market_event_at.get(guild.id)
                    if due is None:
                        delay = random.uniform(eco.GUILD_ECONOMY_EVENT_MIN_HOURS, eco.GUILD_ECONOMY_EVENT_MAX_HOURS) * 3600
                        self._next_market_event_at[guild.id] = now + delay
                        continue
                    if now < due:
                        continue

                    await self.economy.prepare_context(guild.id)
                    event = random.choice(["blackmarket", "double_work", "crime_rush", "lucky_hour"])
                    if event == "blackmarket":
                        if guild.id not in self.black_markets or self.black_markets[guild.id].expires_at <= datetime.now(timezone.utc):
                            await self._open_black_market(channel)
                    elif event == "double_work":
                        expires = datetime.now(timezone.utc) + timedelta(hours=eco.GUILD_ECONOMY_EVENT_DURATION_HOURS)
                        await self.db.set_guild_effect(guild.id, "work_multiplier", eco.GUILD_EVENT_WORK_MULTIPLIER, expires)
                        await channel.send(embed=base_embed("🛠️ WORK RUSH", f"A `!work` jutalmak **x{eco.GUILD_EVENT_WORK_MULTIPLIER:.2f}** szorzót kaptak!\n⏳ Vége: <t:{int(expires.timestamp())}:R>", SUCCESS))
                    elif event == "crime_rush":
                        expires = datetime.now(timezone.utc) + timedelta(hours=eco.GUILD_ECONOMY_EVENT_DURATION_HOURS)
                        await self.db.set_guild_effect(guild.id, "crime_multiplier", eco.GUILD_EVENT_CRIME_MULTIPLIER, expires)
                        await channel.send(embed=base_embed("🚨 CRIME RUSH", f"A sikeres `!crime` jutalmak **x{eco.GUILD_EVENT_CRIME_MULTIPLIER:.2f}** szorzót kaptak!\n⏳ Vége: <t:{int(expires.timestamp())}:R>"))
                    else:
                        expires = datetime.now(timezone.utc) + timedelta(hours=eco.GUILD_ECONOMY_EVENT_DURATION_HOURS)
                        await self.db.set_guild_effect(guild.id, "luck_multiplier", eco.GUILD_EVENT_LUCK_MULTIPLIER, expires)
                        await channel.send(embed=base_embed("🍀 LUCKY HOUR", f"Jobb esélyek a ládáknál és sorsjegyeknél.\n⏳ Vége: <t:{int(expires.timestamp())}:R>", SUCCESS))
                    delay = random.uniform(eco.GUILD_ECONOMY_EVENT_MIN_HOURS, eco.GUILD_ECONOMY_EVENT_MAX_HOURS) * 3600
                    self._next_market_event_at[guild.id] = time.monotonic() + delay
                except Exception:
                    logger.exception("Community economy event loop hiba guild=%s", guild.id)
                    self._next_market_event_at[guild.id] = time.monotonic() + 60
            await asyncio.sleep(10)


    async def _build_black_market_view(self, guild_id: int) -> discord.ui.LayoutView:
        state = self.black_markets.get(guild_id)
        view = discord.ui.LayoutView(timeout=900)
        container = discord.ui.Container(accent_colour=discord.Colour.dark_purple())

        if not state or state.expires_at <= datetime.now(timezone.utc):
            container.add_item(discord.ui.TextDisplay(
                "# 🌑 Yoru Feketepiac\n*A Feketepiac jelenleg zárva van.*"
            ))
            view.add_item(container)
            return view

        container.add_item(discord.ui.TextDisplay(
            "# 🌑 Yoru Feketepiac\n"
            "Limitált készletű, kedvezményes tárgyak. Kattints a jobb oldali **ár gombra** az azonnali vásárláshoz.\n"
            f"⏳ Bezár: <t:{int(state.expires_at.timestamp())}:R>"
        ))
        container.add_item(discord.ui.Separator())

        for index, (item_id, (price, stock)) in enumerate(state.items.items()):
            item = await self.db.get_shop_item(item_id)
            if not item:
                continue
            name, emoji, normal_price, rarity, description = item
            discount_pct = max(0, round((1 - (price / max(1, normal_price))) * 100))
            stock_text = "**ELFOGYOTT**" if stock <= 0 else f"**{stock} db**"
            text = (
                f"### {emoji} {name}\n"
                f"{description}\n"
                f"`{item_id}` • {rarity.title()}\n"
                f"📦 Készlet: {stock_text} • 🏷️ **-{discount_pct}%** • normál ár: ~~{money(normal_price)}~~"
            )
            button = BlackMarketBuyButton(self, guild_id, item_id, price)
            button.disabled = stock <= 0
            container.add_item(discord.ui.Section(discord.ui.TextDisplay(text), accessory=button))
            if index != len(state.items) - 1:
                container.add_item(discord.ui.Separator())

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "-# A gombos vásárlás 1 darabot vesz. Több darabhoz: `!bm buy <id> <db>` vagy `/community blackmarketbuy`."
        ))
        view.add_item(container)
        view.add_item(discord.ui.ActionRow(BlackMarketRefreshButton(self, guild_id)))
        return view

    async def _open_black_market(self, channel: discord.TextChannel) -> None:
        await self.economy.prepare_context(channel.guild.id)
        candidates = ["rare_crate", "epic_crate", "legendary_crate", "work_booster", "crime_booster", "luck_booster", "rob_booster", "interest_booster", "rob_shield"]
        chosen = random.sample(candidates, k=4)
        items: dict[str, tuple[int, int]] = {}
        for item_id in chosen:
            item = await self.db.get_shop_item(item_id)
            if not item:
                continue
            _, _, price, _, _ = item
            discount = random.uniform(*eco.BLACK_MARKET_PRICE_MULTIPLIER)
            bm_price = max(1, int(price * discount))
            stock = random.randint(1, 5)
            items[item_id] = (bm_price, stock)
        expires = datetime.now(timezone.utc) + timedelta(minutes=eco.BLACK_MARKET_DURATION_MINUTES)
        self.black_markets[channel.guild.id] = BlackMarketState(expires, items)
        await channel.send(view=await self._build_black_market_view(channel.guild.id))

    @app_commands.command(name="blackmarket", description="Megmutatja az aktuális Feketepiacot.")
    async def blackmarket_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        try:
            await self.economy.require_access(interaction.guild_id, "economy", interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        state = self.black_markets.get(interaction.guild_id)
        if not state or state.expires_at <= datetime.now(timezone.utc):
            return await interaction.response.send_message("🌑 A Feketepiac jelenleg zárva van.", ephemeral=True)
        await interaction.response.send_message(view=await self._build_black_market_view(interaction.guild_id))

    @app_commands.command(name="blackmarketbuy", description="Vásárlás az aktuális Feketepiacról.")
    async def blackmarket_buy_slash(self, interaction: discord.Interaction, item: str, mennyiseg: app_commands.Range[int,1,20]=1) -> None:
        if interaction.guild_id is None:
            return
        try:
            await self.economy.require_access(interaction.guild_id, "economy", interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as error:
            return await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        state=self.black_markets.get(interaction.guild_id)
        if not state or state.expires_at<=datetime.now(timezone.utc):
            return await interaction.response.send_message("🌑 A Feketepiac jelenleg zárva van.", ephemeral=True)
        item_id=item.lower().strip()
        if item_id not in state.items:
            return await interaction.response.send_message("❌ Ez a tárgy nincs most a Feketepiacon.", ephemeral=True)
        price,stock=state.items[item_id]
        if mennyiseg>stock:
            return await interaction.response.send_message(f"❌ Már csak **{stock} db** van.", ephemeral=True)
        total=price*mennyiseg
        wallet,_=await self.db.get_balance(interaction.guild_id,interaction.user.id)
        if wallet<total:
            return await interaction.response.send_message("❌ Nincs elég pénzed.", ephemeral=True)
        await self.db.add_wallet(interaction.guild_id,interaction.user.id,-total,f"black_market:{item_id}x{mennyiseg}")
        await self.db.add_item(interaction.guild_id,interaction.user.id,item_id,mennyiseg)
        await self.bot.statistics.increment(interaction.guild_id, interaction.user.id, "market.black_market.purchases", mennyiseg)
        await self.bot.statistics.add(interaction.guild_id, interaction.user.id, "market.black_market.spent", total)
        await self.bot.statistics.increment(interaction.guild_id, interaction.user.id, f"market.black_market.item.{item_id}.bought", mennyiseg)
        state.items[item_id]=(price,stock-mennyiseg)
        info=await self.db.get_shop_item(item_id)
        await interaction.response.send_message(f"🌑 Megvettél **{mennyiseg}× {info[1]} {info[0]}** tárgyat **{money(total)}** összegért.")

    @app_commands.command(name="servereffects", description="Megmutatja az aktív szerver event-szorzókat.")
    async def servereffects_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        rows=await self.db.list_guild_effects(interaction.guild_id)
        labels={"work_multiplier":"🛠️ Work","crime_multiplier":"🚨 Crime","luck_multiplier":"🍀 Luck"}
        desc="\n".join(f"{labels.get(eid,eid)} • **x{mult:.2f}** • <t:{int(exp.timestamp())}:R>" for eid,mult,exp in rows) or "Nincs aktív szerver szorzó."
        await interaction.response.send_message(embed=base_embed("⚡ Aktív szerver eventek",desc))

    @commands.command(name="servereffects", aliases=["effects", "eff", "eventek"])
    @commands.guild_only()
    async def servereffects_prefix(self, ctx: commands.Context) -> None:
        rows=await self.db.list_guild_effects(ctx.guild.id)
        labels={"work_multiplier":"🛠️ Work","crime_multiplier":"🚨 Crime","luck_multiplier":"🍀 Luck"}
        desc="\n".join(f"{labels.get(eid,eid)} • **x{mult:.2f}** • <t:{int(exp.timestamp())}:R>" for eid,mult,exp in rows) or "Nincs aktív szerver szorzó."
        await ctx.send(embed=base_embed("⚡ Aktív szerver eventek",desc))

    @commands.group(name="blackmarket", aliases=["bm", "feketepiac"], invoke_without_command=True)
    @commands.guild_only()
    async def blackmarket_prefix(self, ctx: commands.Context) -> None:
        try:
            await self.economy.prepare_context(ctx.guild.id)
            await self.economy.guild_settings.require_feature(ctx.guild.id, "economy")
        except ValueError as error:
            return await ctx.send(f"❌ {error}")
        try:
            await self.economy.guild_settings.require_channel(
                ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None)
            )
        except ValueError:
            await handle_wrong_economy_channel(ctx, self.economy)
            return
        state = self.black_markets.get(ctx.guild.id)
        now = datetime.now(timezone.utc)
        if not state or state.expires_at <= now:
            return await ctx.send("🌑 A Feketepiac jelenleg zárva van.")
        await ctx.send(view=await self._build_black_market_view(ctx.guild.id))

    @blackmarket_prefix.command(name="buy", aliases=["b"])
    async def blackmarket_buy(self, ctx: commands.Context, item_id: str, quantity: int = 1) -> None:
        try:
            await self.economy.prepare_context(ctx.guild.id)
            await self.economy.guild_settings.require_feature(ctx.guild.id, "economy")
        except ValueError as error:
            return await ctx.send(f"❌ {error}")
        try:
            await self.economy.guild_settings.require_channel(
                ctx.guild.id, ctx.channel.id, getattr(ctx.channel, "category_id", None)
            )
        except ValueError:
            await handle_wrong_economy_channel(ctx, self.economy)
            return
        state = self.black_markets.get(ctx.guild.id)
        if not state or state.expires_at <= datetime.now(timezone.utc):
            return await ctx.send("🌑 A Feketepiac jelenleg zárva van.")
        if item_id not in state.items:
            return await ctx.send("❌ Ez a tárgy nincs most a Feketepiacon.")
        if quantity < 1:
            return await ctx.send("❌ A mennyiség legalább 1 legyen.")
        price, stock = state.items[item_id]
        if quantity > stock:
            return await ctx.send(f"❌ Már csak **{stock} db** van készleten.")
        total = price * quantity
        wallet, _ = await self.db.get_balance(ctx.guild.id, ctx.author.id)
        if wallet < total:
            return await ctx.send("❌ Nincs elég pénzed.")
        await self.db.add_wallet(ctx.guild.id, ctx.author.id, -total, f"black_market:{item_id}x{quantity}")
        await self.db.add_item(ctx.guild.id, ctx.author.id, item_id, quantity)
        await self.bot.statistics.increment(ctx.guild.id, ctx.author.id, "market.black_market.purchases", quantity)
        await self.bot.statistics.add(ctx.guild.id, ctx.author.id, "market.black_market.spent", total)
        await self.bot.statistics.increment(ctx.guild.id, ctx.author.id, f"market.black_market.item.{item_id}.bought", quantity)
        state.items[item_id] = (price, stock - quantity)
        item = await self.db.get_shop_item(item_id)
        await ctx.send(f"🌑 Megvettél **{quantity}× {item[1]} {item[0]}** tárgyat **{money(total)}** összegért.")

    @commands.command(name="openblackmarket", aliases=["openbm"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def open_blackmarket_admin(self, ctx: commands.Context) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        await self._open_black_market(ctx.channel)
        await ctx.message.add_reaction("✅")

    # -------------------- v3.8 Community Management --------------------

    async def _restore_community_runtime(self) -> None:
        """Restore persistent buttons and restart-safe timers after a bot restart."""
        suggestions = await self.db.list_active_community_suggestions(communitycfg.MAX_RESTORED_SUGGESTIONS)
        for row in suggestions:
            if row.get("message_id"):
                try:
                    self.bot.add_view(SuggestionView.from_row(self, row), message_id=row["message_id"])
                except Exception:
                    LOGGER.exception("Suggestion view restore failed: %s", row.get("suggestion_id"))

        polls = await self.db.list_active_community_polls(communitycfg.MAX_RESTORED_POLLS)
        for row in polls:
            if row.get("message_id"):
                try:
                    self.bot.add_view(PollView.from_row(self, row), message_id=row["message_id"])
                except Exception:
                    LOGGER.exception("Poll view restore failed: %s", row.get("poll_id"))
            self._schedule_poll(row["poll_id"])

        giveaways = await self.db.list_active_community_giveaways(communitycfg.MAX_RESTORED_GIVEAWAYS)
        for row in giveaways:
            if row.get("message_id"):
                try:
                    self.bot.add_view(
                        GiveawayView(self, row["giveaway_id"], len(row.get("entries", []))),
                        message_id=row["message_id"],
                    )
                except Exception:
                    LOGGER.exception("Giveaway view restore failed: %s", row.get("giveaway_id"))
            self._schedule_giveaway(row["giveaway_id"])

    def _suggestion_embed(self, row: dict) -> discord.Embed:
        status = row.get("status", "pending")
        labels = {
            "pending": ("📝 Javaslat", GOLD),
            "approved": ("✅ Elfogadott javaslat", SUCCESS),
            "denied": ("❌ Elutasított javaslat", discord.Color.red()),
        }
        title, color = labels.get(status, ("📝 Javaslat", GOLD))
        embed = base_embed(f"{title} #{row['suggestion_id']}", row["content"], color)
        embed.add_field(name="👍 Támogatás", value=str(row.get("upvotes", 0)), inline=True)
        embed.add_field(name="👎 Ellene", value=str(row.get("downvotes", 0)), inline=True)
        if status == "pending":
            author_value = "Névtelen" if row.get("anonymous") else f"<@{row['author_id']}>"
            embed.add_field(name="👤 Beküldte", value=author_value, inline=True)
        else:
            embed.add_field(name="🛡️ Lezárta", value=f"<@{row.get('staff_id')}>" if row.get("staff_id") else "Staff", inline=True)
        if row.get("staff_note"):
            embed.add_field(name="📝 Staff megjegyzés", value=row["staff_note"][:1000], inline=False)
        embed.set_footer(text="Yoru • Suggestions • A saját szavazat újrakattintással visszavonható")
        return embed

    async def _create_suggestion(self, guild: discord.Guild | None, user: discord.abc.User, content: str) -> discord.Message:
        if guild is None:
            raise ValueError("Ez csak szerveren használható.")
        if not await self.settings_service.get_suggestions_enabled(guild.id):
            raise ValueError("A javaslat rendszer ezen a szerveren ki van kapcsolva.")
        channel_id = await self.settings_service.get_suggestion_channel_id(guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Nincs érvényes Suggestion csatorna beállítva a `/settings` alatt.")
        clean = content.strip()
        if len(clean) < 3:
            raise ValueError("A javaslat túl rövid.")
        clean = clean[: communitycfg.SUGGESTIONS_MAX_LENGTH]
        anonymous = await self.settings_service.get_suggestions_anonymous(guild.id)
        suggestion_id = await self.db.create_community_suggestion(guild.id, channel.id, user.id, clean, anonymous)
        row = await self.db.get_community_suggestion(suggestion_id)
        embed = self._suggestion_embed(row)
        view = SuggestionView.from_row(self, row)
        message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        await self.db.set_community_suggestion_message(suggestion_id, message.id)
        self.bot.add_view(view, message_id=message.id)
        return message

    def _poll_embed(self, row: dict) -> discord.Embed:
        counts = row.get("counts", {})
        total = sum(int(v) for v in counts.values())
        lines = []
        numbers = PollVoteButton.NUMBERS
        for index, option in enumerate(row["options"]):
            count = int(counts.get(index, 0))
            percent = (count / total * 100) if total else 0.0
            lines.append(f"{numbers[index]} **{option}** — `{count}` • `{percent:.0f}%`")
        closes_at = datetime.fromisoformat(row["closes_at"])
        state = "🔒 Lezárva" if row.get("closed") else f"⏳ Zárás: <t:{int(closes_at.timestamp())}:R>"
        embed = base_embed(f"📊 Szavazás #{row['poll_id']} • {row['question']}", "\n".join(lines), GOLD)
        embed.add_field(name="👥 Szavazatok", value=str(total), inline=True)
        embed.add_field(name="Állapot", value=state, inline=True)
        embed.add_field(name="👤 Indította", value=f"<@{row['author_id']}>", inline=True)
        embed.set_footer(text="Yoru • Poll • Egy embernek egy aktív szavazata lehet")
        return embed

    async def _create_poll(
        self,
        guild: discord.Guild,
        channel: discord.abc.Messageable,
        user: discord.abc.User,
        question: str,
        options: list[str],
        minutes: int,
    ) -> discord.Message:
        if not await self.settings_service.get_polls_enabled(guild.id):
            raise ValueError("A Poll rendszer ezen a szerveren ki van kapcsolva.")
        if await self.settings_service.get_polls_staff_only(guild.id):
            if not isinstance(user, discord.Member) or not user.guild_permissions.manage_messages:
                raise ValueError("Ezen a szerveren csak staff indíthat szavazást.")
        clean_options = []
        for option in options:
            value = option.strip()[:100]
            if value and value.casefold() not in {x.casefold() for x in clean_options}:
                clean_options.append(value)
        if len(clean_options) < 2 or len(clean_options) > communitycfg.POLLS_MAX_OPTIONS:
            raise ValueError(f"2–{communitycfg.POLLS_MAX_OPTIONS} különböző opció szükséges.")
        question = question.strip()[:256]
        closes_at = _utcnow() + timedelta(minutes=minutes)
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            raise ValueError("Érvénytelen csatorna.")
        poll_id = await self.db.create_community_poll(guild.id, int(channel_id), user.id, question, clean_options, closes_at)
        row = await self.db.get_community_poll(poll_id)
        view = PollView.from_row(self, row)
        message = await channel.send(embed=self._poll_embed(row), view=view, allowed_mentions=discord.AllowedMentions.none())
        await self.db.set_community_poll_message(poll_id, message.id)
        self.bot.add_view(view, message_id=message.id)
        self._schedule_poll(poll_id)
        return message

    def _schedule_poll(self, poll_id: int) -> None:
        old = self.poll_tasks.get(poll_id)
        if old and not old.done():
            return
        self.poll_tasks[poll_id] = asyncio.create_task(self._poll_timer(poll_id))

    async def _poll_timer(self, poll_id: int) -> None:
        try:
            await self.bot.wait_until_ready()
            row = await self.db.get_community_poll(poll_id)
            if row is None or row["closed"]:
                return
            delay = max(0.0, (datetime.fromisoformat(row["closes_at"]) - _utcnow()).total_seconds())
            await asyncio.sleep(delay)
            await self._finish_poll(poll_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Poll timer failed: %s", poll_id)
        finally:
            self.poll_tasks.pop(poll_id, None)

    async def _finish_poll(self, poll_id: int) -> None:
        row = await self.db.get_community_poll(poll_id)
        if row is None or row["closed"]:
            return
        await self.db.close_community_poll(poll_id)
        row = await self.db.get_community_poll(poll_id)
        channel = self.bot.get_channel(row["channel_id"])
        if not isinstance(channel, discord.TextChannel) or not row.get("message_id"):
            return
        try:
            message = await channel.fetch_message(row["message_id"])
            await message.edit(embed=self._poll_embed(row), view=PollView.from_row(self, row, disabled=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    def _giveaway_embed(self, row: dict, winners: list[int] | None = None) -> discord.Embed:
        count = len(row.get("entries", []))
        ends_at = datetime.fromisoformat(row["ends_at"])
        if row.get("ended"):
            if winners:
                result = ", ".join(f"<@{uid}>" for uid in winners)
            else:
                result = "Nem volt érvényes jelentkező."
            description = f"🎁 **{row['prize']}**\n\n🏆 Nyertes(ek): {result}"
            title = f"🎉 Giveaway #{row['giveaway_id']} • Lezárva"
            color = SUCCESS
        else:
            description = (
                f"🎁 **{row['prize']}**\n\n"
                f"⏳ Vége: <t:{int(ends_at.timestamp())}:R>\n"
                f"🏆 Nyertesek: **{row['winner_count']} fő**\n"
                f"👥 Jelentkezők: **{count} fő**"
            )
            title = f"🎉 Giveaway #{row['giveaway_id']}"
            color = GOLD
        embed = base_embed(title, description, color)
        embed.add_field(name="👤 Host", value=f"<@{row['host_id']}>", inline=True)
        embed.set_footer(text="Yoru • Giveaway • A gomb újrakattintásával visszavonhatod a jelentkezést")
        return embed

    async def _create_giveaway(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        user: discord.abc.User,
        prize: str,
        minutes: int,
        winner_count: int,
    ) -> discord.Message:
        if not await self.settings_service.get_giveaways_enabled(guild.id):
            raise ValueError("A Giveaway rendszer ezen a szerveren ki van kapcsolva.")
        prize = prize.strip()[:500]
        if not prize:
            raise ValueError("Adj meg nyereményt.")
        ends_at = _utcnow() + timedelta(minutes=minutes)
        giveaway_id = await self.db.create_community_giveaway(
            guild.id, channel.id, user.id, prize, winner_count, ends_at
        )
        row = await self.db.get_community_giveaway(giveaway_id)
        view = GiveawayView(self, giveaway_id, 0)
        message = await channel.send(embed=self._giveaway_embed(row), view=view, allowed_mentions=discord.AllowedMentions.none())
        await self.db.set_community_giveaway_message(giveaway_id, message.id)
        self.bot.add_view(view, message_id=message.id)
        self._schedule_giveaway(giveaway_id)
        return message

    def _schedule_giveaway(self, giveaway_id: int) -> None:
        old = self.giveaway_tasks.get(giveaway_id)
        if old and not old.done():
            return
        self.giveaway_tasks[giveaway_id] = asyncio.create_task(self._giveaway_timer(giveaway_id))

    async def _giveaway_timer(self, giveaway_id: int) -> None:
        try:
            await self.bot.wait_until_ready()
            row = await self.db.get_community_giveaway(giveaway_id)
            if row is None or row["ended"]:
                return
            delay = max(0.0, (datetime.fromisoformat(row["ends_at"]) - _utcnow()).total_seconds())
            await asyncio.sleep(delay)
            await self._finish_giveaway(giveaway_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Giveaway timer failed: %s", giveaway_id)
        finally:
            self.giveaway_tasks.pop(giveaway_id, None)

    async def _finish_giveaway(self, giveaway_id: int) -> list[int]:
        row = await self.db.get_community_giveaway(giveaway_id)
        if row is None:
            return []
        if row["ended"]:
            return []
        entries = list(dict.fromkeys(int(uid) for uid in row.get("entries", [])))
        winner_count = min(row["winner_count"], len(entries))
        winners = random.sample(entries, k=winner_count) if winner_count > 0 else []
        await self.db.end_community_giveaway(giveaway_id)
        row = await self.db.get_community_giveaway(giveaway_id)
        channel = self.bot.get_channel(row["channel_id"])
        if isinstance(channel, discord.TextChannel):
            if row.get("message_id"):
                try:
                    message = await channel.fetch_message(row["message_id"])
                    await message.edit(
                        embed=self._giveaway_embed(row, winners),
                        view=GiveawayView(self, giveaway_id, len(entries), disabled=True),
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            if winners:
                await channel.send(
                    f"🎉 Giveaway **#{giveaway_id}** nyertesei: " + ", ".join(f"<@{uid}>" for uid in winners),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            else:
                await channel.send(f"🎉 Giveaway **#{giveaway_id}** lezárult, de nem volt jelentkező.")
        return winners

    async def _reroll_giveaway(self, guild_id: int, giveaway_id: int) -> list[int]:
        row = await self.db.get_community_giveaway(giveaway_id)
        if row is None or row["guild_id"] != guild_id:
            raise ValueError("Nincs ilyen giveaway ezen a szerveren.")
        if not row["ended"]:
            raise ValueError("Csak lezárt giveawayt lehet újrasorsolni.")
        entries = list(dict.fromkeys(int(uid) for uid in row.get("entries", [])))
        if not entries:
            raise ValueError("Nem volt jelentkező.")
        return random.sample(entries, k=min(row["winner_count"], len(entries)))

    def _starboard_embed(self, message: discord.Message, star_count: int) -> discord.Embed:
        content = message.content.strip() or "*(nincs szöveges tartalom)*"
        embed = base_embed("⭐ Starboard", content[:3500], GOLD)
        embed.add_field(name="⭐ Csillag", value=str(star_count), inline=True)
        embed.add_field(name="📍 Forrás", value=f"{message.channel.mention} • [Ugrás az üzenetre]({message.jump_url})", inline=False)
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        attachments = []
        for attachment in message.attachments:
            content_type = (attachment.content_type or "").lower()
            if content_type.startswith("image/"):
                embed.set_image(url=attachment.url)
                break
            attachments.append(f"[{attachment.filename}]({attachment.url})")
        if attachments:
            embed.add_field(name="📎 Fájlok", value="\n".join(attachments[:5]), inline=False)
        embed.set_footer(text=f"Yoru • Starboard • Message ID: {message.id}")
        return embed

    async def _sync_starboard(self, guild_id: int, channel_id: int, message_id: int) -> None:
        if not await self.settings_service.get_starboard_enabled(guild_id):
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        starboard_id = await self.settings_service.get_starboard_channel_id(guild_id)
        starboard = guild.get_channel(starboard_id) if starboard_id else None
        source = guild.get_channel(channel_id)
        if not isinstance(starboard, discord.TextChannel) or not isinstance(source, discord.TextChannel):
            return
        if source.id == starboard.id:
            return
        try:
            message = await source.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        star_reaction = next((r for r in message.reactions if str(r.emoji) == communitycfg.STARBOARD_EMOJI), None)
        star_count = 0
        if star_reaction is not None:
            try:
                async for user in star_reaction.users(limit=None):
                    if not user.bot:
                        star_count += 1
            except (discord.Forbidden, discord.HTTPException):
                star_count = max(0, int(star_reaction.count))
        threshold = await self.settings_service.get_starboard_threshold(guild_id)
        existing = await self.db.get_community_starboard_post(guild_id, message_id)
        if star_count < threshold:
            if existing:
                try:
                    posted = await starboard.fetch_message(existing["starboard_message_id"])
                    suppress = getattr(self.bot, "_suppressed_delete_log_ids", None)
                    if isinstance(suppress, set):
                        suppress.add(posted.id)
                    await posted.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                await self.db.delete_community_starboard_post(guild_id, message_id)
            return
        content = f"⭐ **{star_count}** • {source.mention}"
        embed = self._starboard_embed(message, star_count)
        if existing:
            try:
                posted = await starboard.fetch_message(existing["starboard_message_id"])
                await posted.edit(content=content, embed=embed)
                await self.db.upsert_community_starboard_post(guild_id, message_id, channel_id, posted.id, star_count)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await self.db.delete_community_starboard_post(guild_id, message_id)
        posted = await starboard.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await self.db.upsert_community_starboard_post(guild_id, message_id, channel_id, posted.id, star_count)

    async def _post_sticky(self, guild: discord.Guild, channel: discord.TextChannel, sticky: dict) -> discord.Message | None:
        key = (guild.id, channel.id)
        if key in self._sticky_locks:
            return None
        self._sticky_locks.add(key)
        try:
            old_id = sticky.get("last_message_id")
            if old_id:
                try:
                    old = await channel.fetch_message(old_id)
                    suppress = getattr(self.bot, "_suppressed_delete_log_ids", None)
                    if isinstance(suppress, set):
                        suppress.add(old.id)
                    await old.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            embed = base_embed("📌 Sticky", sticky["content"], GOLD)
            embed.set_footer(text="Yoru • Sticky • Ezt az üzenetet a bot automatikusan lent tartja")
            message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            await self.db.update_community_sticky_runtime(
                guild.id,
                channel.id,
                last_message_id=message.id,
                message_counter=0,
                last_posted_at=_utcnow().isoformat(),
            )
            return message
        finally:
            self._sticky_locks.discard(key)

    @commands.Cog.listener("on_raw_reaction_add")
    async def community_star_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or str(payload.emoji) != communitycfg.STARBOARD_EMOJI:
            return
        await self._sync_starboard(payload.guild_id, payload.channel_id, payload.message_id)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def community_star_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or str(payload.emoji) != communitycfg.STARBOARD_EMOJI:
            return
        await self._sync_starboard(payload.guild_id, payload.channel_id, payload.message_id)

    @commands.Cog.listener("on_raw_message_delete")
    async def community_source_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id is None:
            return
        existing = await self.db.get_community_starboard_post(payload.guild_id, payload.message_id)
        if not existing:
            return
        guild = self.bot.get_guild(payload.guild_id)
        starboard_id = await self.settings_service.get_starboard_channel_id(payload.guild_id)
        channel = guild.get_channel(starboard_id) if guild and starboard_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                posted = await channel.fetch_message(existing["starboard_message_id"])
                suppress = getattr(self.bot, "_suppressed_delete_log_ids", None)
                if isinstance(suppress, set):
                    suppress.add(posted.id)
                await posted.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.db.delete_community_starboard_post(payload.guild_id, payload.message_id)

    @commands.Cog.listener("on_message")
    async def community_message_listener(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        guild = message.guild

        if await self.settings_service.get_afk_enabled(guild.id):
            # The !afk message itself must not instantly clear the AFK state it creates.
            is_afk_command = message.content.strip().lower().startswith(("!afk", "!away"))
            if not is_afk_command:
                cleared = await self.db.clear_community_afk(guild.id, message.author.id)
                if cleared:
                    try:
                        await message.channel.send(
                            f"👋 {message.author.mention}, AFK állapotod törölve. Üdv újra!",
                            delete_after=8,
                            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                        )
                    except discord.HTTPException:
                        pass

            now = asyncio.get_running_loop().time()
            notices = []
            for member in dict.fromkeys(message.mentions):
                if member.id == message.author.id:
                    continue
                afk = await self.db.get_community_afk(guild.id, member.id)
                if not afk:
                    continue
                key = (guild.id, message.channel.id, member.id)
                if now - self._afk_notice_times.get(key, 0.0) < communitycfg.AFK_MENTION_NOTICE_COOLDOWN_SECONDS:
                    continue
                self._afk_notice_times[key] = now
                if len(self._afk_notice_times) >= 2000:
                    cutoff = now - max(300.0, float(communitycfg.AFK_MENTION_NOTICE_COOLDOWN_SECONDS) * 4.0)
                    self._afk_notice_times = {k: stamp for k, stamp in self._afk_notice_times.items() if stamp >= cutoff}
                since = datetime.fromisoformat(afk["since"])
                notices.append(f"💤 **{member.display_name}** AFK: {afk['reason']} • <t:{int(since.timestamp())}:R>")
            if notices:
                try:
                    await message.channel.send("\n".join(notices[:3]), delete_after=15, allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass

        if await self.settings_service.get_sticky_enabled(guild.id) and isinstance(message.channel, discord.TextChannel):
            sticky = await self.db.get_community_sticky(guild.id, message.channel.id)
            if sticky and sticky.get("active"):
                count = int(sticky.get("message_counter", 0)) + 1
                threshold = await self.settings_service.get_sticky_every_messages(guild.id)
                await self.db.update_community_sticky_runtime(guild.id, message.channel.id, message_counter=count)
                if count >= threshold:
                    last_posted = sticky.get("last_posted_at")
                    if last_posted:
                        elapsed = (_utcnow() - datetime.fromisoformat(last_posted)).total_seconds()
                        if elapsed < communitycfg.STICKY_REPOST_COOLDOWN_SECONDS:
                            return
                    sticky["message_counter"] = count
                    await self._post_sticky(guild, message.channel, sticky)

    @app_commands.command(name="suggest", description="Javaslat küldése a szerver suggestion csatornájába.")
    async def suggest_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez csak szerveren használható.", ephemeral=True)
        if not await self.settings_service.get_suggestions_enabled(interaction.guild.id):
            return await interaction.response.send_message("❌ A javaslat rendszer ki van kapcsolva.", ephemeral=True)
        await interaction.response.send_modal(SuggestionModal(self))

    @commands.command(name="suggest", aliases=["suggestion", "javaslat"])
    @commands.guild_only()
    async def suggest_prefix(self, ctx: commands.Context, *, text: str) -> None:
        try:
            message = await self._create_suggestion(ctx.guild, ctx.author, text)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.send(f"✅ Javaslat elküldve: {message.jump_url}", delete_after=10)

    @app_commands.command(name="poll", description="Interaktív szavazás létrehozása.")
    async def poll_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Ez csak szerveren használható.", ephemeral=True)
        if not await self.settings_service.get_polls_enabled(interaction.guild.id):
            return await interaction.response.send_message("❌ A Poll rendszer ki van kapcsolva.", ephemeral=True)
        if await self.settings_service.get_polls_staff_only(interaction.guild.id):
            if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_messages:
                return await interaction.response.send_message("❌ Ezen a szerveren csak staff indíthat szavazást.", ephemeral=True)
        await interaction.response.send_modal(PollModal(self))

    @commands.command(name="poll", aliases=["szavazas", "votecreate"])
    @commands.guild_only()
    async def poll_prefix(self, ctx: commands.Context, *, raw: str) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.send("❌ Ezt normál szöveges szervercsatornában használd.")
        parts = [part.strip() for part in raw.split("|") if part.strip()]
        if len(parts) < 3:
            return await ctx.send("❌ Használat: `!poll Kérdés | Opció 1 | Opció 2 | ...`")
        minutes = await self.settings_service.get_poll_default_duration_minutes(ctx.guild.id)
        try:
            await self._create_poll(ctx.guild, ctx.channel, ctx.author, parts[0], parts[1:], minutes)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.message.add_reaction("✅")

    @app_commands.command(name="giveaway", description="Interaktív giveaway létrehozása.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def giveaway_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.send_modal(GiveawayModal(self))

    @commands.command(name="giveaway", aliases=["gw"])
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def giveaway_prefix(self, ctx: commands.Context, duration: str, winners: int, *, prize: str) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        try:
            minutes = _parse_duration_minutes(
                duration,
                minimum=communitycfg.GIVEAWAYS_MIN_DURATION_MINUTES,
                maximum=communitycfg.GIVEAWAYS_MAX_DURATION_MINUTES,
            )
            if winners < 1 or winners > communitycfg.GIVEAWAYS_MAX_WINNERS:
                raise ValueError(f"A nyertesek száma 1–{communitycfg.GIVEAWAYS_MAX_WINNERS} lehet.")
            await self._create_giveaway(ctx.guild, ctx.channel, ctx.author, prize, minutes, winners)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.message.add_reaction("✅")

    @app_commands.command(name="reroll", description="Lezárt giveaway újrasorsolása.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def giveaway_reroll_slash(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        try:
            winners = await self._reroll_giveaway(interaction.guild_id, giveaway_id)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        await interaction.response.send_message(
            f"🎲 Újrasorsolás **#{giveaway_id}**: " + ", ".join(f"<@{uid}>" for uid in winners),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @commands.command(name="giveawayreroll", aliases=["gwreroll", "reroll"])
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def giveaway_reroll_prefix(self, ctx: commands.Context, giveaway_id: int) -> None:
        try:
            winners = await self._reroll_giveaway(ctx.guild.id, giveaway_id)
        except ValueError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.send(
            f"🎲 Újrasorsolás **#{giveaway_id}**: " + ", ".join(f"<@{uid}>" for uid in winners),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @app_commands.command(name="afk", description="AFK állapot beállítása.")
    @app_commands.describe(reason="Miért vagy távol?")
    async def afk_slash(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        if interaction.guild_id is None:
            return
        if not await self.settings_service.get_afk_enabled(interaction.guild_id):
            return await interaction.response.send_message("❌ Az AFK rendszer ki van kapcsolva.", ephemeral=True)
        clean = reason.strip()[: communitycfg.AFK_MAX_REASON_LENGTH] or "AFK"
        await self.db.set_community_afk(interaction.guild_id, interaction.user.id, clean)
        await interaction.response.send_message(f"💤 AFK beállítva: **{clean}**", ephemeral=True)

    @commands.command(name="afk", aliases=["away"])
    @commands.guild_only()
    async def afk_prefix(self, ctx: commands.Context, *, reason: str = "AFK") -> None:
        if not await self.settings_service.get_afk_enabled(ctx.guild.id):
            return await ctx.send("❌ Az AFK rendszer ki van kapcsolva.")
        clean = reason.strip()[: communitycfg.AFK_MAX_REASON_LENGTH] or "AFK"
        await self.db.set_community_afk(ctx.guild.id, ctx.author.id, clean)
        await ctx.send(f"💤 {ctx.author.mention} AFK: **{clean}**", allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    @app_commands.command(name="sticky", description="Sticky üzenet beállítása az aktuális csatornában.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def sticky_slash(self, interaction: discord.Interaction, content: str) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        if not await self.settings_service.get_sticky_enabled(interaction.guild.id):
            return await interaction.response.send_message("❌ A Sticky rendszer ki van kapcsolva.", ephemeral=True)
        clean = content.strip()[: communitycfg.STICKY_MAX_LENGTH]
        if not clean:
            return await interaction.response.send_message("❌ Adj meg szöveget.", ephemeral=True)
        await self.db.set_community_sticky(interaction.guild.id, interaction.channel.id, clean, interaction.user.id)
        sticky = await self.db.get_community_sticky(interaction.guild.id, interaction.channel.id)
        await self._post_sticky(interaction.guild, interaction.channel, sticky)
        await interaction.response.send_message("✅ Sticky beállítva.", ephemeral=True)

    @commands.command(name="sticky")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def sticky_prefix(self, ctx: commands.Context, *, content: str) -> None:
        if not isinstance(ctx.channel, discord.TextChannel):
            return
        if not await self.settings_service.get_sticky_enabled(ctx.guild.id):
            return await ctx.send("❌ A Sticky rendszer ki van kapcsolva.")
        clean = content.strip()[: communitycfg.STICKY_MAX_LENGTH]
        if not clean:
            return
        await self.db.set_community_sticky(ctx.guild.id, ctx.channel.id, clean, ctx.author.id)
        sticky = await self.db.get_community_sticky(ctx.guild.id, ctx.channel.id)
        await self._post_sticky(ctx.guild, ctx.channel, sticky)
        await ctx.message.add_reaction("✅")

    @app_commands.command(name="stickyoff", description="Sticky törlése az aktuális csatornából.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def stickyoff_slash(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            return
        sticky = await self.db.get_community_sticky(interaction.guild_id, interaction.channel_id)
        removed = await self.db.remove_community_sticky(interaction.guild_id, interaction.channel_id)
        if removed and sticky and sticky.get("last_message_id") and isinstance(interaction.channel, discord.TextChannel):
            try:
                old = await interaction.channel.fetch_message(sticky["last_message_id"])
                suppress = getattr(self.bot, "_suppressed_delete_log_ids", None)
                if isinstance(suppress, set):
                    suppress.add(old.id)
                await old.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await interaction.response.send_message("✅ Sticky törölve." if removed else "ℹ️ Nincs sticky ebben a csatornában.", ephemeral=True)

    @commands.command(name="stickyoff", aliases=["unsticky"])
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def stickyoff_prefix(self, ctx: commands.Context) -> None:
        sticky = await self.db.get_community_sticky(ctx.guild.id, ctx.channel.id)
        removed = await self.db.remove_community_sticky(ctx.guild.id, ctx.channel.id)
        if removed and sticky and sticky.get("last_message_id") and isinstance(ctx.channel, discord.TextChannel):
            try:
                old = await ctx.channel.fetch_message(sticky["last_message_id"])
                suppress = getattr(self.bot, "_suppressed_delete_log_ids", None)
                if isinstance(suppress, set):
                    suppress.add(old.id)
                await old.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await ctx.message.add_reaction("✅" if removed else "ℹ️")


    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "⛔ Ehhez **Üzenetek kezelése** jogosultság kell."
        else:
            raise error
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
