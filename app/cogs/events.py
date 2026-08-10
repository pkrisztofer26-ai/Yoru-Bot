from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from app import economy_config as eco
from app.services.economy import EconomyService
from app.ui import DANGER, GOLD, SUCCESS, base_embed, money

logger = logging.getLogger("vaultbot.events")


@dataclass
class ActiveEvent:
    kind: str
    message_id: int


class EventCog(commands.Cog):
    SAFE_EMOJI = "💰"
    BOMB_EMOJI = "💣"

    def __init__(self, bot: commands.Bot, economy: EconomyService) -> None:
        self.bot = bot
        self.economy = economy
        self.active_events: dict[int, ActiveEvent] = {}
        self.auto_task: asyncio.Task[None] | None = None
        self._activity_messages: dict[int, deque[tuple[float, int]]] = {}
        self._activity_last_user_message: dict[tuple[int, int], float] = {}
        self._activity_ready: dict[int, asyncio.Event] = {}

    async def cog_load(self) -> None:
        settings = self.bot.settings  # type: ignore[attr-defined]
        if settings.auto_events_enabled and settings.event_channel_id:
            self.auto_task = asyncio.create_task(self._automatic_event_loop())

    async def cog_unload(self) -> None:
        if self.auto_task:
            self.auto_task.cancel()

    def _activity_gate(self, guild_id: int) -> asyncio.Event:
        gate = self._activity_ready.get(guild_id)
        if gate is None:
            gate = asyncio.Event()
            self._activity_ready[guild_id] = gate
        return gate

    def _prune_activity(self, guild_id: int, now: float | None = None) -> None:
        settings = self.bot.settings  # type: ignore[attr-defined]
        now = time.monotonic() if now is None else now
        cutoff = now - (settings.auto_event_activity_window_minutes * 60)
        messages = self._activity_messages.setdefault(guild_id, deque())
        while messages and messages[0][0] < cutoff:
            messages.popleft()
        for key, last_seen in list(self._activity_last_user_message.items()):
            if key[0] == guild_id and last_seen < cutoff:
                self._activity_last_user_message.pop(key, None)

    def get_activity_status(self, guild_id: int) -> dict[str, int | bool]:
        self._prune_activity(guild_id)
        messages = self._activity_messages.setdefault(guild_id, deque())
        users = {user_id for _, user_id in messages}
        gate = self._activity_gate(guild_id)
        settings = self.bot.settings  # type: ignore[attr-defined]
        qualifies = (
            len(messages) >= settings.auto_event_activity_messages
            and len(users) >= settings.auto_event_activity_min_users
        )
        # Az activity gate csak addig marad aktív, amíg a rolling ablak alapján
        # tényleg él a chat. Így egy esti aktivitás nem indít eventet órákkal később.
        if qualifies:
            gate.set()
        else:
            gate.clear()
        return {
            "messages": len(messages),
            "required_messages": settings.auto_event_activity_messages,
            "users": len(users),
            "required_users": settings.auto_event_activity_min_users,
            "window_minutes": settings.auto_event_activity_window_minutes,
            "user_cooldown_seconds": settings.auto_event_activity_user_cooldown_seconds,
            "armed": qualifies,
        }

    def _reset_activity(self, guild_id: int) -> None:
        self._activity_messages.pop(guild_id, None)
        for key in [key for key in self._activity_last_user_message if key[0] == guild_id]:
            self._activity_last_user_message.pop(key, None)
        gate = self._activity_ready.get(guild_id)
        if gate is not None:
            gate.clear()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        settings = self.bot.settings  # type: ignore[attr-defined]
        if (
            not settings.auto_events_enabled
            or not settings.event_channel_id
            or message.guild is None
            or message.channel.id != settings.event_channel_id
            or message.author.bot
            or message.webhook_id is not None
        ):
            return

        guild_id = message.guild.id
        gate = self._activity_gate(guild_id)
        now = time.monotonic()
        self._prune_activity(guild_id, now)
        cooldown = settings.auto_event_activity_user_cooldown_seconds
        user_key = (guild_id, message.author.id)
        last = self._activity_last_user_message.get(user_key)
        if last is not None and now - last < cooldown:
            return

        self._activity_last_user_message[user_key] = now
        messages = self._activity_messages.setdefault(guild_id, deque())
        messages.append((now, message.author.id))
        users = {user_id for _, user_id in messages}

        qualifies = (
            len(messages) >= settings.auto_event_activity_messages
            and len(users) >= settings.auto_event_activity_min_users
        )
        was_armed = gate.is_set()
        if qualifies:
            gate.set()
            if not was_armed:
                logger.info(
                    "Auto event aktivitás teljesült guild=%s: %s üzenet, %s user.",
                    guild_id,
                    len(messages),
                    len(users),
                )
        else:
            gate.clear()

    async def _get_participants(self, message: discord.Message, emoji: str) -> list[discord.User | discord.Member]:
        refreshed = await message.channel.fetch_message(message.id)
        for reaction in refreshed.reactions:
            if str(reaction.emoji) == emoji:
                users = [user async for user in reaction.users()]
                return [user for user in users if not user.bot]
        return []

    async def _reserve_event(self, guild_id: int, kind: str, message_id: int) -> bool:
        if guild_id in self.active_events:
            return False
        self.active_events[guild_id] = ActiveEvent(kind=kind, message_id=message_id)
        return True

    def _release_event(self, guild_id: int) -> None:
        self.active_events.pop(guild_id, None)

    @app_commands.command(name="kincseslada", description="Admin Kincses Láda eventet indít, amely egyenlően szétosztja a jutalmat.")
    @app_commands.describe(osszeg="A teljes kiosztandó pénzösszeg", jelentkezes="Hány másodpercig lehessen csatlakozni?")
    @app_commands.checks.has_permissions(administrator=True)
    async def kincseslada(
        self,
        interaction: discord.Interaction,
        osszeg: app_commands.Range[int, eco.EVENT_MIN_REWARD],
        jelentkezes: app_commands.Range[int, eco.EVENT_JOIN_MIN_SECONDS, eco.EVENT_JOIN_MAX_SECONDS] = eco.AUTO_EVENT_JOIN_SECONDS,
    ) -> None:
        if interaction.guild_id is None or interaction.channel is None:
            return await interaction.response.send_message("Ez a parancs csak szerveren használható.", ephemeral=True)
        if interaction.guild_id in self.active_events:
            return await interaction.response.send_message("❌ Már fut egy event ezen a szerveren.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        message = await self._post_safe(interaction.channel, interaction.guild_id, osszeg, jelentkezes, interaction.user, False)
        if message is None:
            return await interaction.followup.send("❌ Nem sikerült elindítani az eventet.", ephemeral=True)
        await interaction.followup.send(f"✅ A Kincses Láda elindult: {message.jump_url}", ephemeral=True)

    @kincseslada.error
    async def kincseslada_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("❌ Ezt csak admin indíthatja.", ephemeral=True)
        raise error

    @app_commands.command(name="hirtelenhalal", description="Admin Hirtelen Halál eventet indít belépési díjjal.")
    @app_commands.describe(
        belepo="Belépési díj játékosonként; a teljes pot ebből áll össze",
        jelentkezes="Hány másodpercig lehessen csatlakozni?",
        kor="Hány másodpercenként essen ki valaki?",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def hirtelenhalal(
        self,
        interaction: discord.Interaction,
        belepo: app_commands.Range[int, eco.BOMB_MIN_ENTRY],
        jelentkezes: app_commands.Range[int, eco.EVENT_JOIN_MIN_SECONDS, eco.EVENT_JOIN_MAX_SECONDS] = eco.AUTO_EVENT_JOIN_SECONDS,
        kor: app_commands.Range[int, eco.BOMB_ROUND_MIN_SECONDS, eco.BOMB_ROUND_MAX_SECONDS] = eco.AUTO_BOMB_ROUND_SECONDS,
    ) -> None:
        if interaction.guild_id is None or interaction.channel is None:
            return await interaction.response.send_message("Ez a parancs csak szerveren használható.", ephemeral=True)
        if interaction.guild_id in self.active_events:
            return await interaction.response.send_message("❌ Már fut egy event ezen a szerveren.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        message = await self._post_bomb(interaction.channel, interaction.guild_id, belepo, jelentkezes, kor, interaction.user, False)
        if message is None:
            return await interaction.followup.send("❌ Nem sikerült elindítani az eventet.", ephemeral=True)
        await interaction.followup.send(f"✅ A Hirtelen Halál elindult: {message.jump_url}", ephemeral=True)

    @hirtelenhalal.error
    async def hirtelenhalal_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("❌ Ezt csak admin indíthatja.", ephemeral=True)
        raise error

    async def _post_safe(
        self,
        channel: discord.abc.Messageable,
        guild_id: int,
        amount: int,
        join_seconds: int,
        starter: discord.abc.User | None,
        automatic: bool,
    ) -> discord.Message | None:
        end_at = int(datetime.now(timezone.utc).timestamp()) + join_seconds
        embed = discord.Embed(
            title="🎁 Kincses Láda",
            description=("Reagálj **💰** emojival a zárásig. A láda teljes tartalmát egyenlően szétosztjuk "
                         "a résztvevők között. **A csatlakozás ingyenes, negatív tárcával is részt vehetsz.**"),
            color=SUCCESS,
        )
        embed.add_field(name="💎 Nyereményalap", value=f"**{money(amount)}**", inline=True)
        embed.add_field(name="⏳ Zárás", value=f"<t:{end_at}:R>", inline=True)
        embed.add_field(name="💰 Csatlakozás", value="Reagálj erre az üzenetre", inline=False)
        embed.set_footer(text="Yoru • Kincses Láda" + (" • Automatikus event" if automatic else ""))

        if not await self._reserve_event(guild_id, "safe", 0):
            return None
        try:
            message = await channel.send(embed=embed)
            self.active_events[guild_id] = ActiveEvent(kind="safe", message_id=message.id)
        except Exception:
            self._release_event(guild_id)
            raise
        await message.add_reaction(self.SAFE_EMOJI)
        asyncio.create_task(self._finish_safe(message, guild_id, amount, join_seconds, starter))
        return message

    async def _finish_safe(
        self,
        message: discord.Message,
        guild_id: int,
        amount: int,
        join_seconds: int,
        starter: discord.abc.User | None,
    ) -> None:
        try:
            await asyncio.sleep(join_seconds)
            participants = await self._get_participants(message, self.SAFE_EMOJI)
            if not participants:
                embed = base_embed(
                    "🔒 Kincses Láda • Végeredmény",
                    "Senki nem csatlakozott időben, ezért most nem történt kiosztás.",
                    discord.Color.dark_grey(),
                )
                await message.channel.send(embed=embed)
                return

            share, remainder = divmod(amount, len(participants))
            for user in participants:
                # Kincses Láda ingyenes event: negatív wallet sem kizáró ok.
                await self.economy.db.ensure_user(guild_id, user.id)
                await self.economy.db.add_wallet(guild_id, user.id, share, "safe_event", allow_negative=True)
                await self.bot.statistics.increment(guild_id, user.id, "community.treasure_chest.participations")
                await self.bot.statistics.add(guild_id, user.id, "community.treasure_chest.earned", share)
                await self.bot.statistics.set_max(guild_id, user.id, "community.treasure_chest.biggest_share", share)

            names = "\n".join(f"💰 **{user.display_name}** — +{money(share)}" for user in participants[:25])
            if len(participants) > 25:
                names += f"\n…és még **{len(participants) - 25} fő**"

            embed = discord.Embed(
                title="✨ Kincses Láda • Végeredmény",
                description=f"A láda tartalmát **{len(participants)} játékos** között osztottuk szét.",
                color=GOLD,
            )
            embed.add_field(name="💰 Fejenként", value=f"**{money(share)}**", inline=True)
            embed.add_field(name="💎 Összesen kiosztva", value=f"**{money(share * len(participants))}**", inline=True)
            embed.add_field(name="🪙 Maradék", value=f"**{money(remainder)}**", inline=True)
            embed.add_field(name="🏆 Részesültek", value=names, inline=False)
            embed.set_footer(text=(f"Yoru • Indította: {starter.display_name}" if starter else "Yoru • Automatikus Kincses Láda"))
            await message.channel.send(embed=embed)
        except Exception:
            logger.exception("Hiba történt a Kincses Láda lezárásakor.")
        finally:
            self._release_event(guild_id)

    def _bomb_signup_embed(
        self,
        *,
        entry_fee: int,
        round_seconds: int,
        end_at: int,
        participants: list[discord.User | discord.Member],
        automatic: bool,
        rejected_count: int = 0,
    ) -> discord.Embed:
        pot = entry_fee * len(participants)
        embed = discord.Embed(
            title="☠️ Hirtelen Halál",
            description=(
                "Reagálj **💣** emojival a nevezéshez. A nevezés lezárásakor levonjuk a belépőt, "
                "majd körönként egy játékos kiesik. **Az utolsó túlélő viszi a teljes potot.**"
            ),
            color=DANGER,
        )
        embed.add_field(name="🎟️ Belépő", value=f"**{money(entry_fee)} / fő**", inline=True)
        embed.add_field(name="🏆 Aktuális pot", value=f"**{money(pot)}**", inline=True)
        embed.add_field(name="👥 Nevezők", value=f"**{len(participants)} fő**", inline=True)
        embed.add_field(name="⏳ Nevezés zárása", value=f"<t:{end_at}:R>", inline=True)
        embed.add_field(name="💥 Köridő", value=f"**{round_seconds} mp**", inline=True)
        embed.add_field(name="⚔️ Minimum", value="**2 játékos**", inline=True)

        if participants:
            names = " • ".join(user.display_name for user in participants[:20])
            if len(participants) > 20:
                names += f" • +{len(participants) - 20} fő"
            embed.add_field(name="💣 Játékosok", value=names, inline=False)
        else:
            embed.add_field(name="💣 Játékosok", value="Még nincs érvényes nevező.", inline=False)

        if rejected_count:
            embed.add_field(
                name="⚠️ Nincs elég pénz",
                value=f"{rejected_count} reakció jelenleg nem számít bele a potba.",
                inline=False,
            )
        embed.set_footer(text="Yoru • Hirtelen Halál" + (" • Automatikus event" if automatic else ""))
        return embed

    async def _preview_bomb_entries(
        self,
        message: discord.Message,
        guild_id: int,
        entry_fee: int,
    ) -> tuple[list[discord.User | discord.Member], int]:
        reactors = await self._get_participants(message, self.BOMB_EMOJI)
        eligible: list[discord.User | discord.Member] = []
        rejected = 0
        for user in reactors:
            wallet, _ = await self.economy.balance(guild_id, user.id)
            if wallet >= entry_fee:
                eligible.append(user)
            else:
                rejected += 1
        return eligible, rejected

    async def _watch_bomb_signup(
        self,
        message: discord.Message,
        guild_id: int,
        entry_fee: int,
        round_seconds: int,
        end_at: int,
        automatic: bool,
    ) -> None:
        last_state: tuple[tuple[int, ...], int] | None = None
        try:
            while datetime.now(timezone.utc).timestamp() < end_at:
                participants, rejected = await self._preview_bomb_entries(message, guild_id, entry_fee)
                state = (tuple(sorted(user.id for user in participants)), rejected)
                if state != last_state:
                    await message.edit(
                        embed=self._bomb_signup_embed(
                            entry_fee=entry_fee,
                            round_seconds=round_seconds,
                            end_at=end_at,
                            participants=participants,
                            automatic=automatic,
                            rejected_count=rejected,
                        )
                    )
                    last_state = state
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Nem sikerült frissíteni a Hirtelen Halál élő potját.")

    async def _post_bomb(
        self,
        channel: discord.abc.Messageable,
        guild_id: int,
        entry_fee: int,
        join_seconds: int,
        round_seconds: int,
        starter: discord.abc.User | None,
        automatic: bool,
    ) -> discord.Message | None:
        end_at = int(datetime.now(timezone.utc).timestamp()) + join_seconds
        embed = self._bomb_signup_embed(
            entry_fee=entry_fee,
            round_seconds=round_seconds,
            end_at=end_at,
            participants=[],
            automatic=automatic,
        )

        if not await self._reserve_event(guild_id, "bomb", 0):
            return None
        try:
            message = await channel.send(embed=embed)
            self.active_events[guild_id] = ActiveEvent(kind="bomb", message_id=message.id)
        except Exception:
            self._release_event(guild_id)
            raise
        await message.add_reaction(self.BOMB_EMOJI)
        watcher = asyncio.create_task(
            self._watch_bomb_signup(message, guild_id, entry_fee, round_seconds, end_at, automatic)
        )
        asyncio.create_task(
            self._run_bomb(message, guild_id, entry_fee, join_seconds, round_seconds, starter, watcher)
        )
        return message

    async def _collect_bomb_entries(
        self,
        message: discord.Message,
        guild_id: int,
        entry_fee: int,
    ) -> tuple[list[discord.User | discord.Member], list[discord.User | discord.Member]]:
        reactors = await self._get_participants(message, self.BOMB_EMOJI)
        paid: list[discord.User | discord.Member] = []
        rejected: list[discord.User | discord.Member] = []
        for user in reactors:
            try:
                await self.economy.db.add_wallet(guild_id, user.id, -entry_fee, "hirtelen_halal_entry")
                paid.append(user)
            except ValueError:
                rejected.append(user)
            except Exception:
                # Ha technikai hiba történik a nevezések levonása közben, az addig
                # levont nevezéseket azonnal visszaadjuk, hogy senki ne veszítsen pénzt.
                for paid_user in paid:
                    await self.economy.db.refund_wallet(
                        guild_id, paid_user.id, entry_fee, "hirtelen_halal_entry_error_refund"
                    )
                raise
        return paid, rejected

    async def _run_bomb(
        self,
        message: discord.Message,
        guild_id: int,
        entry_fee: int,
        join_seconds: int,
        round_seconds: int,
        starter: discord.abc.User | None,
        watcher: asyncio.Task[None] | None = None,
    ) -> None:
        paid: list[discord.User | discord.Member] = []
        payout_complete = False
        try:
            await asyncio.sleep(join_seconds)
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            paid, rejected = await self._collect_bomb_entries(message, guild_id, entry_fee)

            if len(paid) < 2:
                for user in paid:
                    await self.economy.db.refund_wallet(guild_id, user.id, entry_fee, "hirtelen_halal_refund")
                rejected_text = f"\n**{len(rejected)} fő** nem rendelkezett elegendő pénzzel." if rejected else ""
                embed = base_embed(
                    "🛑 Hirtelen Halál • Elmaradt",
                    f"Legalább **2 fizető játékos** kell az induláshoz. A levont nevezések visszajártak.{rejected_text}",
                    discord.Color.dark_grey(),
                )
                await message.channel.send(embed=embed)
                return

            pot = entry_fee * len(paid)
            for user in paid:
                await self.bot.statistics.increment(guild_id, user.id, "community.sudden_death.entries")
                await self.bot.statistics.add(guild_id, user.id, "community.sudden_death.spent", entry_fee)
            alive = paid.copy()
            eliminated: list[discord.User | discord.Member] = []
            round_number = 1

            start_names = "\n".join(f"❤️ **{user.display_name}**" for user in alive[:25])
            start_embed = discord.Embed(
                title="☠️ Hirtelen Halál • Indul!",
                description="A nevezés lezárult. Innentől minden kör végén egy játékos kiesik.",
                color=discord.Color.orange(),
            )
            start_embed.add_field(name="👥 Játékosok", value=f"**{len(alive)} fő**", inline=True)
            start_embed.add_field(name="🎟️ Belépő", value=f"**{money(entry_fee)}**", inline=True)
            start_embed.add_field(name="🏆 Teljes pot", value=f"**{money(pot)}**", inline=True)
            start_embed.add_field(name="Játékban", value=start_names, inline=False)
            if rejected:
                start_embed.add_field(name="⚠️ Sikertelen nevezés", value=f"**{len(rejected)} fő** — nem volt elég pénz", inline=False)
            start_embed.set_footer(text="Yoru • Hirtelen Halál")
            await message.edit(embed=start_embed)

            # A Hirtelen Halál körönként külön üzenetet küld. Így akkor is visszakövethető
            # a teljes meccs, ha közben pörög a chat. Az eredeti nevezési üzenetet többé
            # nem írjuk felül minden egyes körben.
            while len(alive) > 1:
                await asyncio.sleep(round_seconds)

                loser = random.choice(alive)
                alive.remove(loser)
                eliminated.append(loser)
                await self.bot.statistics.increment(guild_id, loser.id, "community.sudden_death.eliminations")

                alive_list = "\n".join(f"❤️ **{user.display_name}**" for user in alive[:25]) or "—"
                eliminated_list = "\n".join(f"☠️ ~~{user.display_name}~~" for user in eliminated[-10:])

                round_embed = discord.Embed(
                    title=f"💥 Hirtelen Halál • {round_number}. kör",
                    description=f"**{loser.display_name}** kiesett a játékból.",
                    color=DANGER,
                )
                round_embed.add_field(name="❤️ Talpon", value=f"**{len(alive)} fő**", inline=True)
                round_embed.add_field(name="🏆 Pot", value=f"**{money(pot)}**", inline=True)

                if len(alive) > 1:
                    next_blast = int(datetime.now(timezone.utc).timestamp()) + round_seconds
                    round_embed.add_field(name="💥 Következő kiesés", value=f"<t:{next_blast}:R>", inline=True)
                else:
                    round_embed.add_field(name="🏁 Állapot", value="**Utolsó túlélő!**", inline=True)

                round_embed.add_field(name="🎮 Játékban maradt", value=alive_list, inline=False)
                round_embed.add_field(name="☠️ Kiesettek", value=eliminated_list, inline=False)
                round_embed.set_footer(text="Yoru • Hirtelen Halál")
                await message.channel.send(embed=round_embed)
                round_number += 1

            winner = alive[0]
            await self.economy.db.add_wallet(guild_id, winner.id, pot, "hirtelen_halal_win")
            payout_complete = True
            await self.bot.statistics.increment(guild_id, winner.id, "community.sudden_death.wins")
            await self.bot.statistics.add(guild_id, winner.id, "community.sudden_death.earned", pot)
            await self.bot.statistics.set_max(guild_id, winner.id, "community.sudden_death.biggest_win", pot)
            embed = discord.Embed(
                title="🏆 Hirtelen Halál • Győztes",
                description=f"**{winner.display_name}** maradt utoljára talpon és elvitte a teljes potot.",
                color=GOLD,
            )
            embed.add_field(name="💰 Nyeremény", value=f"**{money(pot)}**", inline=True)
            embed.add_field(name="🎟️ Belépő", value=f"**{money(entry_fee)}**", inline=True)
            embed.add_field(name="👥 Résztvevők", value=f"**{len(paid)} fő**", inline=True)
            embed.set_footer(text=(f"Yoru • Indította: {starter.display_name}" if starter else "Yoru • Automatikus Hirtelen Halál"))
            await message.channel.send(embed=embed)
        except Exception:
            logger.exception("Hiba történt a Hirtelen Halál futása közben.")
            # Ha a játék a nevezések levonása után technikai hibával áll le, visszaadjuk a nevezéseket.
            if paid and not payout_complete:
                for user in paid:
                    try:
                        await self.economy.db.refund_wallet(guild_id, user.id, entry_fee, "hirtelen_halal_error_refund")
                    except Exception:
                        logger.exception("Nem sikerült Hirtelen Halál refundot adni user=%s", user.id)
        finally:
            self._release_event(guild_id)

    async def _automatic_event_loop(self) -> None:
        await self.bot.wait_until_ready()
        settings = self.bot.settings  # type: ignore[attr-defined]

        while not self.bot.is_closed():
            # A random időzítés megmarad, de ez csak a legkorábbi auto-event idő.
            # Ha addig nincs elég aktivitás, a bot csendben vár az activity gate-re.
            delay_seconds = random.uniform(
                settings.auto_event_min_hours * 3600,
                settings.auto_event_max_hours * 3600,
            )
            logger.info(
                "Auto event legkorábban %.1f perc múlva; aktivitás kell: %s üzenet / %s user / %s perc.",
                delay_seconds / 60,
                settings.auto_event_activity_messages,
                settings.auto_event_activity_min_users,
                settings.auto_event_activity_window_minutes,
            )
            await asyncio.sleep(delay_seconds)

            channel = self.bot.get_channel(settings.event_channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(settings.event_channel_id)
                except discord.DiscordException:
                    logger.exception("Az EVENT_CHANNEL_ID csatorna nem érhető el.")
                    continue

            guild = getattr(channel, "guild", None)
            if guild is None:
                continue

            gate = self._activity_gate(guild.id)
            status = self.get_activity_status(guild.id)
            if not status["armed"]:
                logger.info(
                    "Auto event timer lejárt, de nincs elég aktivitás guild=%s (%s/%s üzenet, %s/%s user). Várakozás.",
                    guild.id,
                    status["messages"],
                    status["required_messages"],
                    status["users"],
                    status["required_users"],
                )
                await gate.wait()

            # Manuális event alatt nem indítunk rá automatikusat. Ha közben a chat
            # lecsendesedik és lejár a rolling activity ablak, új aktivitást várunk.
            while not self.bot.is_closed():
                while guild.id in self.active_events and not self.bot.is_closed():
                    await asyncio.sleep(5)
                if self.bot.is_closed():
                    break
                status = self.get_activity_status(guild.id)
                if status["armed"]:
                    break
                logger.info(
                    "Az auto event aktivitás közben elévült guild=%s; új aktivitásra várunk.",
                    guild.id,
                )
                await gate.wait()
            if self.bot.is_closed():
                break

            started = False
            try:
                if random.random() < eco.AUTO_EVENT_SAFE_CHANCE:
                    amount = random.randint(settings.auto_safe_min_reward, settings.auto_safe_max_reward)
                    started = (
                        await self._post_safe(
                            channel, guild.id, amount, settings.auto_join_seconds, None, True
                        )
                    ) is not None
                else:
                    entry_fee = random.randint(settings.auto_bomb_min_entry, settings.auto_bomb_max_entry)
                    started = (
                        await self._post_bomb(
                            channel,
                            guild.id,
                            entry_fee,
                            settings.auto_join_seconds,
                            settings.auto_bomb_round_seconds,
                            None,
                            True,
                        )
                    ) is not None
            except Exception:
                logger.exception("Nem sikerült automatikus eventet indítani.")

            if started:
                # Egy sikeresen elindult auto event elfogyasztja az aktivitást.
                # A következőhöz ismét új, valódi chat activity kell.
                self._reset_activity(guild.id)
            else:
                # Technikai hiba / race esetén ne pörögjön forró loopban.
                await asyncio.sleep(30)
