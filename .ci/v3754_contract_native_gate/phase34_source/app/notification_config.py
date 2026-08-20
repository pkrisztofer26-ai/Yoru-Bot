from __future__ import annotations

# Existing gameplay DMs are consolidated through this single preference model.
# Critical messages still try a DM even when optional categories are disabled.
CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "system": ("⚙️", "Rendszer"),
    "organization": ("🏴", "Szervezet"),
    "heist": ("🧨", "Nagy Meló"),
    "authority": ("🚔", "Hatósági ügyek"),
    "economy": ("💰", "Gazdaság"),
    "betting": ("🎫", "Fogadás"),
    "world": ("🌍", "Világ"),
    "community": ("💬", "Közösség"),
    "relationship": ("🤝", "Kapcsolatok"),
    "opportunity": ("📌", "Lehetőségek"),
    "contract": ("📦", "Megbízások"),
}

OPTIONAL_DM_DEFAULTS: dict[str, bool] = {
    "organization": True,
    "heist": True,
    "authority": True,
    "economy": True,
    "betting": True,
    "world": False,
    "community": False,
    "relationship": True,
    "opportunity": True,
    "contract": True,
}

SEVERITIES = {"info", "important", "critical"}
INBOX_PAGE_SIZE = 8
INBOX_RETENTION_DAYS = 45
