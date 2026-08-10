from __future__ import annotations

from datetime import datetime
import math

import discord
from discord.ext import commands

from app.amounts import parse_amount
from app import economy_config as eco
from app.services.economy import CooldownError, EconomyService, JailError
from app.services.shop import ShopService
from app.shop_ui import build_shop_view
from app.services.gambling import GamblingService
from app.ui import BRAND, DANGER, GOLD, SUCCESS, action_embed, cooldown_embed, error_embed, gambling_result_embed, money
from app.profile_ui import make_profile_view


class PrefixCog(commands.Cog):
    """A slash parancsok ! prefixszel használható változatai."""

    def __init__(self, bot: commands.Bot, economy: EconomyService, shop: ShopService, gambling: GamblingService) -> None:
        self.bot = bot
        self.economy = economy
        self.shop = shop
        self.gambling = gambling

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        await ctx.send(f"🏓 Pong! **{round(self.bot.latency * 1000)} ms**")

    @commands.command(name="balance", aliases=["bal", "cash", "money"])
    @commands.guild_only()
    async def balance(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        wallet, bank = await self.economy.balance(ctx.guild.id, target.id)
        embed = discord.Embed(title=f"💰 {target.display_name} egyenlege", color=discord.Color.gold())
        embed.add_field(name="Tárca", value=money(wallet), inline=True)
        embed.add_field(name="Bank", value=money(bank), inline=True)
        embed.add_field(name="Összesen", value=money(wallet + bank), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="profile", aliases=["prof", "p"])
    @commands.guild_only()
    async def profile(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        embed, view = await make_profile_view(self.bot, ctx.guild.id, target, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="stats", aliases=["stat", "statistics"])
    @commands.guild_only()
    async def stats(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        embed, view = await make_profile_view(self.bot, ctx.guild.id, target, ctx.author.id, initial_page="stats")
        await ctx.send(embed=embed, view=view)

    @commands.command(name="bank", aliases=["banka"])
    @commands.guild_only()
    async def bank(self, ctx: commands.Context) -> None:
        wallet, bank = await self.economy.balance(ctx.guild.id, ctx.author.id)
        embed = action_embed("🏦 Bank", ctx.author)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        embed.add_field(name="💎 Vagyon", value=f"**{money(wallet + bank)}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="deposit", aliases=["dep"])
    @commands.guild_only()
    async def deposit(self, ctx: commands.Context, amount: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed = parse_amount(amount, wallet)
            new_wallet, bank = await self.economy.deposit(ctx.guild.id, ctx.author.id, parsed)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = action_embed("🏦 Befizetés", ctx.author, color=SUCCESS)
        embed.add_field(name="📥 Betett összeg", value=f"**{money(parsed)}**", inline=False)
        embed.add_field(name="💵 Tárca", value=f"**{money(new_wallet)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(bank)}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="withdraw", aliases=["with", "wd"])
    @commands.guild_only()
    async def withdraw(self, ctx: commands.Context, amount: str) -> None:
        _, bank_balance = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed = parse_amount(amount, bank_balance)
            wallet, new_bank = await self.economy.withdraw(ctx.guild.id, ctx.author.id, parsed)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = action_embed("💵 Kifizetés", ctx.author, color=SUCCESS)
        embed.add_field(name="📤 Kivett összeg", value=f"**{money(parsed)}**", inline=False)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        embed.add_field(name="🏦 Bank", value=f"**{money(new_bank)}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="pay", aliases=["give", "send"])
    @commands.guild_only()
    async def pay(self, ctx: commands.Context, member: discord.Member, amount: str) -> None:
        if member.bot:
            return await ctx.send(embed=error_embed(ctx.author, "Botnak nem küldhetsz pénzt."))
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed = parse_amount(amount, wallet)
            new_wallet, _ = await self.economy.pay(ctx.guild.id, ctx.author.id, member.id, parsed)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = action_embed("💸 Átutalás", ctx.author, color=SUCCESS)
        embed.add_field(name="👤 Címzett", value=f"**{member.display_name}**", inline=True)
        embed.add_field(name="💰 Összeg", value=f"**{money(parsed)}**", inline=True)
        embed.add_field(name="💵 Maradék", value=f"**{money(new_wallet)}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="daily", aliases=["dly"])
    @commands.guild_only()
    async def daily(self, ctx: commands.Context) -> None:
        try:
            reward, streak, ready_at = await self.economy.claim_daily(ctx.guild.id, ctx.author.id)
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Daily", error.ready_at))
        embed = action_embed("🎁 Daily", ctx.author, color=SUCCESS)
        embed.add_field(name="💰 Jutalom", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="🔥 Streak", value=f"**{streak} nap**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="beg", aliases=["koldul", "kereget"])
    @commands.guild_only()
    async def beg(self, ctx: commands.Context) -> None:
        try:
            reward, outcome, ready_at = await self.economy.beg(ctx.guild.id, ctx.author.id)
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Beg", error.ready_at))
        embed = action_embed("🙏 Beg", ctx.author, description=outcome, color=SUCCESS if reward else GOLD)
        embed.add_field(name="💰 Eredmény", value=f"**{money(reward)}**" if reward else "**Nem kaptál semmit.**", inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="search", aliases=["keres"])
    @commands.guild_only()
    async def search(self, ctx: commands.Context) -> None:
        try:
            reward, place, ready_at, dropped = await self.economy.search(ctx.guild.id, ctx.author.id)
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Search", error.ready_at))
        embed = action_embed("🔎 Search", ctx.author, color=SUCCESS)
        embed.add_field(name="📍 Hely", value=f"**{place}**", inline=False)
        embed.add_field(name="💰 Találtál", value=f"**{money(reward)}**", inline=True)
        if dropped:
            item_id, name, emoji = dropped
            embed.add_field(name="🎁 Ritka találat!", value=f"{emoji} **{name}** (`{item_id}`)", inline=False)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="slut", aliases=["kurva", "hoe"])
    @commands.guild_only()
    async def slut(self, ctx: commands.Context) -> None:
        try:
            success, amount, text, ready_at = await self.economy.slut(ctx.guild.id, ctx.author.id)
        except JailError as error:
            return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Slut", error.ready_at))
        embed = action_embed("💋 Slut", ctx.author, description=text, color=SUCCESS if success else DANGER)
        embed.add_field(name="💰 Eredmény", value=(f"**+{money(amount)}**" if success else f"**-{money(amount)}**"), inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="cooldowns", aliases=["cd"])
    @commands.guild_only()
    async def cooldowns(self, ctx: commands.Context) -> None:
        values = await self.economy.cooldowns(ctx.guild.id, ctx.author.id)
        labels = {
            "daily": "🎁 Daily", "beg": "🙏 Beg", "search": "🔎 Search",
            "work": "🛠️ Work", "crime": "🕵️ Crime", "rob": "🥷 Rob",
            "weekly": "📅 Weekly", "monthly": "🗓️ Monthly", "interest": "🏦 Interest",
            "slut": "💋 Slut", "claimincome": "💼 Role Income",
        }
        lines = []
        for key, ready_at in values.items():
            status = "✅ Elérhető" if ready_at is None else f"<t:{int(ready_at.timestamp())}:R>"
            lines.append(f"{labels[key]} — **{status}**")
        embed = action_embed("⏱️ Cooldownok", ctx.author, description="\n".join(lines))
        await ctx.send(embed=embed)

    @commands.command(name="work", aliases=["w"])
    @commands.guild_only()
    async def work(self, ctx: commands.Context) -> None:
        try:
            reward, job, ready_at = await self.economy.work(ctx.guild.id, ctx.author.id)
        except JailError as error:
            return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Work", error.ready_at))
        embed = action_embed("🛠️ Work", ctx.author, description=job.capitalize(), color=SUCCESS)
        embed.add_field(name="💰 Fizetés", value=f"**{money(reward)}**", inline=True)
        embed.add_field(name="⏳ Következő műszak", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="crime", aliases=["cr"])
    @commands.guild_only()
    async def crime(self, ctx: commands.Context) -> None:
        try:
            success, amount, scenario, ready_at, jail_until = await self.economy.crime(ctx.guild.id, ctx.author.id)
        except JailError as error:
            return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Crime", error.ready_at))
        embed = action_embed("🕵️ Crime", ctx.author, description=scenario.capitalize(), color=SUCCESS if success else DANGER)
        embed.add_field(name="✅ Eredmény" if success else "🚓 Lebuktál", value=(f"**+{money(amount)}**" if success else f"**-{money(amount)}**"), inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        if jail_until:
            embed.add_field(name="🚔 Börtön", value=f"<t:{int(jail_until.timestamp())}:R>", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="rob", aliases=["steal"])
    @commands.guild_only()
    async def rob(self, ctx: commands.Context, member: discord.Member) -> None:
        if member.bot:
            return await ctx.send(embed=error_embed(ctx.author, "Botot nem rabolhatsz ki."))
        try:
            success, amount, ready_at = await self.economy.rob(ctx.guild.id, ctx.author.id, member.id)
        except JailError as error:
            return await ctx.send(embed=error_embed(ctx.author, f"Börtönben vagy még: <t:{int(error.ready_at.timestamp())}:R>", title="🚔 Börtön"))
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Rob", error.ready_at))
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = action_embed("🥷 Rob", ctx.author, color=SUCCESS if success else DANGER)
        embed.add_field(name="🎯 Célpont", value=f"**{member.display_name}**", inline=False)
        embed.add_field(name="✅ Zsákmány" if success else "❌ Kártérítés", value=(f"**+{money(amount)}**" if success else f"**-{money(amount)}**"), inline=True)
        embed.add_field(name="⏳ Következő", value=f"<t:{int(ready_at.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="roleincome", aliases=["ri"])
    @commands.guild_only()
    async def roleincome(self, ctx: commands.Context) -> None:
        rows = await self.economy.role_income_list(ctx.guild.id)
        if not rows:
            return await ctx.send(embed=error_embed(ctx.author, "Még nincs beállítva Role Income.", title="💼 Role Income"))
        embed = action_embed("💼 Role Income", ctx.author, color=SUCCESS)
        embed.description = "\n".join(f"<@&{role_id}> — **{money(amount)} / óra**" for role_id, amount in rows)
        embed.set_footer(text="Yoru • Maximum 24 óra gyűlik • Alapból csak a legmagasabb Role Income számít")
        await ctx.send(embed=embed)

    @commands.command(name="claimincome", aliases=["ci", "claim"])
    @commands.guild_only()
    async def claimincome(self, ctx: commands.Context) -> None:
        role_ids = {role.id for role in ctx.author.roles}
        try:
            reward, hours, _ = await self.economy.claim_role_income(ctx.guild.id, ctx.author.id, role_ids)
        except CooldownError as error:
            return await ctx.send(embed=cooldown_embed(ctx.author, "Role Income", error.ready_at))
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        embed = action_embed("💼 Role Income", ctx.author, color=SUCCESS)
        embed.add_field(name="⏱️ Elszámolt idő", value=f"**{hours} óra**", inline=True)
        embed.add_field(name="💰 Jóváírás", value=f"**{money(reward)}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="setroleincome", aliases=["sri"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setroleincome(self, ctx: commands.Context, role: discord.Role, hourly_amount: str) -> None:
        raw = hourly_amount.strip().lower()
        try:
            parsed = 0 if raw in {"0", "off", "ki"} else parse_amount(raw)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await self.economy.set_role_income(ctx.guild.id, role.id, parsed)
        embed = action_embed("💼 Role Income beállítás", ctx.author, color=SUCCESS)
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
        await ctx.send(embed=embed)

    @commands.command(name="top", aliases=["leaderboard", "lb"])
    @commands.guild_only()
    async def top(self, ctx: commands.Context, category: str = "money") -> None:
        aliases = {"money":"money","vagyon":"money","wallet":"wallet","cash":"wallet","bank":"bank","rob":"rob","rablás":"rob","gambling":"gambling","gamble":"gambling","wins":"wins","work":"work","crime":"crime","daily":"daily","streak":"daily","earned":"earned","chicken":"chicken","cock":"chicken","scratch":"scratch","weekly":"weekly","level":"level","lvl":"level","investment":"investment","invest":"investment","jackpot":"jackpot","jp":"jackpot","lottery":"lottery","lotto":"lottery"}
        category = aliases.get(category.lower(), "money")
        rows = await self.economy.leaderboard(ctx.guild.id, category, 10)
        labels = {"money":"💰 Vagyon","wallet":"💵 Tárca","bank":"🏦 Bank","rob":"🥷 Rablási profit","gambling":"🎰 Gambling profit","wins":"🏆 Játékgyőzelmek","work":"🛠️ Elvégzett munkák","crime":"🕵️ Sikeres crime","daily":"🔥 Daily streak","earned":"💹 Összes kereset","chicken":"🐔 Chicken Fight win","scratch":"🎟️ Lekapart sorsjegyek","weekly":"📅 Weekly átvételek","level":"⭐ Szint / XP","investment":"📈 Befektetés profit","jackpot":"🎰 Jackpot győzelem","lottery":"🎟️ Lottery győzelem"}
        lines = []
        for index, (user_id, _, _, score) in enumerate(rows, 1):
            if category in {"money", "wallet", "bank", "rob", "gambling", "earned", "investment"}:
                shown = money(score)
            elif category == "level":
                shown = f"{score:,} XP".replace(",", " ")
            elif category == "daily":
                shown = f"{score} nap"
            else:
                shown = f"{score} db"
            lines.append(f"`{index}.` <@{user_id}> — **{shown}**")
        await ctx.send(embed=discord.Embed(title=f"🏆 Toplista • {labels[category]}", description="\n".join(lines) or "Még nincs adat.", color=discord.Color.gold()))

    @commands.command(name="history", aliases=["hist", "transactions", "tx"])
    @commands.guild_only()
    async def history(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        rows = await self.economy.history(ctx.guild.id, target.id, 10)
        if not rows:
            return await ctx.send(embed=error_embed(ctx.author, "Még nincs tranzakció.", title="📜 Tranzakciók"))
        lines = []
        for amount, reason, created_at in rows:
            if amount > 0:
                shown = f"+{money(amount)}"
            elif amount < 0:
                shown = f"-{money(abs(amount))}"
            else:
                shown = money(0)
            lines.append(f"`{shown}` • **{reason}** • <t:{int(datetime.fromisoformat(created_at).timestamp())}:R>")
        embed = discord.Embed(title=f"📜 {target.display_name} utolsó tranzakciói", description="\n".join(lines), color=discord.Color.dark_teal())
        await ctx.send(embed=embed)

    @commands.command(name="addmoney", aliases=["am"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def addmoney(self, ctx: commands.Context, member: discord.Member, amount: str) -> None:
        try:
            parsed = parse_amount(amount)
            wallet = await self.economy.admin_add(ctx.guild.id, member.id, parsed, ctx.author.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"✅ {member.mention} kapott **{money(parsed)}** összeget. Új tárca: **{money(wallet)}**")

    @commands.command(name="removemoney", aliases=["rm"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def removemoney(self, ctx: commands.Context, member: discord.Member, amount: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, member.id)
        try:
            parsed = parse_amount(amount, wallet)
            new_wallet = await self.economy.admin_add(ctx.guild.id, member.id, -parsed, ctx.author.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"✅ {member.mention} tárcájából levonva **{money(parsed)}**. Új tárca: **{money(new_wallet)}**")

    @commands.command(name="setmoney", aliases=["sm"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setmoney(self, ctx: commands.Context, member: discord.Member, amount: str) -> None:
        try:
            parsed = parse_amount(amount)
            wallet = await self.economy.admin_set(ctx.guild.id, member.id, parsed, ctx.author.id)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(f"✅ {member.mention} tárcája beállítva: **{money(wallet)}**")

    @commands.command(name="shop", aliases=["store"])
    @commands.guild_only()
    async def shop_command(self, ctx: commands.Context, category: str | None = None) -> None:
        view = await build_shop_view(self.shop, ctx.guild.id, category=category)
        await ctx.send(view=view)

    @commands.command(name="buy", aliases=["purchase"])
    @commands.guild_only()
    async def buy(self, ctx: commands.Context, item: str, quantity: int = 1) -> None:
        try:
            name, emoji, total_price, new_wallet, stock = await self.shop.buy(ctx.guild.id, ctx.author.id, item, quantity)
        except (ValueError, LookupError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        is_premium = item.lower().strip() in eco.PREMIUM_REWARD_RULES
        embed = action_embed("🛒 Vásárlás", ctx.author, color=SUCCESS)
        embed.add_field(name="📦 Tárgy", value=f"**{quantity}× {emoji} {name}**", inline=False)
        embed.add_field(name="💰 Ár", value=f"**{money(total_price)}**", inline=True)
        embed.add_field(name="💵 Maradék", value=f"**{money(new_wallet)}**", inline=True)
        if stock is not None:
            embed.add_field(
                name="🎁 Havi szerverkészlet" if is_premium else "📊 Mai készlet",
                value=f"**{stock} db**",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="sell", aliases=["s"])
    @commands.guild_only()
    async def sell(self, ctx: commands.Context, item: str, quantity: int = 1) -> None:
        try:
            name, emoji, value, wallet, stock = await self.shop.sell(ctx.guild.id, ctx.author.id, item, quantity)
        except (ValueError, LookupError) as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        stock_text = f" • Mai készlet: **{stock} db**" if stock is not None else ""
        embed = action_embed("💱 Eladás", ctx.author, color=SUCCESS)
        embed.add_field(name="📦 Tárgy", value=f"**{quantity}× {emoji} {name}**", inline=False)
        embed.add_field(name="💰 Bevétel", value=f"**{money(value)}**", inline=True)
        embed.add_field(name="💵 Tárca", value=f"**{money(wallet)}**", inline=True)
        if stock is not None: embed.add_field(name="📊 Mai készlet", value=f"**{stock} db**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="use", aliases=["u", "open"])
    @commands.guild_only()
    async def use(self, ctx: commands.Context, item: str) -> None:
        try:
            label, reward, extra = await self.shop.use(ctx.guild.id, ctx.author.id, item)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        if reward:
            await ctx.send(embed=discord.Embed(title="📦 Láda kinyitva", description=f"Ritkaság: **{label}**\nJutalom: **{money(reward)}**\n{extra}", color=discord.Color.purple()))
        else:
            await ctx.send(embed=discord.Embed(title="⚡ Booster aktiválva", description=f"**{label}**\n{extra}", color=discord.Color.purple()))

    @commands.command(name="inventory", aliases=["inv", "bag"])
    @commands.guild_only()
    async def inventory(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        embed, view = await make_profile_view(self.bot, ctx.guild.id, target, ctx.author.id, initial_page="inventory")
        await ctx.send(embed=embed, view=view)

    @commands.command(name="jail", aliases=["j", "prison"])
    @commands.guild_only()
    async def jail(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        target = member or ctx.author
        until = await self.economy.jail_status(ctx.guild.id, target.id)
        embed = action_embed("🚔 Börtön státusz", ctx.author, color=DANGER if until else SUCCESS)
        embed.add_field(name="👤 Játékos", value=f"**{target.display_name}**", inline=True)
        embed.add_field(name="Állapot", value=(f"<t:{int(until.timestamp())}:R>" if until else "**Szabad**"), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="kincseslada", aliases=["lada", "chest"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def kincseslada(self, ctx: commands.Context, amount: str, join_seconds: int = 60) -> None:
        try:
            parsed_amount = parse_amount(amount)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        if parsed_amount < eco.EVENT_MIN_REWARD:
            return await ctx.send(embed=error_embed(ctx.author, f"A Kincses Láda minimum összege {money(eco.EVENT_MIN_REWARD)}."))
        if not eco.EVENT_JOIN_MIN_SECONDS <= join_seconds <= eco.EVENT_JOIN_MAX_SECONDS:
            return await ctx.send(embed=error_embed(ctx.author, f"A nevezési idő {eco.EVENT_JOIN_MIN_SECONDS}–{eco.EVENT_JOIN_MAX_SECONDS} másodperc lehet."))
        events = self.bot.get_cog("EventCog")
        if events is None:
            return await ctx.send("❌ Az event modul nem érhető el.")
        if ctx.guild.id in events.active_events:
            return await ctx.send("❌ Már fut egy event ezen a szerveren.")
        message = await events._post_safe(ctx.channel, ctx.guild.id, parsed_amount, join_seconds, ctx.author, False)
        if message is None:
            await ctx.send("❌ Nem sikerült elindítani.", delete_after=5)

    @commands.command(name="hirtelenhalal", aliases=["bomb", "hh", "sd"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def hirtelenhalal(self, ctx: commands.Context, belepo: str, join_seconds: int = 60, round_seconds: int = 15) -> None:
        try:
            entry_fee = parse_amount(belepo)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        if entry_fee < eco.BOMB_MIN_ENTRY:
            return await ctx.send(embed=error_embed(ctx.author, f"A Hirtelen Halál minimum belépője {money(eco.BOMB_MIN_ENTRY)}."))
        if not eco.EVENT_JOIN_MIN_SECONDS <= join_seconds <= eco.EVENT_JOIN_MAX_SECONDS:
            return await ctx.send(embed=error_embed(ctx.author, f"A nevezési idő {eco.EVENT_JOIN_MIN_SECONDS}–{eco.EVENT_JOIN_MAX_SECONDS} másodperc lehet."))
        if not eco.BOMB_ROUND_MIN_SECONDS <= round_seconds <= eco.BOMB_ROUND_MAX_SECONDS:
            return await ctx.send(embed=error_embed(ctx.author, f"A köridő {eco.BOMB_ROUND_MIN_SECONDS}–{eco.BOMB_ROUND_MAX_SECONDS} másodperc lehet."))
        events = self.bot.get_cog("EventCog")
        if events is None:
            return await ctx.send("❌ Az event modul nem érhető el.")
        if ctx.guild.id in events.active_events:
            return await ctx.send("❌ Már fut egy event ezen a szerveren.")
        message = await events._post_bomb(ctx.channel, ctx.guild.id, entry_fee, join_seconds, round_seconds, ctx.author, False)
        if message is None:
            await ctx.send("❌ Nem sikerült elindítani.", delete_after=5)

    async def _send_prefix_gamble(self, ctx: commands.Context, title: str, function, bet: int, *args) -> None:
        try:
            result = await function(ctx.guild.id, ctx.author.id, *args)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await ctx.send(embed=gambling_result_embed(
            title,
            ctx.author,
            result_text=result.display,
            bet=bet,
            profit=result.profit,
            wallet=result.wallet,
        ))

    @commands.command(name="coinflip", aliases=["cf"])
    @commands.guild_only()
    async def coinflip(self, ctx: commands.Context, first: str, second: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        choices = {"fej", "heads", "h", "iras", "írás", "tails", "t"}
        if first.lower() in choices:
            choice, bet = first, second
        elif second.lower() in choices:
            choice, bet = second, first
        else:
            return await ctx.send(embed=error_embed(ctx.author, "Használat: `!cf fej 100k` vagy `!cf 100k fej`."))
        try:
            parsed_bet = parse_amount(bet, wallet)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await self._send_prefix_gamble(ctx, "🪙 Coinflip", self.gambling.coinflip, parsed_bet, choice, parsed_bet)

    @commands.command(name="dice", aliases=["kocka", "roll"])
    @commands.guild_only()
    async def dice(self, ctx: commands.Context, first: str, second: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        guess = None
        bet = None
        try:
            candidate = int(first)
            if 1 <= candidate <= 6:
                guess, bet = candidate, second
        except ValueError:
            pass
        if guess is None:
            try:
                candidate = int(second)
                if 1 <= candidate <= 6:
                    guess, bet = candidate, first
            except ValueError:
                pass
        if guess is None or bet is None:
            return await ctx.send(embed=error_embed(ctx.author, "Használat: `!roll 4 100k` vagy `!roll 100k 4`."))
        try:
            parsed_bet = parse_amount(bet, wallet)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await self._send_prefix_gamble(ctx, "🎲 Kockajáték", self.gambling.dice, parsed_bet, guess, parsed_bet)

    @commands.command(name="slots", aliases=["slot", "sl"])
    @commands.guild_only()
    async def slots(self, ctx: commands.Context, bet: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed_bet = parse_amount(bet, wallet)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await self._send_prefix_gamble(ctx, "🎰 Slots", self.gambling.slots, parsed_bet, parsed_bet)

    @commands.command(name="roulette", aliases=["rulett", "r"])
    @commands.guild_only()
    async def roulette(self, ctx: commands.Context, first: str, second: str) -> None:
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        roulette_choices = {"piros", "red", "fekete", "black", "zold", "zöld", "green", "paros", "páros", "even", "paratlan", "páratlan", "odd", "alacsony", "low", "magas", "high"}
        def is_choice(value: str) -> bool:
            v = value.lower().strip()
            return v in roulette_choices or (v.isdigit() and 0 <= int(v) <= 36)
        if is_choice(first):
            choice, bet = first, second
        elif is_choice(second):
            choice, bet = second, first
        else:
            return await ctx.send(embed=error_embed(ctx.author, "Használat: `!roulette red 100k` vagy `!roulette 100k red`."))
        try:
            parsed_bet = parse_amount(bet, wallet)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        await self._send_prefix_gamble(ctx, "🎡 Roulette", self.gambling.roulette, parsed_bet, choice, parsed_bet)

    @commands.command(name="blackjack", aliases=["bj"])
    @commands.guild_only()
    async def blackjack(self, ctx: commands.Context, bet: str) -> None:
        cog = self.bot.get_cog("GamblingCog")
        if cog is None:
            return await ctx.send(embed=error_embed(ctx.author, "A gambling modul nem érhető el."))
        wallet, _ = await self.economy.balance(ctx.guild.id, ctx.author.id)
        try:
            parsed_bet = parse_amount(bet, wallet)
            view = await cog.start_blackjack(ctx.guild.id, ctx.author, parsed_bet)
        except ValueError as error:
            return await ctx.send(embed=error_embed(ctx.author, str(error)))
        view.message = await ctx.send(embed=view.embed(), view=view)
        if view.opening_is_finished():
            await view.finish(auto=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send(embed=error_embed(ctx.author, f"Hiányzó adat: `{error.param.name}`. Használd a `!help` parancsot."))
        if isinstance(error, commands.BadArgument):
            return await ctx.send(embed=error_embed(ctx.author, "Hibás paraméter. Ellenőrizd a parancs sorrendjét és az értékeket. Összegnél használhatsz ilyet is: `25k`, `2m`, `1b`, `1t`, `1q`, `all`."))
        raise error
