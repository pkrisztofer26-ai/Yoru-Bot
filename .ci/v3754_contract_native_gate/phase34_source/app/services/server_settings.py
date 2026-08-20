from __future__ import annotations
import json
from dataclasses import dataclass
from app.database import Database
from app.repositories.guild_state import GuildStateRepository
from app.repositories.automod import AutomodRepository
from app import member_config as membercfg
from app import moderation_config as modcfg
from app import community_config as communitycfg

@dataclass(frozen=True)
class AutomodRuleState:
    enabled: bool
    action: str
    threshold: int
    timeout_seconds: int
AUTOMOD_PRESETS: dict[str, dict[str, dict[str, int | str | bool]]] = {'basic': {'invite': {'enabled': True, 'action': 'delete', 'threshold': 1, 'timeout_seconds': 600}, 'links': {'enabled': False, 'action': 'delete', 'threshold': 1, 'timeout_seconds': 600}, 'spam': {'enabled': True, 'action': 'warn', 'threshold': 7, 'timeout_seconds': 600}, 'duplicate': {'enabled': True, 'action': 'warn', 'threshold': 4, 'timeout_seconds': 600}, 'mentions': {'enabled': True, 'action': 'timeout', 'threshold': 8, 'timeout_seconds': 600}, 'caps': {'enabled': False, 'action': 'delete', 'threshold': 85, 'timeout_seconds': 600}, 'emoji': {'enabled': False, 'action': 'delete', 'threshold': 16, 'timeout_seconds': 600}, 'words': {'enabled': True, 'action': 'warn', 'threshold': 1, 'timeout_seconds': 600}, 'zalgo': {'enabled': True, 'action': 'delete', 'threshold': 10, 'timeout_seconds': 600}}, 'recommended': {key: dict(value) for key, value in modcfg.AUTOMOD_RULE_DEFAULTS.items()}, 'strict': {'invite': {'enabled': True, 'action': 'delete', 'threshold': 1, 'timeout_seconds': 600}, 'links': {'enabled': True, 'action': 'delete', 'threshold': 1, 'timeout_seconds': 600}, 'spam': {'enabled': True, 'action': 'timeout', 'threshold': 5, 'timeout_seconds': 600}, 'duplicate': {'enabled': True, 'action': 'timeout', 'threshold': 3, 'timeout_seconds': 600}, 'mentions': {'enabled': True, 'action': 'timeout', 'threshold': 5, 'timeout_seconds': 900}, 'caps': {'enabled': True, 'action': 'delete', 'threshold': 75, 'timeout_seconds': 600}, 'emoji': {'enabled': True, 'action': 'delete', 'threshold': 10, 'timeout_seconds': 600}, 'words': {'enabled': True, 'action': 'warn', 'threshold': 1, 'timeout_seconds': 600}, 'zalgo': {'enabled': True, 'action': 'delete', 'threshold': 6, 'timeout_seconds': 600}}}
PRESET_LABELS = {'basic': '🟢 Basic', 'recommended': '🔵 Recommended', 'strict': '🔴 Strict'}

def _clean_template_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if value and value not in cleaned:
            cleaned.append(value[:4000])
    return cleaned[:10]

class ServerSettingsService:
    """Single per-guild configuration API used by Discord UI and future dashboard."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.guild_state_repository = GuildStateRepository(db.path)
        self.automod_repository = AutomodRepository(db.path)

    async def get_bool(self, guild_id: int, key: str, default: bool=False) -> bool:
        raw = await self.guild_state_repository.get(guild_id, key)
        if raw is None or not raw.strip():
            return default
        return raw == '1'

    async def set_bool(self, guild_id: int, key: str, value: bool) -> None:
        await self.guild_state_repository.set(guild_id, key, '1' if value else '0')

    async def get_int(self, guild_id: int, key: str) -> int | None:
        raw = await self.guild_state_repository.get(guild_id, key)
        if raw is None or not raw.strip():
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    async def set_int(self, guild_id: int, key: str, value: int | None) -> None:
        await self.guild_state_repository.set(guild_id, key, str(value) if value is not None else '')

    async def get_text(self, guild_id: int, key: str, default: str='') -> str:
        raw = await self.guild_state_repository.get(guild_id, key)
        return default if raw is None else raw

    async def set_text(self, guild_id: int, key: str, value: str, *, max_length: int=4000) -> None:
        await self.guild_state_repository.set(guild_id, key, str(value)[:max_length])

    async def get_list(self, guild_id: int, key: str, default: list | None=None) -> list:
        raw = await self.guild_state_repository.get(guild_id, key)
        if not raw:
            return list(default or [])
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return list(default or [])
        return list(data) if isinstance(data, list) else list(default or [])

    async def set_list(self, guild_id: int, key: str, values: list) -> None:
        await self.guild_state_repository.set(guild_id, key, json.dumps(values, ensure_ascii=False, separators=(',', ':')))

    async def set_automod_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, 'automod_enabled', enabled)

    async def get_rule(self, guild_id: int, rule: str) -> AutomodRuleState:
        stored = await self.automod_repository.get_rule(guild_id, rule)
        if stored is None:
            default = modcfg.AUTOMOD_RULE_DEFAULTS[rule]
            return AutomodRuleState(bool(default['enabled']), str(default['action']), int(default['threshold']), int(default['timeout_seconds']))
        return AutomodRuleState(*stored)

    async def set_rule(self, guild_id: int, rule: str, *, enabled: bool | None=None, action: str | None=None, threshold: int | None=None, timeout_seconds: int | None=None) -> AutomodRuleState:
        state = await self.get_rule(guild_id, rule)
        final = AutomodRuleState(state.enabled if enabled is None else bool(enabled), state.action if action is None else str(action), state.threshold if threshold is None else int(threshold), state.timeout_seconds if timeout_seconds is None else int(timeout_seconds))
        if final.action not in modcfg.AUTOMOD_ACTIONS:
            raise ValueError('Érvénytelen automatikus védelmi művelet.')
        if final.threshold < 1 or final.threshold > 100:
            raise ValueError('A threshold 1 és 100 között legyen.')
        if final.timeout_seconds < 60 or final.timeout_seconds > 28 * 24 * 3600:
            raise ValueError('A timeout 1 perc és 28 nap között legyen.')
        await self.automod_repository.set_rule(guild_id, rule, final.enabled, final.action, final.threshold, final.timeout_seconds)
        return final

    async def set_rule_window(self, guild_id: int, rule: str, seconds: float) -> None:
        if rule not in {'spam', 'duplicate'}:
            raise ValueError('Ehhez a szabályhoz nincs időablak.')
        if seconds < 1 or seconds > 120:
            raise ValueError('Az időablak 1 és 120 másodperc között legyen.')
        await self.guild_state_repository.set(guild_id, f'automod_window_{rule}', f'{float(seconds):g}')

    async def add_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> None:
        await self.automod_repository.add_exemption(guild_id, rule, scope_type, scope_id)

    async def remove_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> bool:
        return await self.automod_repository.remove_exemption(guild_id, rule, scope_type, scope_id)

    async def list_exemptions(self, guild_id: int, rule: str | None=None) -> list[tuple[str, str, int]]:
        return await self.automod_repository.list_exemptions(guild_id, rule)

    async def remove_domain(self, guild_id: int, domain: str) -> bool:
        return await self.automod_repository.remove_domain(guild_id, domain)

    async def list_domains(self, guild_id: int) -> list[tuple[str, str]]:
        return await self.automod_repository.list_domains(guild_id)

    async def add_word(self, guild_id: int, word: str) -> None:
        await self.automod_repository.add_word(guild_id, word)

    async def remove_word(self, guild_id: int, word: str) -> bool:
        return await self.automod_repository.remove_word(guild_id, word)

    async def list_words(self, guild_id: int) -> list[str]:
        return await self.automod_repository.list_words(guild_id)
