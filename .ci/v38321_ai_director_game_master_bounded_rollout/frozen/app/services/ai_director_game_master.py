from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.ai_director_game_master import (
    AIDirectorGameMasterPacket,
    AIDirectorGameMasterSurface,
    AIDirectorGameMasterValidationError,
    fallback_game_master_surface,
    validate_game_master_packet,
    validate_game_master_surface,
)
from app.ai_director_game_master_rollout import (
    AIDirectorGameMasterRolloutPolicy,
    ROLLOUT_PROVIDER_ATTEMPTS_PER_MINUTE,
)

logger = logging.getLogger("yoru.ai_game_master")


class AIDirectorGameMasterProvider(Protocol):
    async def generate_game_master(self, packet: AIDirectorGameMasterPacket) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AIDirectorGameMasterPolicy:
    enabled: bool = False
    test_guild_id: int | None = None

    def active_for_guild(self, guild_id: int | None) -> bool:
        return bool(
            self.enabled
            and self.test_guild_id is not None
            and guild_id is not None
            and int(guild_id) == int(self.test_guild_id)
        )


@dataclass(frozen=True, slots=True)
class AIDirectorGameMasterObservationSnapshot:
    requests_total: int
    inactive_skips: int
    packet_rejections: int
    provider_unavailable: int
    provider_attempts: int
    provider_failures: int
    provider_rate_limits: int
    provider_timeouts: int
    output_validation_failures: int
    ai_surfaces: int
    cache_hits: int
    deterministic_fallbacks: int
    fields_added: int
    presentation_skips: int
    integration_failures: int
    rollout_requests: int
    rollout_eligible: int
    rollout_ineligible: int
    rollout_paused_skips: int
    rollout_budget_skips: int
    rollout_ai_surfaces: int
    rollout_cache_hits: int
    rollout_fallbacks: int
    rollout_fields_added: int
    family_requests: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests_total": self.requests_total,
            "inactive_skips": self.inactive_skips,
            "packet_rejections": self.packet_rejections,
            "provider_unavailable": self.provider_unavailable,
            "provider_attempts": self.provider_attempts,
            "provider_failures": self.provider_failures,
            "provider_rate_limits": self.provider_rate_limits,
            "provider_timeouts": self.provider_timeouts,
            "output_validation_failures": self.output_validation_failures,
            "ai_surfaces": self.ai_surfaces,
            "cache_hits": self.cache_hits,
            "deterministic_fallbacks": self.deterministic_fallbacks,
            "fields_added": self.fields_added,
            "presentation_skips": self.presentation_skips,
            "integration_failures": self.integration_failures,
            "rollout_requests": self.rollout_requests,
            "rollout_eligible": self.rollout_eligible,
            "rollout_ineligible": self.rollout_ineligible,
            "rollout_paused_skips": self.rollout_paused_skips,
            "rollout_budget_skips": self.rollout_budget_skips,
            "rollout_ai_surfaces": self.rollout_ai_surfaces,
            "rollout_cache_hits": self.rollout_cache_hits,
            "rollout_fallbacks": self.rollout_fallbacks,
            "rollout_fields_added": self.rollout_fields_added,
            "family_requests": dict(self.family_requests),
        }


class AIDirectorGameMaster:
    """Fail-closed Tier-3 presentation service with a bounded W22.8 rollout gate.

    The already-certified test-guild pilot remains full-scope for all six Tier-3
    families. W22.8 optionally adds one explicit rollout guild, only the locked
    rare-content families, a deterministic packet-digest cohort capped at 10%,
    an in-memory provider budget, and an owner-controlled runtime pause. None of
    these paths own gameplay state or persistence.
    """

    def __init__(
        self,
        *,
        provider: AIDirectorGameMasterProvider | None = None,
        enabled: bool = False,
        test_guild_id: int | None = None,
        rollout_enabled: bool = False,
        rollout_guild_id: int | None = None,
        rollout_percent: int = 0,
        timeout_seconds: float = 8.0,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.provider = provider
        self.policy = AIDirectorGameMasterPolicy(bool(enabled), test_guild_id)
        self.rollout_policy = AIDirectorGameMasterRolloutPolicy(
            bool(rollout_enabled), rollout_guild_id, int(rollout_percent)
        )
        self.timeout_seconds = max(2.0, min(float(timeout_seconds), 15.0))
        self.cache_ttl_seconds = max(30.0, min(float(cache_ttl_seconds), 1800.0))
        self._cache: dict[str, tuple[float, AIDirectorGameMasterSurface]] = {}
        self._provider_lock = asyncio.Lock()
        self._rollout_paused = False
        self._rollout_provider_attempt_times: deque[float] = deque()
        self._observation: dict[str, int] = {
            "requests_total": 0,
            "inactive_skips": 0,
            "packet_rejections": 0,
            "provider_unavailable": 0,
            "provider_attempts": 0,
            "provider_failures": 0,
            "provider_rate_limits": 0,
            "provider_timeouts": 0,
            "output_validation_failures": 0,
            "ai_surfaces": 0,
            "cache_hits": 0,
            "deterministic_fallbacks": 0,
            "fields_added": 0,
            "presentation_skips": 0,
            "integration_failures": 0,
            "rollout_requests": 0,
            "rollout_eligible": 0,
            "rollout_ineligible": 0,
            "rollout_paused_skips": 0,
            "rollout_budget_skips": 0,
            "rollout_ai_surfaces": 0,
            "rollout_cache_hits": 0,
            "rollout_fallbacks": 0,
            "rollout_fields_added": 0,
        }
        self._family_requests: dict[str, int] = {}

    # Backward-compatible meaning: this is the isolated test-pilot check only.
    # /gmpilotprobe must never become runnable merely because broader rollout is on.
    def active_for_guild(self, guild_id: int | None) -> bool:
        return self.policy.active_for_guild(guild_id)

    def rollout_active_for_guild(self, guild_id: int | None) -> bool:
        return bool(self.rollout_policy.guild_matches(guild_id) and not self._rollout_paused)

    def rollout_eligible_for_packet(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> bool:
        if self._rollout_paused:
            return False
        return self.rollout_policy.decision(guild_id, packet).eligible

    def rollout_status(self) -> dict[str, object]:
        status = self.rollout_policy.public_status(paused=self._rollout_paused)
        observation = self.observation_snapshot().as_dict()
        status["observation"] = {
            key: observation[key]
            for key in (
                "rollout_requests",
                "rollout_eligible",
                "rollout_ineligible",
                "rollout_paused_skips",
                "rollout_budget_skips",
                "rollout_ai_surfaces",
                "rollout_cache_hits",
                "rollout_fallbacks",
                "rollout_fields_added",
            )
        }
        return status

    def pause_rollout(self) -> bool:
        changed = not self._rollout_paused
        self._rollout_paused = True
        return changed

    def resume_rollout(self) -> bool:
        if not self.rollout_policy.enabled:
            return False
        changed = self._rollout_paused
        self._rollout_paused = False
        return changed

    def _record(self, key: str, family: str | None = None) -> None:
        if key in self._observation:
            self._observation[key] += 1
        if key == "requests_total" and family:
            self._family_requests[family] = self._family_requests.get(family, 0) + 1

    def observation_snapshot(self) -> AIDirectorGameMasterObservationSnapshot:
        return AIDirectorGameMasterObservationSnapshot(
            **self._observation,
            family_requests=tuple(sorted(self._family_requests.items())),
        )

    def reset_observation(self, *, clear_cache: bool = False) -> None:
        for key in self._observation:
            self._observation[key] = 0
        self._family_requests.clear()
        self._rollout_provider_attempt_times.clear()
        if clear_cache:
            self._cache.clear()

    def note_presentation_result(
        self,
        *,
        added: bool = False,
        integration_failure: bool = False,
        rollout: bool = False,
    ) -> None:
        if added:
            self._record("fields_added")
            if rollout:
                self._record("rollout_fields_added")
        else:
            self._record("presentation_skips")
        if integration_failure:
            self._record("integration_failures")

    def presentation_field_name(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> str:
        if self.active_for_guild(guild_id):
            return "🌙 Yoru Director • GM teszt"
        if self.rollout_eligible_for_packet(guild_id, packet):
            return "🌙 Yoru Director"
        return "🌙 Yoru Director • GM teszt"

    def _consume_rollout_provider_budget(self, now: float) -> bool:
        cutoff = now - 60.0
        while self._rollout_provider_attempt_times and self._rollout_provider_attempt_times[0] <= cutoff:
            self._rollout_provider_attempt_times.popleft()
        if len(self._rollout_provider_attempt_times) >= ROLLOUT_PROVIDER_ATTEMPTS_PER_MINUTE:
            return False
        self._rollout_provider_attempt_times.append(now)
        return True

    def _route(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> str | None:
        if self.active_for_guild(guild_id):
            return "pilot"

        decision = self.rollout_policy.decision(guild_id, packet)
        if self.rollout_policy.guild_matches(guild_id):
            self._record("rollout_requests")
            if self._rollout_paused:
                self._record("rollout_paused_skips")
                return None
            if decision.eligible:
                self._record("rollout_eligible")
                return "rollout"
            self._record("rollout_ineligible")
        return None

    async def surface(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> AIDirectorGameMasterSurface | None:
        family = getattr(packet, "family", None)
        self._record("requests_total", str(family) if family else None)
        try:
            validate_game_master_packet(packet)
        except Exception:
            self._record("packet_rejections")
            raise

        route = self._route(guild_id, packet)
        if route is None:
            self._record("inactive_skips")
            return None

        is_rollout = route == "rollout"
        fallback = fallback_game_master_surface(packet)
        if self.provider is None:
            self._record("provider_unavailable")
            self._record("deterministic_fallbacks")
            if is_rollout:
                self._record("rollout_fallbacks")
            return fallback

        cache_key = packet.digest()
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            self._record("cache_hits")
            if is_rollout:
                self._record("rollout_cache_hits")
            value = cached[1]
            return AIDirectorGameMasterSurface(
                story_key=value.story_key,
                family=value.family,
                title=value.title,
                description=value.description,
                source="ai_game_master_rollout_cache" if is_rollout else "ai_game_master_cache",
                packet_digest=value.packet_digest,
                contract_version=value.contract_version,
            )

        if is_rollout and not self._consume_rollout_provider_budget(now):
            self._record("rollout_budget_skips")
            self._record("deterministic_fallbacks")
            self._record("rollout_fallbacks")
            return fallback

        self._record("provider_attempts")
        try:
            async with self._provider_lock:
                raw = await asyncio.wait_for(
                    self.provider.generate_game_master(packet),
                    timeout=self.timeout_seconds,
                )
            title, description = validate_game_master_surface(packet, raw)
            self._record("ai_surfaces")
            if is_rollout:
                self._record("rollout_ai_surfaces")
            surface = AIDirectorGameMasterSurface(
                story_key=packet.story_key,
                family=packet.family,
                title=title,
                description=description,
                source="ai_game_master_rollout" if is_rollout else "ai_game_master",
                packet_digest=cache_key,
                contract_version=packet.contract_version,
            )
            self._cache[cache_key] = (time.monotonic() + self.cache_ttl_seconds, surface)
            if len(self._cache) > 128:
                cutoff = time.monotonic()
                self._cache = {key: value for key, value in self._cache.items() if value[0] > cutoff}
            return surface
        except asyncio.TimeoutError as exc:
            self._record("provider_timeouts")
            self._record("deterministic_fallbacks")
            if is_rollout:
                self._record("rollout_fallbacks")
            logger.warning(
                "Tier3 Game Master timeout fallback guild=%s family=%s key=%s error=%s",
                guild_id,
                packet.family,
                packet.story_key,
                type(exc).__name__,
            )
            return fallback
        except AIDirectorGameMasterValidationError as exc:
            self._record("output_validation_failures")
            self._record("deterministic_fallbacks")
            if is_rollout:
                self._record("rollout_fallbacks")
            logger.warning(
                "Tier3 Game Master validation fallback guild=%s family=%s key=%s error=%s",
                guild_id,
                packet.family,
                packet.story_key,
                type(exc).__name__,
            )
            return fallback
        except Exception as exc:
            self._record("provider_failures")
            error_text = str(exc).casefold()
            error_name = type(exc).__name__.casefold()
            is_rate_limit = (
                "ratelimit" in error_name
                or "dailytokenlimit" in error_name
                or "groq http 429" in error_text
                or "too many requests" in error_text
                or "(tpm)" in error_text
                or "(tpd)" in error_text
            )
            if is_rate_limit:
                self._record("provider_rate_limits")
            self._record("deterministic_fallbacks")
            if is_rollout:
                self._record("rollout_fallbacks")
            logger.warning(
                "Tier3 Game Master fallback guild=%s family=%s key=%s error=%s rate_limit=%s",
                guild_id,
                packet.family,
                packet.story_key,
                type(exc).__name__,
                is_rate_limit,
            )
            return fallback

    async def field_value(self, guild_id: int | None, packet: AIDirectorGameMasterPacket) -> str | None:
        surface = await self.surface(guild_id, packet)
        if surface is None:
            return None
        return f"**{surface.title}**\n{surface.description}"[:1024]
