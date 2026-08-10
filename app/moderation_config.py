from __future__ import annotations

"""Yoru moderation / AutoMod defaults.

Per-guild overrides are stored in SQLite.  This module intentionally keeps the
system defaults in one place so future balance/tuning does not require hunting
through cogs.
"""

# Deleted-message attachment cache.  Nothing is written to disk; only recent
# small files are kept in RAM so deleted images can be re-uploaded to modlog.
ATTACHMENT_CACHE_TTL_SECONDS = 20 * 60
ATTACHMENT_CACHE_FILE_MAX_BYTES = 6 * 1024 * 1024
ATTACHMENT_CACHE_TOTAL_MAX_BYTES = 24 * 1024 * 1024
ATTACHMENT_CACHE_MAX_MESSAGES = 400

# Audit-log matching window.  Discord audit entries can arrive a little later
# than the gateway event, so listeners wait briefly before attribution.
AUDIT_LOOKBACK_SECONDS = 8
AUDIT_SETTLE_SECONDS = 0.75

# AutoMod is opt-in per guild.  Enabling it uses these safe defaults.
AUTOMOD_DEFAULT_ENABLED = False
AUTOMOD_STAFF_BYPASS = True
AUTOMOD_NOTICE_DELETE_AFTER = 6
AUTOMOD_NOTICE_COOLDOWN_SECONDS = 10

# Rules: enabled, default action, threshold, timeout seconds.
# Supported actions: delete, warn, timeout.
AUTOMOD_RULE_DEFAULTS: dict[str, dict[str, int | str | bool]] = {
    "invite": {"enabled": True, "action": "delete", "threshold": 1, "timeout_seconds": 600},
    "links": {"enabled": False, "action": "delete", "threshold": 1, "timeout_seconds": 600},
    "spam": {"enabled": True, "action": "warn", "threshold": 6, "timeout_seconds": 600},
    "duplicate": {"enabled": True, "action": "warn", "threshold": 3, "timeout_seconds": 600},
    "mentions": {"enabled": True, "action": "timeout", "threshold": 6, "timeout_seconds": 600},
    "caps": {"enabled": True, "action": "delete", "threshold": 80, "timeout_seconds": 600},
    "emoji": {"enabled": True, "action": "delete", "threshold": 14, "timeout_seconds": 600},
    "words": {"enabled": True, "action": "warn", "threshold": 1, "timeout_seconds": 600},
    "zalgo": {"enabled": True, "action": "delete", "threshold": 8, "timeout_seconds": 600},
}

AUTOMOD_RULE_LABELS = {
    "invite": "Discord invite",
    "links": "Külső link",
    "spam": "Üzenet spam",
    "duplicate": "Ismételt üzenet",
    "mentions": "Mention spam",
    "caps": "CAPS spam",
    "emoji": "Emoji spam",
    "words": "Tiltott szó",
    "zalgo": "Unicode / Zalgo spam",
}

AUTOMOD_ACTIONS = {"delete", "warn", "timeout"}

# Detection tuning not exposed as thresholds because these are implementation
# details rather than server policy.
SPAM_WINDOW_SECONDS = 5.0
DUPLICATE_WINDOW_SECONDS = 20.0
CAPS_MIN_LETTERS = 18

# Passive raid warning (no automatic punishment).
RAID_JOIN_WINDOW_SECONDS = 30.0
RAID_JOIN_THRESHOLD = 6
RAID_ALERT_COOLDOWN_SECONDS = 5 * 60

# Domain lists are guild-configurable.  These are intentionally only obvious
# local defaults; Yoru does not pretend to ship a live phishing intelligence
# feed.  Guild blacklist entries always win over exemptions/bypass (owner is
# the only bypass), while allowlist entries bypass the generic links rule.
DEFAULT_BLOCKED_DOMAINS: tuple[str, ...] = ()
DEFAULT_ALLOWED_DOMAINS: tuple[str, ...] = ()

# Log toggles.  Message/member moderation logs are on when a log channel exists;
# voice activity is opt-in because busy voice servers can flood a modlog.
DEFAULT_LOG_VOICE = False

# Per-guild log switches used by /settings.  A missing DB override falls back
# to these values, so existing guilds keep their current logging behaviour.
LOG_DEFAULTS: dict[str, bool] = {
    "message_delete": True,
    "deleted_attachments": True,
    "message_edit": True,
    "join_leave": True,
    "ban_kick": True,
    "timeout": True,
    "role_nick": True,
    "moderation_actions": True,
    "automod": True,
    "voice": DEFAULT_LOG_VOICE,
}
