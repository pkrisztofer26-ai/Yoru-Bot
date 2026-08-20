from __future__ import annotations

# Yoru v3.13 Social Economy defaults.

# Player marketplace
PLAYER_MARKET_TAX_RATE = 0.05
PLAYER_MARKET_LISTING_HOURS = 72
PLAYER_MARKET_MAX_ACTIVE_PER_USER = 20
PLAYER_MARKET_MAX_QUANTITY = 999
PLAYER_MARKET_MIN_UNIT_PRICE = 1_000
PLAYER_MARKET_PAGE_SIZE = 10

# Custom server shop
SERVER_SHOP_MAX_ITEMS = 50
SERVER_SHOP_DEFAULT_EMOJI = "🎁"
SERVER_SHOP_MAX_NAME = 80
SERVER_SHOP_MAX_DESCRIPTION = 300
SERVER_SHOP_MAX_STOCK = 1_000_000
SERVER_SHOP_MAX_PER_USER = 10_000
SERVER_SHOP_MAX_TEMP_ROLE_MINUTES = 60 * 24 * 365
SERVER_SHOP_REWARD_TYPES = ("role", "temporary_role", "custom_role", "temporary_custom_role", "item", "custom")


# Beépített Közösségi Bolt jutalmak.
# Ezek nem a játékbeli Yoru Bolt részei. A Server Shop/Közösségi Bolt
# meglévő claim-rendszerét használják, így nincs második jutalom-backend.
BUILTIN_COMMUNITY_REWARDS = {
    "builtin:nitro_basic_1m": {
        "name": "Discord Nitro Basic • 1 hónap",
        "description": "Közösségi jutalom. Vásárlás után a moderátori csapat intézi az átadását.",
        "emoji": "🎁",
        "price": 500_000_000,
        "claim_text": "Discord Nitro Basic • 1 hónap",
        "min_account_age_days": 30,
        "personal_cooldown_days": 30,
        "guild_monthly_stock": 4,
    },
    "builtin:discord_nitro_1m": {
        "name": "Discord Nitro • 1 hónap",
        "description": "Közösségi jutalom. Vásárlás után a moderátori csapat intézi az átadását.",
        "emoji": "💠",
        "price": 750_000_000,
        "claim_text": "Discord Nitro • 1 hónap",
        "min_account_age_days": 45,
        "personal_cooldown_days": 30,
        "guild_monthly_stock": 2,
    },
}

LEGACY_PREMIUM_ITEM_TO_COMMUNITY_REF = {
    "nitro_basic_1m": "builtin:nitro_basic_1m",
    "discord_nitro_1m": "builtin:discord_nitro_1m",
}


def builtin_community_reward(reward_ref: str):
    return BUILTIN_COMMUNITY_REWARDS.get(str(reward_ref))


def community_claim_text(reward_ref: str) -> str:
    rule = builtin_community_reward(reward_ref)
    return str(rule["claim_text"]) if rule else str(reward_ref)

# PvP gambling
PVP_MIN_STAKE = 1_000
PVP_CHALLENGE_SECONDS = 120
PVP_RPS_SECONDS = 120
PVP_GAMES = ("coinflip", "dice", "rps")

# Background maintenance
SOCIAL_CLEANUP_SECONDS = 60

# PvP Casino visual standard
PVP_RENDER_CONCURRENCY = 2
PVP_VISUAL_ANIMATION_SECONDS = 3.35
PVP_RPS_VISUAL_ANIMATION_SECONDS = 2.45
