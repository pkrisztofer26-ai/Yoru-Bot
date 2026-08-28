from __future__ import annotations

"""W22.8 bounded rare-content Tier-3 rollout policy.

The policy expands presentation eligibility only. It never owns gameplay truth,
settlement, rewards, state or persistence. Eligibility is deterministic from the
validated packet digest; no user identifier is used for cohort selection.
"""

import hashlib
from dataclasses import dataclass

from app.ai_director_game_master import AIDirectorGameMasterPacket


ROLLOUT_CONTRACT_VERSION = "tier3-rare-content-rollout-v1"
ROLLOUT_ELIGIBLE_FAMILIES = frozenset({"world_story", "legendary_event"})
ROLLOUT_PERCENT_HARD_CAP = 10
ROLLOUT_PROVIDER_ATTEMPTS_PER_MINUTE = 4
ROLLOUT_BUCKETS = 10_000
ROLLOUT_COHORT_SALT = "yoru-w22.8-tier3-rare-content-v1"


@dataclass(frozen=True, slots=True)
class AIDirectorGameMasterRolloutDecision:
    eligible: bool
    reason: str
    bucket: int | None = None


@dataclass(frozen=True, slots=True)
class AIDirectorGameMasterRolloutPolicy:
    enabled: bool = False
    guild_id: int | None = None
    percent: int = 0

    def __post_init__(self) -> None:
        percent = int(self.percent)
        if percent < 0 or percent > ROLLOUT_PERCENT_HARD_CAP:
            raise ValueError(
                f"Tier-3 rollout percent must be between 0 and {ROLLOUT_PERCENT_HARD_CAP}."
            )
        if self.enabled and self.guild_id is None:
            raise ValueError("Enabled Tier-3 rollout requires one explicit rollout guild.")
        if self.enabled and percent <= 0:
            raise ValueError("Enabled Tier-3 rollout requires a positive rollout percent.")

    def guild_matches(self, guild_id: int | None) -> bool:
        return bool(
            self.enabled
            and self.guild_id is not None
            and guild_id is not None
            and int(guild_id) == int(self.guild_id)
        )

    @staticmethod
    def _bucket(packet: AIDirectorGameMasterPacket) -> int:
        raw = f"{ROLLOUT_COHORT_SALT}:{packet.digest()}".encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        return int.from_bytes(digest[:4], "big") % ROLLOUT_BUCKETS

    def decision(
        self,
        guild_id: int | None,
        packet: AIDirectorGameMasterPacket,
    ) -> AIDirectorGameMasterRolloutDecision:
        if not self.enabled:
            return AIDirectorGameMasterRolloutDecision(False, "rollout_disabled")
        if not self.guild_matches(guild_id):
            return AIDirectorGameMasterRolloutDecision(False, "wrong_rollout_guild")
        if packet.family not in ROLLOUT_ELIGIBLE_FAMILIES:
            return AIDirectorGameMasterRolloutDecision(False, "family_not_eligible")
        if self.percent <= 0:
            return AIDirectorGameMasterRolloutDecision(False, "zero_percent")

        bucket = self._bucket(packet)
        threshold = int(self.percent) * 100  # 1% == 100 of 10,000 buckets.
        return AIDirectorGameMasterRolloutDecision(
            bucket < threshold,
            "eligible" if bucket < threshold else "outside_content_cohort",
            bucket,
        )

    def public_status(self, *, paused: bool) -> dict[str, object]:
        """Anonymized owner-facing status; intentionally excludes guild IDs/content."""
        return {
            "contract": ROLLOUT_CONTRACT_VERSION,
            "enabled": bool(self.enabled),
            "paused": bool(paused),
            "guild_configured": self.guild_id is not None,
            "percent": int(self.percent),
            "hard_cap_percent": ROLLOUT_PERCENT_HARD_CAP,
            "eligible_families": sorted(ROLLOUT_ELIGIBLE_FAMILIES),
            "provider_attempts_per_minute_cap": ROLLOUT_PROVIDER_ATTEMPTS_PER_MINUTE,
            "cohort_basis": "content_hash_only",
            "personal_cohorting": False,
            "gameplay_authority": "NONE",
            "persistence": "NONE",
        }
