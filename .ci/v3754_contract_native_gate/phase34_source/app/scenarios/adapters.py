from __future__ import annotations

from collections.abc import Iterable

from app.job_framework import DecisionScenario as LegacyDecisionScenario
from app.job_framework import ScenarioChoice as LegacyScenarioChoice
from app.scenarios.models import ScenarioChoice, ScenarioDefinition, ScenarioRarity


def choice_from_legacy(choice: LegacyScenarioChoice) -> ScenarioChoice:
    return ScenarioChoice(
        key=choice.key,
        label=choice.label,
        emoji=choice.emoji,
        description=choice.description,
        success_chance=choice.success_chance,
        reward_success=choice.reward_success,
        reward_fail=choice.reward_fail,
        score_success=choice.score_success,
        score_fail=choice.score_fail,
        continue_on_success=choice.continue_on_success,
        continue_on_fail=choice.continue_on_fail,
        default=choice.default,
    )


def definition_from_legacy(
    scenario: LegacyDecisionScenario,
    *,
    family: str,
    domain: str,
    tags: Iterable[str] = (),
    semantic_key: str | None = None,
    rarity: ScenarioRarity = ScenarioRarity.COMMON,
    metadata: dict | None = None,
) -> ScenarioDefinition:
    return ScenarioDefinition(
        key=scenario.key,
        family=family,
        domain=domain,
        title=scenario.title,
        prompt=scenario.prompt,
        choices=tuple(choice_from_legacy(choice) for choice in scenario.choices),
        rarity=rarity,
        tags=tuple(tags),
        semantic_key=semantic_key or scenario.key,
        source="deterministic",
        metadata=dict(metadata or {}),
    )


def passive_definition(
    *,
    key: str,
    family: str,
    domain: str,
    title: str,
    prompt: str,
    tags: Iterable[str] = (),
    semantic_key: str | None = None,
    metadata: dict | None = None,
) -> ScenarioDefinition:
    """Adapt a legacy one-shot/static outcome into the common scenario catalog.

    The synthetic `complete` choice has no payout authority.  Work keeps using
    EconomyService's existing reward range and settlement logic.
    """
    return ScenarioDefinition(
        key=key,
        family=family,
        domain=domain,
        title=title,
        prompt=prompt,
        choices=(ScenarioChoice(key="complete", label="Folytatás", success_chance=1.0, default=True),),
        tags=tuple(tags),
        semantic_key=semantic_key or key,
        source="deterministic",
        metadata=dict(metadata or {}),
    )
