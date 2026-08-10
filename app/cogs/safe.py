from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from app import economy_config as eco
from app.services.economy import EconomyService
from app.ui import money

logger = logging.getLogger("vaultbot.safe")

SAFE_EMOJI = "💰"


@dataclass
class ActiveSafe:
    message_id: int
    channel_id: int
    prize: int
    ends_at: int


class SafeCog(commands.Cog):
    def __init__(self, bot: commands.Bot, economy: EconomyService) -> None:
        self.bot = bot
        self.economy = economy
        self.active_safes: dict[int, ActiveSafe] = {}

    @app_commands.command(
        name="safe",
        description="Adminisztrátorként elindítasz egy pénzosztó széf eseményt.",
    )
    @app_commands.describe(
        osszeg="A teljes kiosztandó pénzösszeg.",
        ido="Jelentkezési idő másodpercben.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def safe(
        self,
        interaction: discord.Interaction,
        osszeg: app_commands.Range[int, eco.EVENT_MIN_REWARD],
        ido: app_commands.Range[int, eco.EVENT_JOIN_MIN_SECONDS, eco.EVENT_JOIN_MAX_SECONDS] = eco.AUTO_EVENT_JOIN_SECONDS,
    ) -> None:
        if interaction.guild_id is None or interaction.channel is None:
            await interaction.response.send_message(
                "Ez a parancs csak szerveren használható.",
                ephemeral=True,
            )
            return

        if interaction.guild_id in self.active_safes:
            await interaction.response.send_message(
                "❌ Ezen a szerveren már fut egy Széf esemény.",
                ephemeral=True,
            )
            return

        ends_at = int(discord.utils.utcnow().timestamp()) + ido
        embed = discord.Embed(
            title="🔐 Kinyílt a Széf!",
            description=(
                f"Reagálj a(z) {SAFE_EMOJI} emojival, hogy részt vegyél!\n\n"
                f"**Teljes nyeremény:** {money(osszeg)}\n"
                f"**Lezárás:** <t:{ends_at}:R>\n\n"
                "A pénzt a bot egyenlően osztja szét minden érvényes résztvevő között."
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Indította: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction(SAFE_EMOJI)

        self.active_safes[interaction.guild_id] = ActiveSafe(
            message_id=message.id,
            channel_id=message.channel.id,
            prize=osszeg,
            ends_at=ends_at,
        )
        asyncio.create_task(self._finish_safe(interaction.guild_id, ido))

    async def _finish_safe(self, guild_id: int, delay: int) -> None:
        await asyncio.sleep(delay)
        active = self.active_safes.get(guild_id)
        if active is None:
            return

        try:
            channel = self.bot.get_channel(active.channel_id)
            if channel is None or not isinstance(channel, discord.abc.Messageable):
                raise RuntimeError("A Széf csatornája nem található.")

            message = await channel.fetch_message(active.message_id)
            participants: dict[int, discord.User | discord.Member] = {}

            for reaction in message.reactions:
                if str(reaction.emoji) != SAFE_EMOJI:
                    continue
                async for user in reaction.users():
                    if not user.bot:
                        participants[user.id] = user
                break

            if not participants:
                embed = discord.Embed(
                    title="🔒 A Széf bezárult",
                    description="Senki nem jelentkezett, ezért nem történt pénzosztás.",
                    color=discord.Color.dark_grey(),
                )
                await message.edit(embed=embed)
                return

            share = active.prize // len(participants)
            remainder = active.prize % len(participants)

            if share < 1:
                embed = discord.Embed(
                    title="🔒 A Széf bezárult",
                    description=(
                        "Túl sok résztvevő volt a megadott összeghez, ezért "
                        "fejenként kevesebb mint 1 pénz jutott volna."
                    ),
                    color=discord.Color.red(),
                )
                await message.edit(embed=embed)
                return

            paid_users: list[discord.User | discord.Member] = []
            for user in participants.values():
                try:
                    await self.economy.db.add_wallet(
                        guild_id,
                        user.id,
                        share,
                        f"safe:{active.message_id}",
                    )
                    paid_users.append(user)
                except Exception:
                    logger.exception("Nem sikerült kifizetni a Széf jutalmát: user_id=%s", user.id)

            mentions = ", ".join(user.mention for user in paid_users)
            if len(mentions) > 900:
                mentions = f"{len(paid_users)} játékos kapta meg a jutalmat."

            embed = discord.Embed(
                title="🔓 A Széf kiosztotta a pénzt!",
                description=(
                    f"**Résztvevők:** {len(participants)}\n"
                    f"**Sikeresen kifizetve:** {len(paid_users)}\n"
                    f"**Fejenként:** {money(share)}\n"
                    f"**Kiosztott összeg:** {money(share * len(paid_users))}"
                ),
                color=discord.Color.green(),
            )
            if remainder:
                embed.add_field(
                    name="Maradék",
                    value=f"{money(remainder)} nem volt egyenlően elosztható.",
                    inline=False,
                )
            embed.add_field(name="Jutalmazottak", value=mentions or "Senki", inline=False)
            await message.edit(embed=embed)

        except Exception:
            logger.exception("Hiba történt a Széf lezárásakor: guild_id=%s", guild_id)
        finally:
            self.active_safes.pop(guild_id, None)

    @safe.error
    async def safe_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ Ezt a parancsot csak adminisztrátor használhatja."
        else:
            logger.exception("Hiba a /safe parancsban", exc_info=error)
            message = "❌ Hiba történt a Széf indításakor."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
