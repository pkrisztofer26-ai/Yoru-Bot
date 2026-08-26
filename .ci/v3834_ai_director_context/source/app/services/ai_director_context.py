from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.ai_director_context import (
    AIDirectorContextPacket,
    AIDirectorContextSurface,
    fallback_context_surface,
    validate_context_packet,
    validate_context_surface,
)

logger = logging.getLogger("yoru.ai_context")


class AIDirectorContextProvider(Protocol):
    async def generate_context(self, packet: AIDirectorContextPacket) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AIDirectorContextPolicy:
    enabled: bool = False
    test_guild_id: int | None = None

    def active_for_guild(self, guild_id: int | None) -> bool:
        return bool(
            self.enabled and self.test_guild_id is not None and guild_id is not None
            and int(guild_id) == int(self.test_guild_id)
        )


class AIDirectorContextPilot:
    """Fail-closed Tier 2 test-guild presentation service.

    Accepted provider text is held in a short in-memory cache. Nothing here can
    mutate domain state. Provider failure, timeout or validation failure returns
    the deterministic host fallback after canonical state has already been read
    or settled by the owning domain.
    """

    def __init__(
        self,
        *,
        provider: AIDirectorContextProvider | None = None,
        enabled: bool = False,
        test_guild_id: int | None = None,
        timeout_seconds: float = 8.0,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.provider = provider
        self.policy = AIDirectorContextPolicy(bool(enabled), test_guild_id)
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 15.0))
        self.cache_ttl_seconds = max(30.0, min(float(cache_ttl_seconds), 1800.0))
        self._cache: dict[str, tuple[float, AIDirectorContextSurface]] = {}
        self._provider_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.policy.enabled

    def active_for_guild(self, guild_id: int | None) -> bool:
        return self.policy.active_for_guild(guild_id)

    async def surface(
        self, guild_id: int | None, user_id: int | None, packet: AIDirectorContextPacket
    ) -> AIDirectorContextSurface | None:
        validate_context_packet(packet)
        if not self.active_for_guild(guild_id):
            return None
        fallback = fallback_context_surface(packet)
        if self.provider is None:
            return fallback
        cache_key = packet.digest()
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            value = cached[1]
            return AIDirectorContextSurface(
                context_key=value.context_key, domain=value.domain, title=value.title,
                description=value.description, source="ai_context_cache",
                packet_digest=value.packet_digest, contract_version=value.contract_version,
            )
        try:
            # The pilot is intentionally serialized in the single test guild so
            # bursts cannot fan out provider calls. Core gameplay never waits on
            # this lock because only read-only/post-settlement presentation paths call it.
            async with self._provider_lock:
                raw = await asyncio.wait_for(
                    self.provider.generate_context(packet), timeout=self.timeout_seconds
                )
            title, description = validate_context_surface(packet, raw)
            surface = AIDirectorContextSurface(
                context_key=packet.context_key, domain=packet.domain, title=title,
                description=description, source="ai_context", packet_digest=cache_key,
                contract_version=packet.contract_version,
            )
            self._cache[cache_key] = (time.monotonic() + self.cache_ttl_seconds, surface)
            if len(self._cache) > 256:
                self._cache = {key: value for key, value in self._cache.items() if value[0] > time.monotonic()}
            return surface
        except Exception as exc:
            logger.warning(
                "Tier2 context fallback guild=%s user=%s domain=%s key=%s error=%s",
                guild_id, user_id, packet.domain, packet.context_key, type(exc).__name__,
            )
            return fallback

    async def field_value(
        self, guild_id: int | None, user_id: int | None, packet: AIDirectorContextPacket
    ) -> str | None:
        surface = await self.surface(guild_id, user_id, packet)
        if surface is None:
            return None
        return f"**{surface.title}**\n{surface.description}"[:1024]
