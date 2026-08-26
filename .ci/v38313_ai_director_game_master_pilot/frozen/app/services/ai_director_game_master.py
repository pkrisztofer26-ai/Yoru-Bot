from __future__ import annotations

import asyncio
import logging
import time
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
    """W22.6 fail-closed Tier 3 test-guild presentation service.

    Only explicit TEST_GUILD_ID opt-in call-sites may request a surface. Provider
    timeout, validation failure or packet rejection never changes host-owned state;
    presentation falls back to deterministic Scenario Engine text.
    """

    def __init__(
        self,
        *,
        provider: AIDirectorGameMasterProvider | None = None,
        enabled: bool = False,
        test_guild_id: int | None = None,
        timeout_seconds: float = 8.0,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.provider = provider
        self.policy = AIDirectorGameMasterPolicy(bool(enabled), test_guild_id)
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 15.0))
        self.cache_ttl_seconds = max(30.0, min(float(cache_ttl_seconds), 1800.0))
        self._cache: dict[str, tuple[float, AIDirectorGameMasterSurface]] = {}
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
        cache_key = packet.digest()
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            value = cached[1]
            return AIDirectorGameMasterSurface(
                story_key=value.story_key, family=value.family, title=value.title,
                description=value.description, source="ai_game_master_cache",
                packet_digest=value.packet_digest, contract_version=value.contract_version,
            )
        try:
            async with self._provider_lock:
                raw = await asyncio.wait_for(self.provider.generate_game_master(packet), timeout=self.timeout_seconds)
            title, description = validate_game_master_surface(packet, raw)
            surface = AIDirectorGameMasterSurface(
                story_key=packet.story_key,
                family=packet.family,
                title=title,
                description=description,
                source="ai_game_master",
                packet_digest=cache_key,
                contract_version=packet.contract_version,
            )
            self._cache[cache_key] = (time.monotonic() + self.cache_ttl_seconds, surface)
            if len(self._cache) > 128:
                cutoff = time.monotonic()
                self._cache = {key: value for key, value in self._cache.items() if value[0] > cutoff}
            return surface
        except Exception as exc:
            logger.warning("Tier3 Game Master fallback guild=%s family=%s key=%s error=%s", guild_id, packet.family, packet.story_key, type(exc).__name__)
            return fallback

    async def field_value(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> str | None:
        surface = await self.surface(guild_id, packet)
        if surface is None:
            return None
        return f"**{surface.title}**\n{surface.description}"[:1024]
