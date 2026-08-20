from __future__ import annotations

import math
import re

from app.scenarios.models import ScenarioChoice, ScenarioDefinition, ScenarioModifier

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")


class ScenarioValidationError(ValueError):
    pass


def _key(value: str, label: str) -> None:
    if not _KEY_RE.fullmatch(str(value or "")):
        raise ScenarioValidationError(f"Érvénytelen {label}: {value!r}")


def validate_modifier(modifier: ScenarioModifier) -> ScenarioModifier:
    _key(modifier.key, "modifier kulcs")
    for name, value, low, high in (
        ("chance_multiplier", modifier.chance_multiplier, 0.0, 3.0),
        ("chance_add", modifier.chance_add, -1.0, 1.0),
        ("reward_multiplier", modifier.reward_multiplier, 0.0, 3.0),
    ):
        numeric = float(value)
        if not math.isfinite(numeric) or not low <= numeric <= high:
            raise ScenarioValidationError(f"Érvénytelen modifier {name}: {value!r}")
    if not -100 <= int(modifier.score_add_success) <= 100:
        raise ScenarioValidationError("A modifier success score tartománya hibás.")
    if not -100 <= int(modifier.score_add_fail) <= 100:
        raise ScenarioValidationError("A modifier fail score tartománya hibás.")
    if len(modifier.tags) > 16:
        raise ScenarioValidationError("Túl sok modifier tag.")
    for tag in modifier.tags:
        _key(tag, "modifier tag")
    return modifier


def validate_choice(choice: ScenarioChoice) -> ScenarioChoice:
    _key(choice.key, "choice kulcs")
    if not str(choice.label).strip() or len(choice.label) > 160:
        raise ScenarioValidationError(f"Hibás choice label: {choice.key}")
    if len(choice.description) > 1200:
        raise ScenarioValidationError(f"Túl hosszú choice description: {choice.key}")
    chance = float(choice.success_chance)
    if not math.isfinite(chance) or not 0.0 <= chance <= 1.0:
        raise ScenarioValidationError(f"Hibás success chance: {choice.key}")
    for value, label in ((choice.reward_success, "success reward"), (choice.reward_fail, "fail reward")):
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 3.0:
            raise ScenarioValidationError(f"Hibás {label}: {choice.key}")
    if not -100 <= int(choice.score_success) <= 100 or not -100 <= int(choice.score_fail) <= 100:
        raise ScenarioValidationError(f"Hibás score delta: {choice.key}")
    for target in (choice.next_on_success, choice.next_on_fail):
        if target is not None:
            _key(target, "branch target")
    return choice


def validate_definition(definition: ScenarioDefinition) -> ScenarioDefinition:
    _key(definition.key, "scenario kulcs")
    _key(definition.family, "scenario family")
    _key(definition.domain, "scenario domain")
    if not str(definition.title).strip() or len(definition.title) > 180:
        raise ScenarioValidationError(f"Hibás scenario cím: {definition.key}")
    if not str(definition.prompt).strip() or len(definition.prompt) > 2400:
        raise ScenarioValidationError(f"Hibás scenario prompt: {definition.key}")
    if not 1 <= len(definition.choices) <= 8:
        raise ScenarioValidationError(f"A scenario 1–8 döntést tartalmazhat: {definition.key}")
    keys: set[str] = set()
    defaults = 0
    for choice in definition.choices:
        validate_choice(choice)
        if choice.key in keys:
            raise ScenarioValidationError(f"Duplikált choice kulcs: {definition.key}/{choice.key}")
        keys.add(choice.key)
        defaults += int(choice.default)
    if defaults > 1:
        raise ScenarioValidationError(f"Több default choice: {definition.key}")
    if not 1 <= int(definition.version) <= 1_000_000:
        raise ScenarioValidationError(f"Hibás scenario version: {definition.key}")
    if str(definition.source) not in {"deterministic", "ai_cached", "ai_live"}:
        raise ScenarioValidationError(f"Ismeretlen scenario source: {definition.source}")
    if len(definition.tags) > 24:
        raise ScenarioValidationError(f"Túl sok scenario tag: {definition.key}")
    for tag in definition.tags:
        _key(tag, "scenario tag")
    if definition.semantic_key:
        _key(definition.semantic_key, "semantic kulcs")
    return definition
