from __future__ import annotations

import hashlib

from app.scenarios.models import ScenarioDefinition
from app.scenarios.validation import validate_definition


class ScenarioRegistry:
    """Validated deterministic scenario catalog.

    Registry writes happen at process setup / adapter registration time. Runtime
    selection is read-only, which makes invalid content fail before any gameplay
    state mutation can occur.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ScenarioDefinition] = {}

    def register(self, definition: ScenarioDefinition, *, replace: bool = False) -> ScenarioDefinition:
        validated = validate_definition(definition)
        identity = (validated.family, validated.key)
        if identity in self._items and not replace:
            raise ValueError(f"Már létező scenario: {validated.family}/{validated.key}")
        self._items[identity] = validated
        return validated

    def register_many(self, definitions) -> int:
        count = 0
        for item in definitions:
            self.register(item)
            count += 1
        return count

    def get(self, family: str, key: str) -> ScenarioDefinition:
        try:
            definition = self._items[(str(family), str(key))]
        except KeyError as exc:
            raise ValueError(f"Ismeretlen scenario: {family}/{key}") from exc
        if not definition.enabled:
            raise ValueError(f"Kikapcsolt scenario: {family}/{key}")
        return definition

    def maybe_get(self, family: str, key: str) -> ScenarioDefinition | None:
        item = self._items.get((str(family), str(key)))
        return item if item is not None and item.enabled else None

    def family(self, family: str, *, domain: str | None = None) -> tuple[ScenarioDefinition, ...]:
        items = [
            item for (fam, _), item in self._items.items()
            if fam == str(family) and item.enabled and (domain is None or item.domain == str(domain))
        ]
        return tuple(sorted(items, key=lambda item: item.key))

    def all(self) -> tuple[ScenarioDefinition, ...]:
        return tuple(sorted((i for i in self._items.values() if i.enabled), key=lambda i: (i.domain, i.family, i.key)))

    def family_digest(self, family: str, *, keys: set[str] | None = None) -> str:
        rows: list[str] = []
        for item in self.family(family):
            if keys is not None and item.key not in keys:
                continue
            rows.append(f"{item.key}:{item.version}:{item.topic_key}:{item.rarity.value}")
        return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:24]
