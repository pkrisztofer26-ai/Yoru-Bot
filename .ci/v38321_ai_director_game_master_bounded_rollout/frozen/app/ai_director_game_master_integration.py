from __future__ import annotations

import logging
from collections.abc import Callable

from app.ai_director_game_master import AIDirectorGameMasterPacket

logger = logging.getLogger("yoru.ai_game_master.integration")
GAME_MASTER_FIELD_NAME = "🌙 Yoru Director • GM teszt"
ROLLOUT_GAME_MASTER_FIELD_NAME = "🌙 Yoru Director"
GameMasterPacketSource = AIDirectorGameMasterPacket | Callable[[], AIDirectorGameMasterPacket]


async def add_game_master_field(bot, embed, guild_id: int | None, packet_source: GameMasterPacketSource) -> bool:
    """Append one bounded Tier-3 field; every presentation failure stays outside host authority."""
    pilot = getattr(bot, "ai_director_game_master", None)
    if pilot is None:
        return False
    packet = None
    rollout = False
    try:
        packet = packet_source() if callable(packet_source) else packet_source
        value = await pilot.field_value(guild_id, packet)
        if not value:
            pilot.note_presentation_result(added=False)
            return False
        rollout = bool(pilot.rollout_eligible_for_packet(guild_id, packet))
        field_name = pilot.presentation_field_name(guild_id, packet)
        embed.add_field(name=field_name, value=value, inline=False)
        pilot.note_presentation_result(added=True, rollout=rollout)
        return True
    except Exception:
        try:
            pilot.note_presentation_result(added=False, integration_failure=True, rollout=rollout)
        except Exception:
            pass
        logger.exception("Tier3 Game Master presentation failed closed")
        return False
