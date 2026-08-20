from __future__ import annotations
import hashlib
import json
import random
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence
from app.repositories.scenario import ScenarioRepository
from app.scenarios.models import OutcomeTier, ScenarioContext, ScenarioDefinition, ScenarioModifier, ScenarioOutcome, ScenarioRunState, ScenarioRunStatus
from app.scenarios.registry import ScenarioRegistry
from app.scenarios.validation import validate_modifier
from app.scenarios import config as scenario_cfg

class ScenarioEngine:
    """Deterministic Scenario Engine V2 foundation.

    The engine owns content validation, selection, repeat protection and scenario
    run bookkeeping.  It intentionally does *not* own wallet/inventory/XP or any
    other domain settlement.
    """
    RECENT_KEY_GUARD = scenario_cfg.RECENT_KEY_GUARD
    RECENT_TOPIC_GUARD = scenario_cfg.RECENT_TOPIC_GUARD

    def __init__(self, repository: ScenarioRepository, registry: ScenarioRegistry | None=None) -> None:
        self.repository = repository
        self.registry = registry or ScenarioRegistry()

    async def initialize(self) -> None:
        await self.repository.initialize()
        await self.repository.expire_stale_runs()

    @staticmethod
    def topic_hash(definition: ScenarioDefinition) -> str:
        return hashlib.sha256(f'{definition.family}:{definition.topic_key}'.encode('utf-8')).hexdigest()[:24]

    @staticmethod
    def context_digest(context: ScenarioContext | None) -> str | None:
        if context is None:
            return None
        payload = {'domain': context.domain, 'family': context.family, 'city_key': context.city_key, 'tags': sorted(context.tags), 'values': dict(context.values)}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]

    @staticmethod
    def _context_allows(definition: ScenarioDefinition, context: ScenarioContext | None) -> bool:
        if context is None:
            return True
        if definition.domain != context.domain or definition.family != context.family:
            return False
        meta = dict(definition.metadata)
        cities = tuple((str(x) for x in meta.get('cities') or ()))
        if cities and context.city_key and (str(context.city_key) not in cities):
            return False
        required = {str(x) for x in meta.get('required_context_tags') or ()}
        if required and (not required.issubset({str(x) for x in context.tags})):
            return False
        blocked = {str(x) for x in meta.get('blocked_context_tags') or ()}
        if blocked.intersection({str(x) for x in context.tags}):
            return False
        minimum_level = meta.get('min_level')
        if minimum_level is not None:
            try:
                level = int(context.values.get('level', 1))
                if level < int(minimum_level):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    async def select_definition(self, context: ScenarioContext, *, candidate_keys: Iterable[str] | None=None, exclude_keys: Iterable[str]=(), rng: random.Random | random.SystemRandom | None=None, record_shown: bool=True, run_id: str | None=None) -> ScenarioDefinition:
        wanted = {str(k) for k in candidate_keys} if candidate_keys is not None else None
        excluded = {str(k) for k in exclude_keys}
        candidates = [item for item in self.registry.family(context.family, domain=context.domain) if (wanted is None or item.key in wanted) and item.key not in excluded and self._context_allows(item, context)]
        if not candidates:
            raise ValueError(f'Nincs elérhető scenario ebben a family-ben: {context.family}')
        candidate_map = {item.key: item for item in candidates}
        digest = self.registry.family_digest(context.family, keys=set(candidate_map))
        bag, persisted_digest = await self.repository.get_bag(context.guild_id, context.user_id, context.family)
        bag = [key for key in bag if key in candidate_map]
        rnd = rng or random.SystemRandom()
        if persisted_digest != digest or not bag:
            rarity_tickets = {'common': 12, 'uncommon': 6, 'rare': 2, 'ultra_rare': 1}
            bag = []
            for item in candidate_map.values():
                bag.extend([item.key] * rarity_tickets.get(item.rarity.value, 12))
            rnd.shuffle(bag)
        history = await self.repository.recent_history(context.guild_id, context.user_id, context.family, limit=12)
        recent_keys = {str(row['scenario_key']) for row in history[:self.RECENT_KEY_GUARD]}
        recent_topics = {str(row['topic_hash']) for row in history[:self.RECENT_TOPIC_GUARD]}

        def acceptable(key: str, *, semantic: bool, repeat: bool) -> bool:
            item = candidate_map[key]
            if repeat and key in recent_keys:
                return False
            if semantic and self.topic_hash(item) in recent_topics:
                return False
            return True
        selected_key: str | None = None
        for semantic, repeat in ((True, True), (False, True), (False, False)):
            selected_key = next((key for key in bag if acceptable(key, semantic=semantic, repeat=repeat)), None)
            if selected_key is not None:
                break
        if selected_key is None:
            bag = list(candidate_map)
            rnd.shuffle(bag)
            selected_key = bag[0]
        bag.remove(selected_key)
        await self.repository.save_bag(context.guild_id, context.user_id, context.family, bag, digest)
        selected = candidate_map[selected_key]
        if record_shown:
            await self.repository.record_shown(guild_id=context.guild_id, user_id=context.user_id, domain=context.domain, family=context.family, scenario_key=selected.key, topic_hash=self.topic_hash(selected), context_digest=self.context_digest(context), run_id=run_id)
        return selected

    async def resume_run(self, run_id: str) -> tuple[ScenarioRunState, ScenarioDefinition]:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise ValueError('A scenario futás nem található.')
        if run.status != ScenarioRunStatus.ACTIVE:
            raise ValueError('Ez a scenario futás már lezárult.')
        if run.expires_at:
            try:
                if datetime.fromisoformat(run.expires_at) <= datetime.now(timezone.utc):
                    await self.repository.update_run(run.run_id, status=ScenarioRunStatus.EXPIRED)
                    raise ValueError('Ez a scenario futás lejárt.')
            except ValueError as exc:
                if str(exc) == 'Ez a scenario futás lejárt.':
                    raise
        definition = self.registry.get(run.family, run.scenario_key)
        return (run, definition)

    async def evaluate_choice(self, run_id: str, choice_key: str | None=None, *, timeout: bool=False, modifiers: Sequence[ScenarioModifier]=(), rng: random.Random | random.SystemRandom | None=None) -> tuple[ScenarioRunState, ScenarioDefinition, ScenarioOutcome]:
        """Validate and roll an outcome without persisting run completion.

        Host services that own authoritative state can first apply their own
        transaction and only then commit the scenario bookkeeping. This avoids a
        completed Scenario run blocking a retry if the host-domain write fails.
        """
        run, definition = await self.resume_run(run_id)
        rnd = rng or random.SystemRandom()
        if timeout or choice_key is None:
            choice = rnd.choice(definition.choices)
        else:
            choice = definition.choice(str(choice_key))
        chance = choice.normalized_chance()
        reward_multiplier = float(choice.reward_success)
        validated_modifiers = tuple((validate_modifier(item) for item in modifiers))
        for modifier in validated_modifiers:
            chance = chance * float(modifier.chance_multiplier) + float(modifier.chance_add)
        chance = max(0.0, min(1.0, chance))
        roll = float(rnd.random())
        success = roll < chance
        if not success:
            reward_multiplier = float(choice.reward_fail)
        for modifier in validated_modifiers:
            reward_multiplier *= float(modifier.reward_multiplier)
        reward_multiplier = max(0.0, min(3.0, reward_multiplier))
        score_delta = int(choice.score_success if success else choice.score_fail)
        for modifier in validated_modifiers:
            score_delta += int(modifier.score_add_success if success else modifier.score_add_fail)
        score_delta = max(-100, min(100, score_delta))
        continue_run = bool(choice.continue_on_success if success else choice.continue_on_fail)
        next_key = choice.next_on_success if success else choice.next_on_fail
        if success:
            tier = OutcomeTier.CRITICAL_SUCCESS if chance > 0 and roll <= chance * 0.12 else OutcomeTier.SUCCESS
        else:
            fail_span = max(1e-09, 1.0 - chance)
            tier = OutcomeTier.CRITICAL_FAIL if roll - chance >= fail_span * 0.88 else OutcomeTier.FAIL
        outcome = ScenarioOutcome(scenario_key=definition.key, family=definition.family, choice_key=choice.key, success=success, tier=tier, effective_chance=chance, roll=roll, reward_multiplier=reward_multiplier, score_delta=score_delta, continue_run=continue_run, next_scenario_key=next_key, timeout=bool(timeout), applied_modifiers=tuple((item.key for item in validated_modifiers)))
        return (run, definition, outcome)

    async def commit_outcome(self, run: ScenarioRunState, outcome: ScenarioOutcome) -> None:
        """Persist a previously evaluated outcome after the host domain accepts it."""
        live = await self.repository.get_run(run.run_id)
        if live is None or live.status != ScenarioRunStatus.ACTIVE:
            raise ValueError('Ez a scenario futás már lezárult.')
        if live.scenario_key != run.scenario_key:
            raise ValueError('A scenario futás közben megváltozott.')
        state = dict(live.state)
        state['last_outcome'] = asdict(outcome)
        next_key = outcome.next_scenario_key
        if next_key and outcome.continue_run:
            next_definition = self.registry.get(live.family, next_key)
            if next_definition.domain != live.domain:
                raise ValueError('A scenario branch domain eltér a futástól.')
            await self.repository.update_run(live.run_id, status=ScenarioRunStatus.ACTIVE, scenario_key=next_definition.key, current_node=next_definition.key, state=state)
        else:
            await self.repository.update_run(live.run_id, status=ScenarioRunStatus.COMPLETED, state=state)
            await self.repository.complete_history(run_id=live.run_id, outcome=outcome.tier.value)
