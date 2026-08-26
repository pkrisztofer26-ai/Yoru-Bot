from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.ai_director_game_master import (
    AIDirectorGameMasterPacket,
    AIDirectorGameMasterSurface,
    fallback_game_master_surface,
    validate_game_master_packet,
    validate_game_master_surface,
)

logger = logging.getLogger("yoru.ai_game_master")


class AIDirectorGameMasterProvider(Protocol):
    async def generate_game_master(self, packet: AIDirectorGameMasterPacket) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AIDirectorGameMasterPolicy:
    enabled: bool = False
    test_guild_id: int | None = None

    def active_for_guild(self, guild_id: int | None) -> bool:
        return bool(self.enabled and self.test_guild_id is not None and guild_id is not None and int(guild_id) == int(self.test_guild_id))


class AIDirectorGameMaster:
    """W22.5 fail-closed Tier 3 runtime shell.

    W22.5 has no player-facing integration.  This service exists so provider,
    timeout and fallback semantics can be proven before any live story call-site
    is allowed to depend on it.
    """

    def __init__(
        self,
        *,
        provider: AIDirectorGameMasterProvider | None = None,
        enabled: bool = False,
        test_guild_id: int | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.provider = provider
        self.policy = AIDirectorGameMasterPolicy(bool(enabled), test_guild_id)
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 15.0))
        self._provider_lock = asyncio.Lock()

    def active_for_guild(self, guild_id: int | None) -> bool:
        return self.policy.active_for_guild(guild_id)

    async def surface(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> AIDirectorGameMasterSurface | None:
        validate_game_master_packet(packet)
        if not self.active_for_guild(guild_id):
            return None
        fallback = fallback_game_master_surface(packet)
        if self.provider is None:
            return fallback
        try:
            async with self._provider_lock:
                raw = await asyncio.wait_for(self.provider.generate_game_master(packet), timeout=self.timeout_seconds)
            title, description = validate_game_master_surface(packet, raw)
            return AIDirectorGameMasterSurface(
                story_key=packet.story_key,
                family=packet.family,
                title=title,
                description=description,
                source="ai_game_master",
                packet_digest=packet.digest(),
                contract_version=packet.contract_version,
            )
        except Exception as exc:
            logger.warning("Tier3 Game Master fallback guild=%s family=%s key=%s error=%s", guild_id, packet.family, packet.story_key, type(exc).__name__)
            return fallback
