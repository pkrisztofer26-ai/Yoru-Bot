from __future__ import annotations

import json
from dataclasses import dataclass

from app.database import Database
from app import member_config as membercfg
from app import moderation_config as modcfg
from app import community_config as communitycfg


@dataclass(frozen=True)
class AutomodRuleState:
    enabled: bool
    action: str
    threshold: int
    timeout_seconds: int


AUTOMOD_PRESETS: dict[str, dict[str, dict[str, int | str | bool]]] = {
    "basic": {
        "invite": {"enabled": True, "action": "delete", "threshold": 1, "timeout_seconds": 600},
        "links": {"enabled": False, "action": "delete", "threshold": 1, "timeout_seconds": 600},
        "spam": {"enabled": True, "action": "warn", "threshold": 7, "timeout_seconds": 600},
        "duplicate": {"enabled": True, "action": "warn", "threshold": 4, "timeout_seconds": 600},
        "mentions": {"enabled": True, "action": "timeout", "threshold": 8, "timeout_seconds": 600},
        "caps": {"enabled": False, "action": "delete", "threshold": 85, "timeout_seconds": 600},
        "emoji": {"enabled": False, "action": "delete", "threshold": 16, "timeout_seconds": 600},
        "words": {"enabled": True, "action": "warn", "threshold": 1, "timeout_seconds": 600},
        "zalgo": {"enabled": True, "action": "delete", "threshold": 10, "timeout_seconds": 600},
    },
    "recommended": {key: dict(value) for key, value in modcfg.AUTOMOD_RULE_DEFAULTS.items()},
    "strict": {
        "invite": {"enabled": True, "action": "delete", "threshold": 1, "timeout_seconds": 600},
        "links": {"enabled": True, "action": "delete", "threshold": 1, "timeout_seconds": 600},
        "spam": {"enabled": True, "action": "timeout", "threshold": 5, "timeout_seconds": 600},
        "duplicate": {"enabled": True, "action": "timeout", "threshold": 3, "timeout_seconds": 600},
        "mentions": {"enabled": True, "action": "timeout", "threshold": 5, "timeout_seconds": 900},
        "caps": {"enabled": True, "action": "delete", "threshold": 75, "timeout_seconds": 600},
        "emoji": {"enabled": True, "action": "delete", "threshold": 10, "timeout_seconds": 600},
        "words": {"enabled": True, "action": "warn", "threshold": 1, "timeout_seconds": 600},
        "zalgo": {"enabled": True, "action": "delete", "threshold": 6, "timeout_seconds": 600},
    },
}

PRESET_LABELS = {
    "basic": "🟢 Basic",
    "recommended": "🔵 Recommended",
    "strict": "🔴 Strict",
}


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

    async def get_bool(self, guild_id: int, key: str, default: bool = False) -> bool:
        raw = await self.db.get_guild_state(guild_id, key)
        if raw is None or not raw.strip():
            return default
        return raw == "1"

    async def set_bool(self, guild_id: int, key: str, value: bool) -> None:
        await self.db.set_guild_state(guild_id, key, "1" if value else "0")

    async def get_int(self, guild_id: int, key: str) -> int | None:
        raw = await self.db.get_guild_state(guild_id, key)
        if raw is None or not raw.strip():
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    async def set_int(self, guild_id: int, key: str, value: int | None) -> None:
        await self.db.set_guild_state(guild_id, key, str(value) if value is not None else "")

    async def get_text(self, guild_id: int, key: str, default: str = "") -> str:
        raw = await self.db.get_guild_state(guild_id, key)
        return default if raw is None else raw

    async def set_text(self, guild_id: int, key: str, value: str, *, max_length: int = 4000) -> None:
        await self.db.set_guild_state(guild_id, key, str(value)[:max_length])

    async def get_list(self, guild_id: int, key: str, default: list | None = None) -> list:
        raw = await self.db.get_guild_state(guild_id, key)
        if not raw:
            return list(default or [])
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return list(default or [])
        return list(data) if isinstance(data, list) else list(default or [])

    async def set_list(self, guild_id: int, key: str, values: list) -> None:
        await self.db.set_guild_state(guild_id, key, json.dumps(values, ensure_ascii=False, separators=(",", ":")))

    # -------------------- Moderation / AutoMod --------------------

    async def get_log_channel_id(self, guild_id: int) -> int | None:
        return await self.get_int(guild_id, "moderation_log_channel")

    async def set_log_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        await self.set_int(guild_id, "moderation_log_channel", channel_id)

    async def get_log_enabled(self, guild_id: int, key: str) -> bool:
        default = modcfg.LOG_DEFAULTS.get(key, True)
        return await self.get_bool(guild_id, f"moderation_log_{key}", default)

    async def set_log_enabled(self, guild_id: int, key: str, enabled: bool) -> None:
        if key not in modcfg.LOG_DEFAULTS:
            raise ValueError(f"Ismeretlen log kulcs: {key}")
        await self.set_bool(guild_id, f"moderation_log_{key}", enabled)

    async def get_automod_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "automod_enabled", modcfg.AUTOMOD_DEFAULT_ENABLED)

    async def set_automod_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "automod_enabled", enabled)

    async def get_rule(self, guild_id: int, rule: str) -> AutomodRuleState:
        stored = await self.db.get_automod_rule(guild_id, rule)
        if stored is None:
            default = modcfg.AUTOMOD_RULE_DEFAULTS[rule]
            return AutomodRuleState(
                bool(default["enabled"]),
                str(default["action"]),
                int(default["threshold"]),
                int(default["timeout_seconds"]),
            )
        return AutomodRuleState(*stored)

    async def set_rule(
        self,
        guild_id: int,
        rule: str,
        *,
        enabled: bool | None = None,
        action: str | None = None,
        threshold: int | None = None,
        timeout_seconds: int | None = None,
    ) -> AutomodRuleState:
        state = await self.get_rule(guild_id, rule)
        final = AutomodRuleState(
            state.enabled if enabled is None else bool(enabled),
            state.action if action is None else str(action),
            state.threshold if threshold is None else int(threshold),
            state.timeout_seconds if timeout_seconds is None else int(timeout_seconds),
        )
        if final.action not in modcfg.AUTOMOD_ACTIONS:
            raise ValueError("Érvénytelen AutoMod action.")
        if final.threshold < 1 or final.threshold > 100:
            raise ValueError("A threshold 1 és 100 között legyen.")
        if final.timeout_seconds < 60 or final.timeout_seconds > 28 * 24 * 3600:
            raise ValueError("A timeout 1 perc és 28 nap között legyen.")
        await self.db.set_automod_rule(
            guild_id,
            rule,
            final.enabled,
            final.action,
            final.threshold,
            final.timeout_seconds,
        )
        return final

    async def get_rule_window(self, guild_id: int, rule: str) -> float | None:
        defaults = {"spam": modcfg.SPAM_WINDOW_SECONDS, "duplicate": modcfg.DUPLICATE_WINDOW_SECONDS}
        if rule not in defaults:
            return None
        raw = await self.db.get_guild_state(guild_id, f"automod_window_{rule}")
        if raw is None:
            return float(defaults[rule])
        try:
            value = float(raw)
        except ValueError:
            return float(defaults[rule])
        return max(1.0, min(120.0, value))

    async def set_rule_window(self, guild_id: int, rule: str, seconds: float) -> None:
        if rule not in {"spam", "duplicate"}:
            raise ValueError("Ehhez a szabályhoz nincs időablak.")
        if seconds < 1 or seconds > 120:
            raise ValueError("Az időablak 1 és 120 másodperc között legyen.")
        await self.db.set_guild_state(guild_id, f"automod_window_{rule}", f"{float(seconds):g}")

    async def apply_preset(self, guild_id: int, preset: str) -> None:
        preset = preset.lower()
        if preset not in AUTOMOD_PRESETS:
            raise ValueError("Ismeretlen preset.")
        for rule, values in AUTOMOD_PRESETS[preset].items():
            await self.db.set_automod_rule(
                guild_id,
                rule,
                bool(values["enabled"]),
                str(values["action"]),
                int(values["threshold"]),
                int(values["timeout_seconds"]),
            )
        await self.set_automod_enabled(guild_id, True)
        await self.set_rule_window(guild_id, "spam", modcfg.SPAM_WINDOW_SECONDS)
        await self.set_rule_window(guild_id, "duplicate", modcfg.DUPLICATE_WINDOW_SECONDS)

    async def add_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> None:
        await self.db.add_automod_exemption(guild_id, rule, scope_type, scope_id)

    async def remove_exemption(self, guild_id: int, rule: str, scope_type: str, scope_id: int) -> bool:
        return await self.db.remove_automod_exemption(guild_id, rule, scope_type, scope_id)

    async def list_exemptions(self, guild_id: int, rule: str | None = None) -> list[tuple[str, str, int]]:
        return await self.db.list_automod_exemptions(guild_id, rule)

    async def add_domain(self, guild_id: int, mode: str, domain: str) -> None:
        await self.db.set_automod_domain(guild_id, mode, domain)

    async def remove_domain(self, guild_id: int, domain: str) -> bool:
        return await self.db.remove_automod_domain(guild_id, domain)

    async def list_domains(self, guild_id: int) -> list[tuple[str, str]]:
        return await self.db.list_automod_domains(guild_id)

    async def add_word(self, guild_id: int, word: str) -> None:
        await self.db.add_automod_word(guild_id, word)

    async def remove_word(self, guild_id: int, word: str) -> bool:
        return await self.db.remove_automod_word(guild_id, word)

    async def list_words(self, guild_id: int) -> list[str]:
        return await self.db.list_automod_words(guild_id)

    # -------------------- Welcome / Goodbye --------------------

    async def get_welcome_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "welcome_enabled", membercfg.WELCOME_DEFAULT_ENABLED)

    async def set_welcome_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "welcome_enabled", enabled)

    async def get_welcome_channel_id(self, guild_id: int) -> int | None:
        return await self.get_int(guild_id, "welcome_channel_id")

    async def set_welcome_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        await self.set_int(guild_id, "welcome_channel_id", channel_id)

    async def get_welcome_embed(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "welcome_embed", membercfg.WELCOME_DEFAULT_EMBED)

    async def set_welcome_embed(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "welcome_embed", enabled)

    async def get_welcome_random(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "welcome_random", membercfg.WELCOME_DEFAULT_RANDOM)

    async def set_welcome_random(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "welcome_random", enabled)

    async def get_welcome_title(self, guild_id: int) -> str:
        return await self.get_text(guild_id, "welcome_title", membercfg.WELCOME_DEFAULT_TITLE)

    async def set_welcome_title(self, guild_id: int, value: str) -> None:
        await self.set_text(guild_id, "welcome_title", value.strip() or membercfg.WELCOME_DEFAULT_TITLE, max_length=256)

    async def get_welcome_templates(self, guild_id: int) -> list[str]:
        values = await self.get_list(guild_id, "welcome_templates", membercfg.WELCOME_DEFAULT_TEMPLATES)
        cleaned = _clean_template_list([str(v) for v in values])
        return cleaned or list(membercfg.WELCOME_DEFAULT_TEMPLATES)

    async def set_welcome_templates(self, guild_id: int, values: list[str]) -> None:
        cleaned = _clean_template_list(values)
        await self.set_list(guild_id, "welcome_templates", cleaned or list(membercfg.WELCOME_DEFAULT_TEMPLATES))

    async def get_welcome_dm_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "welcome_dm_enabled", membercfg.WELCOME_DEFAULT_DM_ENABLED)

    async def set_welcome_dm_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "welcome_dm_enabled", enabled)

    async def get_welcome_dm_template(self, guild_id: int) -> str:
        return await self.get_text(guild_id, "welcome_dm_template", membercfg.WELCOME_DEFAULT_DM_TEMPLATE)

    async def set_welcome_dm_template(self, guild_id: int, value: str) -> None:
        await self.set_text(guild_id, "welcome_dm_template", value.strip() or membercfg.WELCOME_DEFAULT_DM_TEMPLATE)

    async def get_goodbye_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "goodbye_enabled", membercfg.GOODBYE_DEFAULT_ENABLED)

    async def set_goodbye_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "goodbye_enabled", enabled)

    async def get_goodbye_channel_id(self, guild_id: int) -> int | None:
        return await self.get_int(guild_id, "goodbye_channel_id")

    async def set_goodbye_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        await self.set_int(guild_id, "goodbye_channel_id", channel_id)

    async def get_goodbye_embed(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "goodbye_embed", membercfg.GOODBYE_DEFAULT_EMBED)

    async def set_goodbye_embed(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "goodbye_embed", enabled)

    async def get_goodbye_title(self, guild_id: int) -> str:
        return await self.get_text(guild_id, "goodbye_title", membercfg.GOODBYE_DEFAULT_TITLE)

    async def set_goodbye_title(self, guild_id: int, value: str) -> None:
        await self.set_text(guild_id, "goodbye_title", value.strip() or membercfg.GOODBYE_DEFAULT_TITLE, max_length=256)

    async def get_goodbye_template(self, guild_id: int) -> str:
        return await self.get_text(guild_id, "goodbye_template", membercfg.GOODBYE_DEFAULT_TEMPLATE)

    async def set_goodbye_template(self, guild_id: int, value: str) -> None:
        await self.set_text(guild_id, "goodbye_template", value.strip() or membercfg.GOODBYE_DEFAULT_TEMPLATE)

    # -------------------- Roles --------------------

    async def get_human_autoroles(self, guild_id: int) -> list[int]:
        values = await self.get_list(guild_id, "autoroles_human", [])
        return [int(v) for v in values if str(v).isdigit()][: membercfg.AUTOROLE_MAX_ROLES]

    async def set_human_autoroles(self, guild_id: int, role_ids: list[int]) -> None:
        unique = list(dict.fromkeys(int(v) for v in role_ids))[: membercfg.AUTOROLE_MAX_ROLES]
        await self.set_list(guild_id, "autoroles_human", unique)

    async def get_bot_autoroles(self, guild_id: int) -> list[int]:
        values = await self.get_list(guild_id, "autoroles_bot", [])
        return [int(v) for v in values if str(v).isdigit()][: membercfg.AUTOROLE_MAX_ROLES]

    async def set_bot_autoroles(self, guild_id: int, role_ids: list[int]) -> None:
        unique = list(dict.fromkeys(int(v) for v in role_ids))[: membercfg.AUTOROLE_MAX_ROLES]
        await self.set_list(guild_id, "autoroles_bot", unique)

    async def get_role_restore_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "role_restore_enabled", membercfg.ROLE_RESTORE_DEFAULT_ENABLED)

    async def set_role_restore_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "role_restore_enabled", enabled)

    # -------------------- Community Management --------------------

    async def get_suggestions_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_suggestions_enabled", communitycfg.SUGGESTIONS_DEFAULT_ENABLED)

    async def set_suggestions_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_suggestions_enabled", enabled)

    async def get_suggestion_channel_id(self, guild_id: int) -> int | None:
        return await self.get_int(guild_id, "community_suggestion_channel_id")

    async def set_suggestion_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        await self.set_int(guild_id, "community_suggestion_channel_id", channel_id)

    async def get_suggestions_anonymous(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_suggestions_anonymous", communitycfg.SUGGESTIONS_ALLOW_ANONYMOUS)

    async def set_suggestions_anonymous(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_suggestions_anonymous", enabled)

    async def get_polls_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_polls_enabled", communitycfg.POLLS_DEFAULT_ENABLED)

    async def set_polls_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_polls_enabled", enabled)

    async def get_polls_staff_only(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_polls_staff_only", communitycfg.POLLS_STAFF_ONLY_DEFAULT)

    async def set_polls_staff_only(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_polls_staff_only", enabled)

    async def get_poll_default_duration_minutes(self, guild_id: int) -> int:
        value = await self.get_int(guild_id, "community_poll_default_duration_minutes")
        return max(communitycfg.POLLS_MIN_DURATION_MINUTES, min(communitycfg.POLLS_MAX_DURATION_MINUTES, value or communitycfg.POLLS_DEFAULT_DURATION_MINUTES))

    async def set_poll_default_duration_minutes(self, guild_id: int, minutes: int) -> None:
        minutes = max(communitycfg.POLLS_MIN_DURATION_MINUTES, min(communitycfg.POLLS_MAX_DURATION_MINUTES, int(minutes)))
        await self.set_int(guild_id, "community_poll_default_duration_minutes", minutes)

    async def get_giveaways_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_giveaways_enabled", communitycfg.GIVEAWAYS_DEFAULT_ENABLED)

    async def set_giveaways_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_giveaways_enabled", enabled)

    async def get_giveaway_default_duration_minutes(self, guild_id: int) -> int:
        value = await self.get_int(guild_id, "community_giveaway_default_duration_minutes")
        return max(communitycfg.GIVEAWAYS_MIN_DURATION_MINUTES, min(communitycfg.GIVEAWAYS_MAX_DURATION_MINUTES, value or communitycfg.GIVEAWAYS_DEFAULT_DURATION_MINUTES))

    async def set_giveaway_default_duration_minutes(self, guild_id: int, minutes: int) -> None:
        minutes = max(communitycfg.GIVEAWAYS_MIN_DURATION_MINUTES, min(communitycfg.GIVEAWAYS_MAX_DURATION_MINUTES, int(minutes)))
        await self.set_int(guild_id, "community_giveaway_default_duration_minutes", minutes)

    async def get_starboard_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_starboard_enabled", communitycfg.STARBOARD_DEFAULT_ENABLED)

    async def set_starboard_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_starboard_enabled", enabled)

    async def get_starboard_channel_id(self, guild_id: int) -> int | None:
        return await self.get_int(guild_id, "community_starboard_channel_id")

    async def set_starboard_channel_id(self, guild_id: int, channel_id: int | None) -> None:
        await self.set_int(guild_id, "community_starboard_channel_id", channel_id)

    async def get_starboard_threshold(self, guild_id: int) -> int:
        value = await self.get_int(guild_id, "community_starboard_threshold")
        return max(communitycfg.STARBOARD_MIN_THRESHOLD, min(communitycfg.STARBOARD_MAX_THRESHOLD, value or communitycfg.STARBOARD_DEFAULT_THRESHOLD))

    async def set_starboard_threshold(self, guild_id: int, threshold: int) -> None:
        threshold = max(communitycfg.STARBOARD_MIN_THRESHOLD, min(communitycfg.STARBOARD_MAX_THRESHOLD, int(threshold)))
        await self.set_int(guild_id, "community_starboard_threshold", threshold)

    async def get_afk_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_afk_enabled", communitycfg.AFK_DEFAULT_ENABLED)

    async def set_afk_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_afk_enabled", enabled)

    async def get_sticky_enabled(self, guild_id: int) -> bool:
        return await self.get_bool(guild_id, "community_sticky_enabled", communitycfg.STICKY_DEFAULT_ENABLED)

    async def set_sticky_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.set_bool(guild_id, "community_sticky_enabled", enabled)

    async def get_sticky_every_messages(self, guild_id: int) -> int:
        value = await self.get_int(guild_id, "community_sticky_every_messages")
        return max(communitycfg.STICKY_MIN_EVERY_MESSAGES, min(communitycfg.STICKY_MAX_EVERY_MESSAGES, value or communitycfg.STICKY_DEFAULT_EVERY_MESSAGES))

    async def set_sticky_every_messages(self, guild_id: int, count: int) -> None:
        count = max(communitycfg.STICKY_MIN_EVERY_MESSAGES, min(communitycfg.STICKY_MAX_EVERY_MESSAGES, int(count)))
        await self.set_int(guild_id, "community_sticky_every_messages", count)

