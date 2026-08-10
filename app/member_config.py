from __future__ import annotations

# Yoru v3.7 - Welcome & Roles defaults.
# Guild-specific overrides live in guild_state / role panel tables and are edited
# through /settings. Keep defaults here so later balance/config changes are easy.

WELCOME_DEFAULT_ENABLED = False
WELCOME_DEFAULT_EMBED = True
WELCOME_DEFAULT_RANDOM = False
WELCOME_DEFAULT_DM_ENABLED = False
WELCOME_DEFAULT_TITLE = "👋 Üdv a szerveren!"
WELCOME_DEFAULT_TEMPLATES = [
    "Szia {user}! Üdv a **{server}** szerveren! 🎉\nTe vagy a(z) **{membercount}.** tagunk.",
    "Megérkezett {user}! 🌙 Üdv a **{server}** közösségében. Már **{membercount}** tag vagyunk!",
    "Üdv itt, {user}! 👋 Érezd jól magad a **{server}** szerveren.",
]
WELCOME_DEFAULT_DM_TEMPLATE = (
    "Szia {username}! 👋\n\nÜdv a **{server}** szerveren! Nézd át a szabályokat és érezd jól magad."
)

GOODBYE_DEFAULT_ENABLED = False
GOODBYE_DEFAULT_EMBED = True
GOODBYE_DEFAULT_TITLE = "👋 Viszlát!"
GOODBYE_DEFAULT_TEMPLATE = "**{username}** elhagyta a **{server}** szervert. Már **{membercount}** tag vagyunk."

ROLE_RESTORE_DEFAULT_ENABLED = False
ROLE_RESTORE_MAX_ROLES = 50
AUTOROLE_MAX_ROLES = 10
SELF_ROLE_PANEL_MAX_ROLES = 10
SELF_ROLE_PANEL_MAX_ACTIVE = 20

VERIFICATION_DEFAULT_TITLE = "✅ Szerver ellenőrzés"
VERIFICATION_DEFAULT_BODY = "Olvasd el a szabályzatot, majd az alábbi gombbal fogadd el."
VERIFICATION_DEFAULT_BUTTON = "Elfogadom a szabályzatot"

# Roles with these properties are never auto-assigned/restored/self-assignable.
# Further Discord hierarchy checks are performed at runtime.
BLOCK_MANAGED_ROLES = True
