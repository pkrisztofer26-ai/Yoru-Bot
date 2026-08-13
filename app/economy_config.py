from __future__ import annotations

from datetime import timedelta

# ============================================================
# YORU v3.5.0 — CENTRAL BALANCE CONFIG
# ============================================================
# A fő economy/progression/shop/event balance értékeket EZEN A
# FÁJLON belül kezeld. Így később nem kell több service/cog között
# keresgélni egy egyszerű balance módosításhoz.
#
# Fontos: a pénzmennyiségnek nincs globális plafonja. A cél az,
# hogy a milliós vagyon már komoly mérföldkő legyen, miközben a
# gambling továbbra is szabadon engedi az all-int, ha a játékos
# vállalja a kockázatot.
# ============================================================

# --- Alap economy / progression ---
STARTING_BALANCE = 25_000
PROGRESSION_LEVEL_XP_SCALE = 5
PROGRESSION_XP_REWARDS = {
    "work": 8,
    "beg": 2,
    "search": 6,
    "crime": 10,
    "slut": 10,
    "rob": 20,
    "daily": 25,
    "weekly": 100,
    "monthly": 300,
    "role_income": 8,
    "interest": 5,
}
QUEST_PROGRESSION_XP = {"daily": 20, "weekly": 75}

# --- Cooldownok ---
DAILY_COOLDOWN = timedelta(hours=24)
WEEKLY_COOLDOWN = timedelta(days=7)
MONTHLY_COOLDOWN = timedelta(days=30)
WORK_COOLDOWN = timedelta(minutes=5)
CRIME_COOLDOWN = timedelta(minutes=10)
SEARCH_COOLDOWN = timedelta(minutes=15)
BEG_COOLDOWN = timedelta(minutes=5)
ROB_COOLDOWN = timedelta(hours=2)
WITHDRAW_ROB_PROTECTION = timedelta(minutes=5)
SLUT_COOLDOWN = timedelta(minutes=10)
INTEREST_COOLDOWN = timedelta(hours=6)
CLAIM_INCOME_COOLDOWN = timedelta(hours=4)
ROLE_INCOME_MAX_ACCUMULATION = timedelta(hours=24)
ROLE_INCOME_FIRST_CLAIM_HOURS = 4
ROLE_INCOME_STACKING = False
WEEKLY_MIN_ACCOUNT_AGE_DAYS = 7
MONTHLY_MIN_ACCOUNT_AGE_DAYS = 30

# Prefix anti-flood: a gyors Ctrl+C/Ctrl+V spam nem fut le újra és újra.
PREFIX_ACTION_MIN_INTERVAL_SECONDS = 1.25

# --- Stabil aktív income ---
DAILY_REWARD = (60_000, 100_000)
DAILY_STREAK_BONUS = 2_500
DAILY_STREAK_BONUS_MAX_DAYS = 20
DAILY_STREAK_GRACE_HOURS = 48
WEEKLY_REWARD = (300_000, 450_000)
MONTHLY_REWARD = (1_000_000, 1_500_000)

WORK_REWARD = (6_000, 25_000)
WORK_JOBS = [
    ("pizzát szállítottál ki", 6_000, 12_000),
    ("egy raktárban pakoltál", 8_000, 15_000),
    ("autókat szereltél", 10_000, 18_000),
    ("egy weboldalon dolgoztál", 12_000, 25_000),
    ("takarítottál egy irodában", 6_000, 11_000),
    ("kutyákat sétáltattál", 6_000, 10_000),
    ("egy étteremben mosogattál", 7_000, 13_000),
    ("csomagokat kézbesítettél", 8_000, 16_000),
    ("egy koncerten biztonsági őr voltál", 10_000, 20_000),
    ("videókat vágtál egy streamernek", 11_000, 23_000),
    ("egy építkezésen segítettél", 9_000, 19_000),
    ("éjszakai műszakot vállaltál", 12_000, 25_000),
]

BEG_OUTCOMES = [
    ("Egy járókelő megsajnált", 500, 3_500),
    ("Egy gazdag üzletember adott egy kis aprót", 2_000, 8_000),
    ("Találtál néhány érmét a földön", 500, 2_500),
    ("Egy idős néni kisegített", 1_000, 5_000),
    ("Senki sem állt meg melletted", 0, 0),
]

SEARCH_PLACES = [
    ("a kanapé párnái között", 500, 4_000),
    ("egy elhagyott hátizsákban", 1_500, 9_000),
    ("a parkolóban", 500, 5_000),
    ("egy automata alatt", 500, 3_500),
    ("a régi kabátod zsebében", 1_000, 6_000),
    ("egy sikátorban", 2_000, 15_000),
    ("a buszmegálló mellett", 500, 4_500),
    ("egy poros fiókban", 1_000, 7_000),
]

# Crime / slut: nagyobb egyszeri payout, valódi negatív kockázattal.
CRIME_REWARD = (20_000, 95_000)
CRIME_FINE = (45_000, 140_000)
CRIME_SCENARIOS = [
    ("feltörtél egy italautomatát", 0.72),
    ("elloptál egy biciklit", 0.68),
    ("meghekkeltél egy parkolóórát", 0.66),
    ("kirámoltál egy kisboltot", 0.60),
    ("elloptál egy autót", 0.52),
    ("kifosztottál egy raktárt", 0.56),
    ("hamis jegyeket adtál el", 0.64),
    ("kaszinózsetonokat csempésztél ki", 0.48),
]
CRIME_JAIL_CHANCE = 0.45
CRIME_JAIL_MIN_MINUTES = 5
CRIME_JAIL_MAX_MINUTES = 15

SLUT_SUCCESS_CHANCE = 0.56
SLUT_REWARD = (18_000, 85_000)
SLUT_FINE = (35_000, 100_000)

# Rob: vagyon-átrendezés, nem pénznyomtatás. A sikeres steal share kifejezetten 60%.
ROB_SUCCESS_SHARE = 0.60
ROB_SUCCESS_CHANCE = 0.25
ROB_BOOSTED_MAX_CHANCE = 0.35
ROB_FAIL_FINE = (15_000, 80_000)
ROB_FAIL_FINE_SHARE = (0.15, 0.25)
ROB_MIN_COVERAGE_SHARE = 0.05
ROB_MIN_ATTEMPT_WALLET = 25_000
ROB_MIN_VICTIM_WALLET = 50_000

# --- Bank / passzív income ---
INTEREST_MIN_BANK = 100_000
INTEREST_MIN_REWARD = 250
# (minimum bank, kamatláb, maximum 6 órás kifizetés), csökkenő sorrendben.
INTEREST_TIERS = [
    (100_000_000, 0.0005, 50_000),
    (25_000_000, 0.0007, 25_000),
    (5_000_000, 0.0009, 10_000),
    (1_000_000, 0.0011, 5_000),
    (0, 0.0015, 2_000),
]
ROLE_INCOME_BALANCE_WARNING_PER_HOUR = 15_000

# --- Gambling / Casino V2 compatibility aliases ---
# A payoutok tényleges source-of-truth fájlja: app/casino_config.py
from app import casino_config as casino

GAMBLING_MIN_BET = casino.MIN_BET
COINFLIP_TOTAL_PAYOUT = casino.COINFLIP_TOTAL_PAYOUT
DICE_TOTAL_PAYOUT = casino.DICE_TOTAL_PAYOUT
ROULETTE_EVEN_TOTAL_PAYOUT = casino.ROULETTE_EVEN_TOTAL_PAYOUT
ROULETTE_SINGLE_TOTAL_PAYOUT = casino.ROULETTE_SINGLE_TOTAL_PAYOUT
CHICKEN_WIN_CHANCE = casino.CHICKEN_WIN_CHANCE
CHICKEN_TOTAL_PAYOUT = casino.CHICKEN_TOTAL_PAYOUT
HIGHLOW_TOTAL_PAYOUT = casino.HIGHLOW_TOTAL_PAYOUT
RPS_TOTAL_PAYOUT = casino.RPS_TOTAL_PAYOUT
BLACKJACK_WIN_TOTAL_PAYOUT = casino.BLACKJACK_WIN_TOTAL_PAYOUT
SLOTS_SYMBOLS = casino.SLOTS_SYMBOLS
SLOTS_WEIGHTS = casino.SLOTS_WEIGHTS
SLOTS_PAIR_TOTAL_PAYOUT = casino.SLOTS_PAIR_TOTAL_PAYOUT
SLOTS_TRIPLE_TOTAL_PAYOUT = casino.SLOTS_TRIPLE_TOTAL_PAYOUT

# --- Sorsjegy / lootbox ---
SCRATCH_TIERS = (
    (0.48, "💨 Üres", 0, 0),
    (0.79, "⚪ Kis nyeremény", 15_000, 25_000),
    (0.94, "🔵 Szép nyeremény", 30_000, 60_000),
    (0.99, "🟣 Nagy nyeremény", 80_000, 160_000),
    (1.00, "🟡 JACKPOT", 300_000, 600_000),
)
BOOSTER_DEFINITIONS = {
    "work_booster": ("🛠️ Work Booster", 1.30, 2),
    "crime_booster": ("🕵️ Crime Booster", 1.25, 4),
    "luck_booster": ("🍀 Luck Booster", 1.30, 1),
    "interest_booster": ("🏦 Interest Booster", 1.25, 24),
    "rob_booster": ("🥷 Rob Booster", 1.25, 1),
}
SCRATCH_LUCK_STRENGTH = 0.10
CRATE_LUCK_STRENGTH = 0.30
LUCKY_CHARM_MULTIPLIER = 1.15
LUCKY_CHARM_MAX_BONUS = 500_000
# Ládanyitás payout eloszlás: tier-esélyek és a crate maximumához viszonyított sávok.
CRATE_TIER_1_THRESHOLD = 0.65
CRATE_TIER_2_THRESHOLD = 0.93
CRATE_TIER_1_MAX_RATIO = 0.35
CRATE_TIER_2_MIN_RATIO = 0.30
CRATE_TIER_2_MAX_RATIO = 0.70
CRATE_TIER_3_MIN_RATIO = 0.65

# Base EV kb. 86–88% a shopárhoz képest.
CRATE_DEFINITIONS = {
    "mystery_box": (30_000, 520_000, "🔵 Mystery"),
    "common_crate": (20_000, 260_000, "⚪ Common"),
    "rare_crate": (60_000, 1_040_000, "🔵 Rare"),
    "epic_crate": (200_000, 4_000_000, "🟣 Epic"),
    "legendary_crate": (500_000, 13_500_000, "🟡 Legendary"),
    "mythic_crate": (1_500_000, 40_000_000, "🔴 Mythic"),
}

# --- Community gambling / investment ---
JACKPOT_MIN_ENTRY = 5_000
JACKPOT_SECONDS = 60
JACKPOT_PAYOUT_SHARE = 0.95
LOTTERY_TICKET_PRICE = 25_000
LOTTERY_INTERVAL_HOURS = 1
LOTTERY_PAYOUT_SHARE = 0.90
LOTTERY_MIN_POT = 25_000
LOTTERY_MAX_TICKETS_PER_BUY = 1_000

INVEST_COOLDOWN_HOURS = 4
INVEST_MIN_AMOUNT = 10_000
INVEST_MIN_LOSS_RATE = 0.10
INVEST_MODES = {
    "low": (0.61, 0.04, 0.10, 0.18, "Alacsony"),
    "medium": (0.49, 0.12, 0.28, 0.45, "Közepes"),
    "high": (0.37, 0.30, 0.70, 0.75, "Magas"),
}

# --- Szerver economy eventek / Feketepiac ---
GUILD_ECONOMY_EVENT_MIN_HOURS = 1.0
GUILD_ECONOMY_EVENT_MAX_HOURS = 4.0
GUILD_ECONOMY_EVENT_DURATION_HOURS = 1
GUILD_EVENT_WORK_MULTIPLIER = 1.50
GUILD_EVENT_CRIME_MULTIPLIER = 1.25
GUILD_EVENT_LUCK_MULTIPLIER = 1.15
BLACK_MARKET_PRICE_MULTIPLIER = (0.70, 0.85)
BLACK_MARKET_DURATION_MINUTES = 15

# --- Auto event economy ---
# Az időzítés/aktivitás envből konfigurálható; a PÉNZ balance itt él.
AUTO_EVENT_MIN_SECONDS = 15 * 60
AUTO_EVENT_MAX_SECONDS = 90 * 60
EVENT_MIN_REWARD = 1_000
EVENT_JOIN_MIN_SECONDS = 15
EVENT_JOIN_MAX_SECONDS = 600
BOMB_MIN_ENTRY = 5_000
BOMB_ROUND_MIN_SECONDS = 5
BOMB_ROUND_MAX_SECONDS = 120
AUTO_EVENT_JOIN_SECONDS = 30
AUTO_SAFE_MIN_REWARD = 100_000
AUTO_SAFE_MAX_REWARD = 500_000
AUTO_BOMB_MIN_ENTRY = 25_000
AUTO_BOMB_MAX_ENTRY = 150_000
AUTO_BOMB_ROUND_SECONDS = 15
AUTO_EVENT_SAFE_CHANCE = 0.40
AUTO_EVENT_ACTIVITY_MESSAGES = 20
AUTO_EVENT_ACTIVITY_WINDOW_MINUTES = 30
AUTO_EVENT_ACTIVITY_MIN_USERS = 4
AUTO_EVENT_ACTIVITY_USER_COOLDOWN_SECONDS = 5

# --- Premium rewardok ---
PREMIUM_REWARD_RULES = {
    "nitro_basic_1m": {
        "price": 500_000_000,
        "min_account_age_days": 30,
        "min_level": 35,
        "personal_cooldown_days": 30,
        "guild_monthly_stock": 4,
    },
    "discord_nitro_1m": {
        "price": 750_000_000,
        "min_account_age_days": 45,
        "min_level": 45,
        "personal_cooldown_days": 30,
        "guild_monthly_stock": 2,
    },
}

# --- Egyszerű Silver / Gold / Diamond market ---
MARKET_ASSETS = {
    "silver": {"min_price": 75_000, "max_price": 150_000, "min_stock": 40, "max_stock": 90},
    "gold": {"min_price": 500_000, "max_price": 1_000_000, "min_stock": 8, "max_stock": 24},
    "diamond": {"min_price": 2_000_000, "max_price": 4_000_000, "min_stock": 2, "max_stock": 8},
}
MARKET_SELL_RATIO = 0.90

# --- Shop ---
SHOP_SELL_RATIO = 0.50

SHOP_PRICES = {
    "lottery_ticket": 25_000,
    "chicken": 50_000,
    "common_crate": 100_000,
    "work_booster": 150_000,
    "mystery_box": 200_000,
    "crime_booster": 200_000,
    "lucky_charm": 250_000,
    "rare_crate": 400_000,
    "interest_booster": 500_000,
    "rob_shield": 1_000_000,
    "luck_booster": 1_500_000,
    "epic_crate": 1_500_000,
    "rob_booster": 2_000_000,
    "legendary_crate": 5_000_000,
    "mythic_crate": 15_000_000,
    "silver": 100_000,
    "gold": 750_000,
    "diamond": 3_000_000,
    "nitro_basic_1m": PREMIUM_REWARD_RULES["nitro_basic_1m"]["price"],
    "discord_nitro_1m": PREMIUM_REWARD_RULES["discord_nitro_1m"]["price"],
}

# --- Crew / Prestige (szintén innen hangolható) ---
CREW_CREATE_COST = 2_000_000
CREW_UPGRADE_COSTS = {1: 5_000_000, 2: 15_000_000, 3: 40_000_000, 4: 100_000_000}
CREW_INCOME_BONUS = {1: 0.00, 2: 0.01, 3: 0.02, 4: 0.035, 5: 0.05}
PRESTIGE_LEVEL_BASE = 50
PRESTIGE_LEVEL_STEP = 10
PRESTIGE_WEALTH_BASE = 35_000_000
PRESTIGE_WEALTH_GROWTH = 1.85
PRESTIGE_INCOME_BONUS_PER_LEVEL = 0.04
PRESTIGE_INCOME_BONUS_CAP = 0.40

# --- Quest pénzjutalmak ---
QUEST_MONEY_REWARDS = {
    "daily_small": 10_000,
    "daily_medium": 20_000,
    "daily_large": 30_000,
    "weekly_small": 75_000,
    "weekly_medium": 125_000,
    "weekly_large": 200_000,
}

# --- Wealth progression mérföldkövek ---
WEALTH_ACHIEVEMENT_TARGETS = {
    "millionaire": 1_000_000,
    "ten_million": 5_000_000,
    "wealth_1b": 25_000_000,
    "wealth_5b": 100_000_000,
}

# --- Search item dropok ---
# Prémium reward (Nitro) SOHA nem esik searchből.
SEARCH_ITEM_DROPS = [
    ("lottery_ticket", 0.0120),
    ("chicken", 0.0060),
    ("silver", 0.0030),
    ("common_crate", 0.0080),
    ("mystery_box", 0.0040),
    ("rob_shield", 0.0015),
    ("lucky_charm", 0.0012),
    ("rare_crate", 0.0012),
    ("gold", 0.00030),
    ("work_booster", 0.0010),
    ("crime_booster", 0.0009),
    ("luck_booster", 0.0005),
    ("interest_booster", 0.0004),
    ("rob_booster", 0.0003),
    ("epic_crate", 0.00025),
    ("legendary_crate", 0.00005),
    ("diamond", 0.00003),
    ("mythic_crate", 0.000005),
]

SLUT_SUCCESS_MESSAGES = [
    "Egy gazdag vendég bőkezű borravalót hagyott.",
    "A VIP vendég úgy döntött, ma nem spórol.",
    "A szállodai este meglepően jövedelmező lett.",
    "Egy sugar daddy túl komolyan vette a borravaló fogalmát.",
    "A vendég öt csillagot adott, te pedig vastag borítékot kaptál.",
    "Egy titokzatos üzletember készpénzzel rendezte a számlát.",
    "A luxushotelben ma neked állt a zászló.",
    "A vendég azt mondta, tartsd meg az aprót. Az apró egy vagyon volt.",
    "Egy túl lelkes rajongó prémium csomagot kért.",
    "Az éjszakai műszak végül sokkal jobban fizetett, mint tervezted.",
]

SLUT_FAIL_MESSAGES = [
    "Megakadt a torkodon egy Viagra, ezért a vendég inkább hazament.",
    "A vendég fizetés helyett futóversenyt rendezett az ajtóig.",
    "Rossz hotelszobába kopogtál be, és még a minibárt is rád terhelték.",
    "A rendőrségi razzia pont a legrosszabbkor érkezett.",
    "Kiderült, hogy Monopoly-pénzzel akart fizetni.",
    "A vendég párja hamarabb ért haza a vártnál. A taxi drága volt.",
    "A szálloda kidobott, és még takarítási díjat is felszámolt.",
    "Az egész este végén csak egy rossz értékelést és egy számlát kaptál.",
    "A vendég azt mondta, majd utal. Nem utalt.",
    "Összekeverted a szobaszámot, és a recepció még büntetést is rád vert.",
]
