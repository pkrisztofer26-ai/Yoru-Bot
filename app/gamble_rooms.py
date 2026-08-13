from __future__ import annotations

import re
import unicodedata

import discord

GAMBLE_ROOM_TOPIC_PREFIX = "YORU_GAMBLE_ROOM"


def make_gamble_room_topic(owner_id: int, panel_channel_id: int | None = None) -> str:
    panel = int(panel_channel_id or 0)
    return f"{GAMBLE_ROOM_TOPIC_PREFIX}|owner={int(owner_id)}|panel={panel}"


def gamble_room_owner(channel: object) -> int | None:
    topic = getattr(channel, "topic", None)
    if not isinstance(topic, str) or not topic.startswith(GAMBLE_ROOM_TOPIC_PREFIX + "|"):
        return None
    match = re.search(r"(?:^|\|)owner=(\d+)(?:\||$)", topic)
    return int(match.group(1)) if match else None


def is_gamble_room(channel: object) -> bool:
    return gamble_room_owner(channel) is not None


def gamble_room_name(display_name: str, user_id: int) -> str:
    normalized = unicodedata.normalize("NFKD", display_name or "")
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    if not slug:
        slug = f"player-{int(user_id) % 10000:04d}"
    return f"gamble-{slug}"[:90].rstrip("-")


def private_room_overwrites(guild: discord.Guild, member: discord.Member) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            use_application_commands=True,
        ),
    }
    me = guild.me
    if me is not None:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            use_application_commands=True,
        )
    return overwrites
