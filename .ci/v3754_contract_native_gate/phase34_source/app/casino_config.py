from __future__ import annotations

"""Yoru Casino V2 central balance/runtime configuration.

All house-game payout and runtime values live here.  Older constants remain for
backwards compatibility, while V2 engines use the dedicated V2 sections below.
"""

# No fixed maximum bet. ``all`` and >1B balances remain supported as long as
# the wallet covers the reservation.
MIN_BET = 5_000

# ---------------------------------------------------------------------------
# Existing quick-game balance
# ---------------------------------------------------------------------------
COINFLIP_TOTAL_PAYOUT = 1.90        # 95.0% RTP
DICE_TOTAL_PAYOUT = 5.50            # 91.7% RTP
ROULETTE_EVEN_TOTAL_PAYOUT = 1.92   # legacy compatibility
ROULETTE_SINGLE_TOTAL_PAYOUT = 34.0 # legacy compatibility
CHICKEN_WIN_CHANCE = 0.46
CHICKEN_TOTAL_PAYOUT = 2.00         # 92% RTP
HIGHLOW_TOTAL_PAYOUT = 1.88         # tie refunddal ~94.5% RTP
RPS_TOTAL_PAYOUT = 1.85             # tie refunddal ~95% RTP

# Legacy Slots V1 constants remain exported because older analytics/tests and
# config aliases still import them. Slots gameplay itself is V2 from v3.19.0.
SLOTS_SYMBOLS = ("🍒", "🍋", "🍇", "🔔", "💎", "7️⃣")
SLOTS_WEIGHTS = (30, 26, 20, 13, 8, 3)
SLOTS_PAIR_TOTAL_PAYOUT = 0.80
SLOTS_TRIPLE_TOTAL_PAYOUT = {
    "🍒": 8.0,
    "🍋": 10.0,
    "🍇": 12.0,
    "🔔": 18.0,
    "💎": 30.0,
    "7️⃣": 80.0,
}

# ---------------------------------------------------------------------------
# Blackjack V2
# ---------------------------------------------------------------------------
BLACKJACK_WIN_TOTAL_PAYOUT = 2.00
BLACKJACK_NATURAL_TOTAL_PAYOUT = 2.50   # classic 3:2 profit
BLACKJACK_INSURANCE_TOTAL_PAYOUT = 3.00 # 2:1 profit on the insurance stake
BLACKJACK_TIMEOUT_SECONDS = 90
BLACKJACK_DEAL_FRAME_DELAY = 0.28
BLACKJACK_PLAYER_DRAW_DELAY = 0.32
BLACKJACK_DEALER_FRAME_DELAY = 0.42
BLACKJACK_DEALER_MAX_FRAMES = 6

# ---------------------------------------------------------------------------
# Slots — 5x3 / 20 paylines / Wild / Scatter / Free Spins
# ---------------------------------------------------------------------------
SLOTS_V2_WILD = "⭐"
SLOTS_V2_SCATTER = "💰"
SLOTS_V2_SYMBOLS = ("🍒", "🍋", "🍇", "🔔", "💎", "7️⃣", SLOTS_V2_WILD, SLOTS_V2_SCATTER)
SLOTS_V2_WEIGHTS = (28, 25, 20, 14, 8, 3, 3, 2)

# Rows are 0=top, 1=middle, 2=bottom. Each tuple selects one row per reel.
SLOTS_V2_PAYLINES = (
    (1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0),
    (2, 2, 2, 2, 2),
    (0, 1, 2, 1, 0),
    (2, 1, 0, 1, 2),
    (0, 0, 1, 2, 2),
    (2, 2, 1, 0, 0),
    (1, 0, 0, 0, 1),
    (1, 2, 2, 2, 1),
    (0, 1, 1, 1, 2),
    (2, 1, 1, 1, 0),
    (1, 0, 1, 2, 1),
    (1, 2, 1, 0, 1),
    (0, 1, 0, 1, 0),
    (2, 1, 2, 1, 2),
    (0, 1, 2, 2, 2),
    (2, 1, 0, 0, 0),
    (0, 0, 1, 0, 0),
    (2, 2, 1, 2, 2),
    (1, 0, 1, 0, 1),
)

# Raw line multipliers are divided equally across all 20 paylines because the
# command stake is the TOTAL spin stake, not a separate stake per line.
# RTP is regression-tested after every payline/paytable change.
SLOTS_V2_PAYTABLE = {
    "🍒": {3: 6.75, 4: 15.75, 5: 33.75},
    "🍋": {3: 9.00, 4: 20.25, 5: 45.00},
    "🍇": {3: 11.25, 4: 27.00, 5: 67.50},
    "🔔": {3: 18.00, 4: 45.00, 5: 112.50},
    "💎": {3: 27.00, 4: 78.75, 5: 202.50},
    "7️⃣": {3: 45.00, 4: 168.75, 5: 562.50},
    SLOTS_V2_WILD: {3: 33.75, 4: 135.00, 5: 450.00},
}
SLOTS_V2_SCATTER_PAYOUT = {3: 2.25, 4: 6.75, 5: 22.50}
SLOTS_V2_FREE_SPINS = {3: 5, 4: 8, 5: 12}
SLOTS_V2_MAX_FREE_SPINS = 25
SLOTS_V2_BASE_FRAME_DELAY = 0.16
SLOTS_V2_FREE_SPIN_DELAY = 0.18
SLOTS_V2_ANIMATION_SECONDS = 2.05
SLOTS_V2_RENDER_CONCURRENCY = 1
SLOTS_V2_RTP_TARGET = (0.92, 0.97)

# ---------------------------------------------------------------------------
# Roulette — individual multi-bet table
# ---------------------------------------------------------------------------
ROULETTE_V2_BETTING_SECONDS = 20
ROULETTE_V2_RESULT_GRACE_SECONDS = 12
ROULETTE_V2_EVEN_TOTAL_PAYOUT = 2.00
ROULETTE_V2_DOZEN_COLUMN_TOTAL_PAYOUT = 3.00
ROULETTE_V2_SINGLE_TOTAL_PAYOUT = 36.00
ROULETTE_V2_SPIN_FRAME_DELAY = 0.18
ROULETTE_V2_SPIN_FRAMES = 20
ROULETTE_V2_ANIMATION_SECONDS = 3.20
ROULETTE_V2_MAX_BETS_PER_PLAYER = 20


# ---------------------------------------------------------------------------
# Quick games / Casino UX standard
# ---------------------------------------------------------------------------
QUICK_GAME_ANIMATION_SECONDS = 2.35
QUICK_GAME_RENDER_CONCURRENCY = 1
COINFLIP_V2_TOTAL_PAYOUT = 1.90
DICE_V2_EXACT_TOTAL_PAYOUT = 5.70
DICE_V2_EVEN_TOTAL_PAYOUT = 1.90
DICE_V2_OVER_UNDER_TOTAL_PAYOUT = 2.28
DICE_V2_EXACT_SEVEN_TOTAL_PAYOUT = 5.70
RPS_V2_TOTAL_PAYOUT = 1.85
HIGHLOW_V2_HOUSE_FACTOR = 0.96
HIGHLOW_V2_MIN_STEP_MULTIPLIER = 1.00
HIGHLOW_V2_TIMEOUT_SECONDS = 90
CHICKEN_V2_ANIMATION_SECONDS = 3.30

# Monthly Global Jackpot
MONTHLY_JACKPOT_MIN_GAMES = 25
MONTHLY_JACKPOT_MIN_WAGER = 250_000
MONTHLY_JACKPOT_PAYOUT_SHARE = 1.00
MONTHLY_JACKPOT_CHECK_SECONDS = 900
MONTHLY_JACKPOT_HISTORY_LIMIT = 5

# ---------------------------------------------------------------------------
# Casino Core / ledger
# ---------------------------------------------------------------------------
MONTHLY_JACKPOT_CONTRIBUTION_RATE = 0.02
CASINO_HISTORY_PAGE_SIZE = 8
CASINO_SESSION_STATUSES = ("ACTIVE", "WAITING_INPUT", "SETTLING", "SETTLED", "REFUNDED", "CANCELLED")

GAME_ID_PREFIXES = {
    "blackjack": "BJ",
    "coinflip": "CF",
    "dice": "DC",
    "slots": "SL",
    "roulette": "RL",
    "highlow": "HL",
    "rps": "RPS",
    "chickenfight": "CHK",
    "mines": "MN",
    "chickenroad": "CRD",
    "plinko": "PLK",
    "candyrush": "CDY",
}

HOUSE_GAMES = frozenset({
    "blackjack", "coinflip", "dice", "slots", "roulette",
    "highlow", "rps", "chickenfight",
    "mines", "chickenroad", "plinko", "candyrush",
})
