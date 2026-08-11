from __future__ import annotations

from datetime import datetime
import math

import discord
from discord import app_commands
from discord.ext import commands

from app.services.economy import CooldownError, EconomyService, JailError
from app.amounts import parse_amount
from app.ui import DANGER, GOLD, SUCCESS, action_embed, cooldown_embed, error_embed, money
from app.profile_ui import make_profile_view
from app import economy_config as eco


def parse_amount_input(raw: str, maximum: int | None = None) -> int:
    return parse_amount(raw, maximum)


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot, economy: EconomyService) -> None:
        self.bot = bot
        self.economy = economy

    async def _guard(self, interaction: discord.Interaction, feature: str = "economy") -> bool:
        if interaction.guild_id is None:
            return False
        try:
            await self.economy.require_access(interaction.guild_id, feature, interaction.channel_id, getattr(interaction.channel, "category_id", None))
        except ValueError as error:
            await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
            return False
        return True

    @app_commands.command(name="balance", description="Megmutatja az egyenleget.")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None: return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)
        if not await self._guard(interaction): return
        target = member or interaction.user
        wallet, bank = await self.economy.balance(interaction.guild_id, target.id)
        embed = discord.Embed(title=f"💰 {target.display_name} egyenlege", color=discord.Color.gold())
        embed.add_field(name="Tárca", value=money(wallet), inline=True)
        embed.add_field(name="Bank", value=money(bank), inline=True)
        embed.add_field(name="Összesen", value=money(wallet + bank), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="Megnyitja egy tag interaktív Yoru profilját.")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)
        if not await self._guard(interaction):
            return
        target = member or interaction.user
        embed, view = await make_profile_view(self.bot, interaction.guild_id, target, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="stats", description="Megnyitja egy tag részletes Yoru statisztikáit.")
    async def stats(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)
        if not await self._guard(interaction):
            return
        target = member or interaction.user
        embed, view = await make_profile_view(self.bot, interaction.guild_id, target, interaction.user.id, initial_page="stats")
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="bank", description="Megmutatja a bankod és a tárcád állapotát.")
    async def bank(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return await interaction.response.send_message("Csak szerveren használható.", ephemeral=True)
        if not await self._guard(interaction, "bank"): return
        wallet, bank = await self.economy.balance(interaction.guild_id, interaction.user.id)
        embed = action_embed("🏦 Bank", interaction.user)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        embed.add_field(name="💎 Vagyon", value=f"**{money(wallet + bank)}**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="deposit", description="Pénzt helyezel a tárcádból a bankba.")
    @app_commands.describe(osszeg="Összeg: pl. 500000, 25k, 2m vagy all")
    async def deposit(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction, "bank"):
            return
        current_wallet, _ = await self.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            amount = parse_amount_input(osszeg, current_wallet)
            wallet, bank = await self.economy.deposit(interaction.guild_id, interaction.user.id, amount)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🏦 Befizetés", interaction.user, color=SUCCESS)
        embed.add_field(name="📥 Betett összeg", value=f"**{money(amount)}**", inline=False)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="withdraw", description="Pénzt veszel ki a bankodból.")
    @app_commands.describe(osszeg="Összeg: pl. 500000, 25k, 2m vagy all")
    async def withdraw(self, interaction: discord.Interaction, osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction, "bank"):
            return
        _, current_bank = await self.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            amount = parse_amount_input(osszeg, current_bank)
            wallet, bank = await self.economy.withdraw(interaction.guild_id, interaction.user.id, amount)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("💵 Kifizetés", interaction.user, color=SUCCESS)
        embed.add_field(name="📤 Kivett összeg", value=f"**{money(amount)}**", inline=False)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pay", description="Pénzt küldesz egy másik tagnak.")
    @app_commands.describe(osszeg="Tét: pl. 25k, 2m, 1b, 1t vagy all")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, osszeg: str) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction): return
        if member.bot: return await interaction.response.send_message(embed=error_embed(interaction.user, "Botnak nem küldhetsz pénzt."), ephemeral=True)
        current_wallet, _ = await self.economy.balance(interaction.guild_id, interaction.user.id)
        try:
            amount = parse_amount(osszeg, current_wallet)
            sender_wallet, _ = await self.economy.pay(interaction.guild_id, interaction.user.id, member.id, amount)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("💸 Átutalás", interaction.user, color=SUCCESS)
        embed.add_field(name="👤 Címzett", value=f"**{member.display_name}**", inline=True)
        embed.add_field(name="💰 Összeg", value=f"**{money(amount)}**", inline=True)
        embed.add_field(name="💵 Maradék", value=f"**{money(sender_wallet)}**", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Átveszed a napi jutalmadat.")
    async def daily(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "daily"): return
        try: reward, streak, ready_at = await self.economy.claim_daily(interaction.guild_id, interaction.user.id)
        except CooldownError as error: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Daily", error.ready_at), ephemeral=True)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🎁 Daily", interaction.user, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="🔥 Streak", value=f"**{streak} nap**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="beg", description="Kérsz egy kis aprót.")
    async def beg(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "beg"): return
        try: reward, outcome, ready_at = await self.economy.beg(interaction.guild_id, interaction.user.id)
        except CooldownError as error: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Beg", error.ready_at), ephemeral=True)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🙏 Beg", interaction.user, description=outcome, color=SUCCESS if reward else GOLD)
        embed.add_field(name="💰 Eredmény", value=f"**{money(reward)}**" if reward else "**Nem kaptál semmit.**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="search", description="Véletlenszerű helyen pénzt keresel.")
    async def search(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "search"): return
        try: reward, place, ready_at, dropped = await self.economy.search(interaction.guild_id, interaction.user.id)
        except CooldownError as error: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Search", error.ready_at), ephemeral=True)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🔎 Search", interaction.user, color=SUCCESS)
        embed.add_field(name="📍 Hely", value=f"**{place}**", inline=False)
        embed.add_field(name="💰 Találtál", value=f"**{money(reward)}**", inline=True)
        if dropped:
            item_id, name, emoji = dropped
            embed.add_field(name="🎁 Ritka találat!", value=f"{emoji} **{name}** (`{item_id}`)", inline=False)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slut", description="Kurválkodsz egy kis pénz reményében.")
    async def slut(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "slut"): return
        try:
            success, amount, text, ready_at = await self.economy.slut(interaction.guild_id, interaction.user.id)
        except JailError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
        except CooldownError as error:
            return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Slut", error.ready_at), ephemeral=True)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("💋 Slut", interaction.user, description=text, color=SUCCESS if success else DANGER)
        embed.add_field(name="💰 Eredmény", value=(f"**+{money(amount)}**" if success else f"**-{money(amount)}**"), inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="cooldowns", description="Megmutatja az economy cooldownjaidat.")
    async def cooldowns(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction): return
        values = await self.economy.cooldowns(interaction.guild_id, interaction.user.id)
        labels = {"daily":"🎁 Daily","beg":"🙏 Beg","search":"🔎 Search","work":"🛠️ Work","crime":"🕵️ Crime","rob":"🥷 Rob","weekly":"📅 Weekly","monthly":"🗓️ Monthly","interest":"🏦 Interest","slut":"💋 Slut","claimincome":"💼 Role Income"}
        lines = []
        for key, ready_at in values.items():
            status = "✅ Elérhető" if ready_at is None else f"<t:{int(ready_at.timestamp())}:R>"
            lines.append(f"{labels[key]} — **{status}**")
        await interaction.response.send_message(embed=action_embed("⏱️ Cooldownok", interaction.user, description="\n".join(lines)), ephemeral=True)

    @app_commands.command(name="work", description="Dolgozol egy kis pénzért.")
    async def work(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "work"): return
        try: reward, job, ready_at = await self.economy.work(interaction.guild_id, interaction.user.id)
        except JailError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
        except CooldownError as error: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Work", error.ready_at), ephemeral=True)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🛠️ Work", interaction.user, description=job.capitalize(), color=SUCCESS)
        embed.add_field(name="💰 Fizetés", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő műszak", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crime", description="Kockázatos bűncselekményt követsz el pénzért.")
    async def crime(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "crime"): return
        try: success, amount, scenario, ready_at, jail_until = await self.economy.crime(interaction.guild_id, interaction.user.id)
        except JailError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
        except CooldownError as error: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Crime", error.ready_at), ephemeral=True)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🕵️ Crime", interaction.user, description=scenario.capitalize(), color=SUCCESS if success else DANGER)
        embed.add_field(name="✅ Eredmény" if success else "🚓 Lebuktál", value=(f"**+{money(amount)}**" if success else f"**-{money(amount)}**"), inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        if jail_until: embed.add_field(name="🚔 Börtön", value=f"<t:{int(jail_until.timestamp())}:R>", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rob", description="Megpróbálsz kirabolni egy másik tagot.")
    async def rob(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "rob"): return
        if member.bot: return await interaction.response.send_message(embed=error_embed(interaction.user, "Botot nem rabolhatsz ki."), ephemeral=True)
        try: success, amount, ready_at = await self.economy.rob(interaction.guild_id, interaction.user.id, member.id)
        except JailError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"), ephemeral=True)
        except CooldownError as error: return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Rob", error.ready_at), ephemeral=True)
        except ValueError as error: return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("🥷 Rob", interaction.user, color=SUCCESS if success else DANGER)
        embed.add_field(name="🎯 Célpont", value=f"**{member.display_name}**", inline=False)
        embed.add_field(name="✅ Zsákmány" if success else "❌ Kártérítés", value=(f"**+{money(amount)}**" if success else f"**-{money(amount)}**"), inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roleincome", description="Megmutatja a szerver rangalapú bevételeit.")
    async def roleincome(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None: return
        if not await self._guard(interaction, "role_income"): return
        rows = await self.economy.role_income_list(interaction.guild_id)
        if not rows:
            return await interaction.response.send_message(
                embed=error_embed(interaction.user, "Még nincs beállítva Role Income.", title="💼 Role Income"),
                ephemeral=True,
            )
        embed = action_embed("💼 Role Income", interaction.user, color=SUCCESS)
        embed.description = "\n".join(f"<@&{role_id}> — **{money(amount)} / óra**" for role_id, amount in rows)
        embed.set_footer(text="Yoru • Maximum 24 óra gyűlik • Alapból csak a legmagasabb Role Income számít")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="claimincome", description="Átveszed a rangjaid után járó bevételt.")
    async def claimincome(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or not isinstance(interaction.user, discord.Member): return
        if not await self._guard(interaction, "role_income"): return
        role_ids = {role.id for role in interaction.user.roles}
        try:
            reward, hours, _ = await self.economy.claim_role_income(interaction.guild_id, interaction.user.id, role_ids)
        except CooldownError as error:
            return await interaction.response.send_message(embed=cooldown_embed(interaction.user, "Role Income", error.ready_at), ephemeral=True)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        embed = action_embed("💼 Role Income", interaction.user, color=SUCCESS)
        embed.add_field(name="⏱️ Elszámolt idő", value=f"**{hours} óra**", inline=True)
        embed.add_field(name="💰 Jóváírás", value=f"**{money(reward)}**", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setroleincome", description="Role Income beállítása egy ranghoz.")
    @app_commands.describe(orankenti_osszeg="Pl. 5k, 10k, 25k; kikapcsoláshoz 0")
    @app_commands.checks.has_permissions(administrator=True)
    async def setroleincome(self, interaction: discord.Interaction, role: discord.Role, orankenti_osszeg: str) -> None:
        if interaction.guild_id is None:
            return
        raw = orankenti_osszeg.strip().lower()
        try:
            parsed = 0 if raw in {"0", "off", "ki"} else parse_amount(raw)
        except ValueError as error:
            return await interaction.response.send_message(embed=error_embed(interaction.user, str(error)), ephemeral=True)
        await self.economy.set_role_income(interaction.guild_id, role.id, parsed)
        embed = action_embed("💼 Role Income beállítás", interaction.user, color=SUCCESS)
        embed.add_field(name="🎭 Rang", value=role.mention, inline=True)
        embed.add_field(
            name="💰 Óránkénti bevétel",
            value=(f"**{money(parsed)}**" if parsed else "**Kikapcsolva**"),
            inline=True,
        )
        if parsed > eco.ROLE_INCOME_BALANCE_WARNING_PER_HOUR:
            embed.add_field(
                name="⚠️ Economy figyelmeztetés",
                value=(
                    f"Ez meghaladja a javasolt **{money(eco.ROLE_INCOME_BALANCE_WARNING_PER_HOUR)} / óra** szintet. "
                    "Nincs hard cap, de ilyen érték mellett a progression gyorsan felborulhat."
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _send_top(self, interaction: discord.Interaction, category: str) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        rows = await self.economy.leaderboard(interaction.guild_id, category, 10)
        labels = {
            "money":"💰 Vagyon", "wallet":"💵 Tárca", "bank":"🏦 Bank",
            "rob":"🥷 Rablási profit", "gambling":"🎰 Gambling profit",
            "wins":"🏆 Játékgyőzelmek", "work":"🛠️ Elvégzett munkák",
            "crime":"🕵️ Sikeres crime", "daily":"🔥 Daily streak",
            "earned":"💹 Összes kereset", "chicken":"🐔 Chicken Fight win",
            "scratch":"🎟️ Lekapart sorsjegyek", "weekly":"📅 Weekly átvételek",
            "level":"⭐ Szint / XP", "investment":"📈 Befektetés profit",
            "jackpot":"🎰 Jackpot győzelem", "lottery":"🎟️ Lottery győzelem",
        }
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        money_categories = {"money", "wallet", "bank", "rob", "gambling", "earned", "investment"}
        for index, (user_id, secondary, tertiary, score) in enumerate(rows, 1):
            prefix = medals[index - 1] if index <= 3 else f"`{index}.`"
            if category in money_categories:
                shown = money(score)
            elif category == "level":
                shown = f"{score:,} XP".replace(",", " ")
            elif category == "daily":
                shown = f"{score} nap"
            else:
                shown = f"{score} db"
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            name = member.display_name if member else f"User {user_id}"
            lines.append(f"{prefix} **{name}** — **{shown}**")
        embed = discord.Embed(
            title=f"🏆 Toplista • {labels.get(category, category)}",
            description="\n".join(lines) or "Még nincs adat.",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="top", description="Toplista különböző kategóriákban.")
    @app_commands.choices(kategoria=[
        app_commands.Choice(name="Vagyon", value="money"),
        app_commands.Choice(name="Tárca", value="wallet"),
        app_commands.Choice(name="Bank", value="bank"),
        app_commands.Choice(name="Rablási profit", value="rob"),
        app_commands.Choice(name="Gambling profit", value="gambling"),
        app_commands.Choice(name="Játékgyőzelmek", value="wins"),
        app_commands.Choice(name="Elvégzett munkák", value="work"),
        app_commands.Choice(name="Sikeres crime", value="crime"),
        app_commands.Choice(name="Daily streak", value="daily"),
        app_commands.Choice(name="Összes kereset", value="earned"),
        app_commands.Choice(name="Chicken Fight win", value="chicken"),
        app_commands.Choice(name="Lekapart sorsjegyek", value="scratch"),
        app_commands.Choice(name="Weekly átvételek", value="weekly"),
        app_commands.Choice(name="Szint / XP", value="level"),
        app_commands.Choice(name="Befektetés profit", value="investment"),
        app_commands.Choice(name="Jackpot győzelem", value="jackpot"),
        app_commands.Choice(name="Lottery győzelem", value="lottery"),
    ])
    async def top(self, interaction: discord.Interaction, kategoria: app_commands.Choice[str]) -> None:
        await self._send_top(interaction, kategoria.value)

    @app_commands.command(name="leaderboard", description="Megmutatja a szerver leggazdagabb tagjait.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await self._send_top(interaction, "money")

    @app_commands.command(name="jail", description="Megmutatja, hogy valaki börtönben van-e.")
    async def jail(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        if interaction.guild_id is None:
            return
        if not await self._guard(interaction):
            return
        target = member or interaction.user
        until = await self.economy.jail_status(interaction.guild_id, target.id)
        embed = action_embed("🚔 Börtön státusz", interaction.user, color=DANGER if until else SUCCESS)
        embed.add_field(name="👤 Játékos", value=f"**{target.display_name}**", inline=True)
        embed.add_field(name="Állapot", value=(f"<t:{int(until.timestamp())}:R>" if until else "**Szabad**"), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @setroleincome.error
    async def setroleincome_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Ehhez adminisztrátori jogosultság kell.", ephemeral=True)
            return
        raise error
