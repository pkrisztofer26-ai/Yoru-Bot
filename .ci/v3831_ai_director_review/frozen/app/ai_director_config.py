from __future__ import annotations

"""Phase 12 AI Director production rollout configuration.

The production runtime is deliberately OFF by default.  Phase 12 starts with a
cached/non-player surface layer; AI never owns gameplay mechanics, outcomes or
state mutation.
"""

AI_DIRECTOR_CONTRACT_VERSION = "tier1-cached-surface-v3"
AI_DIRECTOR_RUNTIME_ENABLED_DEFAULT = False
AI_DIRECTOR_CACHE_TTL_SECONDS = 6 * 60 * 60
AI_DIRECTOR_BATCH_LIMIT = 32
AI_DIRECTOR_TITLE_MAX = 120
AI_DIRECTOR_DESCRIPTION_MAX = 700

# Phase 12 roadmap Tier 1 only.  Tier 2/3 must be introduced by later gates.
AI_DIRECTOR_TIER1_FAMILIES = frozenset({
    "work",
    "crime",
    "search",
    "beg",
    "career",
})

# Provider output is a narrative surface only.  These names must never be
# accepted as provider-owned fields even if an upstream model returns them.
AI_DIRECTOR_FORBIDDEN_FIELDS = frozenset({
    "amount", "reward", "payout", "money", "wallet", "bank", "xp",
    "inventory", "item", "items", "cooldown", "chance", "probability",
    "roll", "rng", "success", "failed", "outcome", "state", "mutation",
    "permission", "admin", "police", "heat", "settlement", "choices",
    "choice", "branch", "mechanical_intent", "requirements",
})
