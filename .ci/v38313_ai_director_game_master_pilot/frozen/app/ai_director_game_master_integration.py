from __future__ import annotations

import logging
from collections.abc import Callable

from app.ai_director_game_master import AIDirectorGameMasterPacket

logger = logging.getLogger("yoru.ai_game_master.integration")
GAME_MASTER_FIELD_NAME = "🌙 Yoru Director • GM teszt"
GameMasterPacketSource = AIDirectorGameMasterPacket | Callable[[], AIDirectorGameMasterPacket]


async def add_game_master_field(bot, embed, guild_id: int | None, packet_source: GameMasterPacketSource) -> bool:
    """Append one bounded Tier-3 field; packet/provider failures never break the host panel."""
    pilot = getattr(bot, "ai_director_game_master", None)
    if pilot is None:
        return False
    try:
        packet = packet_source() if callable(packet_source) else packet_source
        value = await pilot.field_value(guild_id, packet)
    except Exception:
        logger.exception("Tier3 Game Master presentation failed closed")
        return False
    if not value:
        return False
    embed.add_field(name=GAME_MASTER_FIELD_NAME, value=value, inline=False)
    return True
