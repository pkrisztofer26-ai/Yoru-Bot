from __future__ import annotations

import discord

BRAND = discord.Color.from_rgb(116, 73, 255)
SUCCESS = discord.Color.from_rgb(46, 204, 113)
DANGER = discord.Color.from_rgb(231, 76, 60)
GOLD = discord.Color.from_rgb(241, 196, 15)
NEUTRAL = discord.Color.from_rgb(88, 101, 242)


def money(value: int) -> str:
    value = int(value)
    sign = "-" if value < 0 else ""
    return sign + "$" + f"{abs(value):,}".replace(",", " ")


def progress_bar(current: int, target: int, width: int = 10) -> str:
    if target <= 0:
        return "█" * width
    ratio = max(0.0, min(1.0, current / target))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


def base_embed(title: str, description: str | None = None, color: discord.Color = BRAND) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Yoru • Economy & Games")
    return embed


def player_embed(
    title: str,
    user: discord.abc.User,
    *,
    description: str | None = None,
    color: discord.Color = BRAND,
) -> discord.Embed:
    embed = base_embed(title, description, color)
    avatar = getattr(user.display_avatar, "url", None)
    embed.set_author(name=f"{user.display_name}", icon_url=avatar)
    return embed


def action_embed(
    title: str,
    user: discord.abc.User,
    *,
    description: str | None = None,
    color: discord.Color = BRAND,
    footer: str = "Yoru • Economy",
) -> discord.Embed:
    embed = player_embed(title, user, description=description, color=color)
    embed.set_footer(text=footer)
    return embed


def error_embed(user: discord.abc.User, message: str, *, title: str = "❌ Sikertelen művelet") -> discord.Embed:
    return action_embed(title, user, description=message, color=DANGER)


def cooldown_embed(user: discord.abc.User, label: str, ready_at) -> discord.Embed:
    return action_embed(
        "⏳ Cooldown",
        user,
        description=f"**{label}** újra elérhető: <t:{int(ready_at.timestamp())}:R>",
        color=GOLD,
    )


def gambling_result_embed(
    title: str,
    user: discord.abc.User,
    *,
    result_text: str,
    bet: int,
    profit: int,
    wallet: int,
) -> discord.Embed:
    if profit > 0:
        color = SUCCESS
        outcome = "✅ Győzelem"
        amount_text = f"+{money(profit)}"
    elif profit < 0:
        color = DANGER
        outcome = "❌ Vereség"
        amount_text = f"-{money(abs(profit))}"
    else:
        color = GOLD
        outcome = "🤝 Döntetlen"
        amount_text = money(0)

    embed = player_embed(title, user, color=color)
    embed.add_field(name="🎮 Eredmény", value=result_text, inline=False)
    payout = max(0, bet + profit)
    embed.add_field(name="🎟️ Tét", value=f"**{money(bet)}**", inline=True)
    embed.add_field(name=outcome, value=f"**{amount_text}**", inline=True)
    embed.add_field(name="💵 Kifizetés", value=f"**{money(payout)}**", inline=True)
    embed.add_field(name="💰 Egyenleg", value=f"**{money(wallet)}**", inline=False)
    embed.set_footer(text="Yoru • Gambling")
    return embed
