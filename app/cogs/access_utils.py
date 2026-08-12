from __future__ import annotations

import discord
from discord.ext import commands

from app.ui import error_embed


async def handle_wrong_economy_channel(
    ctx: commands.Context,
    economy,
    *,
    kind: str = "economy",
) -> None:
    """Delete a misplaced prefix economy/gambling command and notify privately.

    Call this only after the feature-enabled check has passed and the configured
    economy location allowlist rejected the current channel/category.
    """
    if ctx.guild is None:
        return

    channels = await economy.guild_settings.get_economy_channel_ids(ctx.guild.id)
    categories = await economy.guild_settings.get_economy_category_ids(ctx.guild.id)

    locations: list[str] = []
    for channel_id in channels[:12]:
        channel = ctx.guild.get_channel(channel_id)
        locations.append(channel.mention if isinstance(channel, discord.abc.GuildChannel) else f"<#{channel_id}>")
    for category_id in categories[:12]:
        category = ctx.guild.get_channel(category_id)
        if isinstance(category, discord.CategoryChannel):
            locations.append(f"**{category.name}** kategória")
        else:
            locations.append(f"<#{category_id}> kategória")

    if not locations:
        where = "a szerveren engedélyezett economy helyen"
    else:
        where = ", ".join(locations[:12])
        extra = len(channels) + len(categories) - min(len(locations), 12)
        if extra > 0:
            where += f" +{extra} további"

    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass

    is_gambling = kind.lower() == "gambling"
    label = "gambling" if is_gambling else "economy"
    title = "🎰 Gambling csatorna" if is_gambling else "💰 Economy csatorna"
    message = f"A {label} parancsokat csak itt használhatod: {where}."
    try:
        await ctx.author.send(embed=error_embed(ctx.author, message, title=title))
    except (discord.Forbidden, discord.HTTPException):
        # Prefix commands cannot be ephemeral. If DMs are closed, keep the
        # fallback short-lived so General still does not get polluted.
        try:
            await ctx.send(
                f"{ctx.author.mention} ❌ {message}",
                delete_after=8,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass


async def handle_wrong_gambling_channel(ctx: commands.Context, economy) -> None:
    """Backwards-compatible wrapper for the gambling-specific cleanup path."""
    await handle_wrong_economy_channel(ctx, economy, kind="gambling")
