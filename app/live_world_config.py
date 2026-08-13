from __future__ import annotations

LIVE_ENABLED_KEY="live_world_enabled"
SHOPROB_ENABLED_KEY="live_shoprob_enabled"
BANKROB_ENABLED_KEY="live_bankrob_enabled"
MAV_ENABLED_KEY="live_mav_enabled"
POKER_ENABLED_KEY="live_poker_enabled"
SHOPROB_COOLDOWN_KEY="live_shoprob_cooldown_minutes"
BANKROB_COOLDOWN_KEY="live_bankrob_cooldown_minutes"
MAV_MIN_BET_KEY="live_mav_min_bet"
POKER_MIN_BUYIN_KEY="live_poker_min_buyin"
LIVE_MAX_PAYOUT_KEY="live_max_payout"

DEFAULT_SHOPROB_COOLDOWN_MINUTES=120
DEFAULT_BANKROB_COOLDOWN_MINUTES=240
DEFAULT_MAV_MIN_BET=50_000
DEFAULT_POKER_MIN_BUYIN=250_000
DEFAULT_MAX_PAYOUT=100_000_000_000
POKER_TURN_SECONDS=35

ROBBERY_DEFS={
    "shoprob": {
        "name":"Boltrablás","emoji":"🏪","stages":4,
        "base_loot": (80_000,150_000),"fail_keep":0.35,
        "choices":{
            "safe":{"label":"Óvatosan","risk":0.10,"loot":0.80,"heat":4},
            "fast":{"label":"Gyorsan","risk":0.16,"loot":1.05,"heat":7},
            "greedy":{"label":"Mindent viszel","risk":0.24,"loot":1.45,"heat":11},
        },
    },
    "bankrob": {
        "name":"Bankrablás","emoji":"🏦","stages":6,
        "base_loot": (220_000,390_000),"fail_keep":0.18,
        "choices":{
            "safe":{"label":"Csendes terv","risk":0.14,"loot":0.85,"heat":5},
            "fast":{"label":"Tempós haladás","risk":0.18,"loot":1.25,"heat":7},
            "greedy":{"label":"Széfet is kipakolod","risk":0.24,"loot":1.80,"heat":10},
        },
    },
}
