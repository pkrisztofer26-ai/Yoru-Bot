from __future__ import annotations

"""Pure domain contracts for Scenario Engine V2.

This module deliberately owns no Discord objects and performs no economy/state
mutation.  Scenario resolution produces validated *intent/outcome data*; the
calling domain service remains authoritative for wallet, inventory, cooldown,
XP, police/world state and every other gameplay mutation.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class ScenarioRarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    ULTRA_RARE = "ultra_rare"


class OutcomeTier(StrEnum):
    CRITICAL_FAIL = "critical_fail"
    FAIL = "fail"
    SUCCESS = "success"
    CRITICAL_SUCCESS = "critical_success"


class ScenarioRunStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ScenarioModifier:
    """Deterministic modifier contract.

    Modifiers may shape a scenario roll/outcome but never mutate authoritative
    game state themselves.  Payout services may choose to consume the returned
    reward multiplier after their own validation.
    """

    key: str
    chance_multiplier: float = 1.0
    chance_add: float = 0.0
    reward_multiplier: float = 1.0
    score_add_success: int = 0
    score_add_fail: int = 0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioChoice:
    key: str
    label: str
    emoji: str = ""
    description: str = ""
    success_chance: float = 1.0
    reward_success: float = 1.0
    reward_fail: float = 0.65
    score_success: int = 0
    score_fail: int = -8
    continue_on_success: bool = True
    continue_on_fail: bool = True
    default: bool = False
    next_on_success: str | None = None
    next_on_fail: str | None = None

    def normalized_chance(self) -> float:
        return max(0.0, min(1.0, float(self.success_chance)))


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    key: str
    family: str
    domain: str
    title: str
    prompt: str
    choices: tuple[ScenarioChoice, ...]
    rarity: ScenarioRarity = ScenarioRarity.COMMON
    tags: tuple[str, ...] = ()
    semantic_key: str | None = None
    version: int = 1
    enabled: bool = True
    source: str = "deterministic"
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    def choice(self, key: str) -> ScenarioChoice:
        for item in self.choices:
            if item.key == key:
                return item
        raise ValueError("Ismeretlen scenario döntés.")

    def default_choice(self) -> ScenarioChoice:
        for item in self.choices:
            if item.default:
                return item
        return self.choices[0]

    @property
    def topic_key(self) -> str:
        return str(self.semantic_key or self.key)


@dataclass(frozen=True, slots=True)
class ScenarioContext:
    guild_id: int
    user_id: int
    domain: str
    family: str
    city_key: str | None = None
    tags: tuple[str, ...] = ()
    values: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario_key: str
    family: str
    choice_key: str
    success: bool
    tier: OutcomeTier
    effective_chance: float
    roll: float
    reward_multiplier: float
    score_delta: int
    continue_run: bool
    next_scenario_key: str | None = None
    timeout: bool = False
    applied_modifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioRunState:
    run_id: str
    guild_id: int
    user_id: int
    domain: str
    family: str
    scenario_key: str
    current_node: str
    source: str
    status: ScenarioRunStatus
    state: Mapping[str, Any]
    created_at: str
    updated_at: str
    expires_at: str | None = None
