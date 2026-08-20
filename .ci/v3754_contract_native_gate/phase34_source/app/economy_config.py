from __future__ import annotations

from app import shop_config as shop_cfg

from datetime import timedelta

# ============================================================
# YORU v3.55.0 — CENTRAL BALANCE CONFIG
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
STARTING_BALANCE = 75_000
# --- Cooldownok ---
DAILY_COOLDOWN = timedelta(hours=24)
WEEKLY_COOLDOWN = timedelta(days=7)
MONTHLY_COOLDOWN = timedelta(days=30)
WORK_COOLDOWN = timedelta(minutes=8)
CRIME_COOLDOWN = timedelta(minutes=10)
SEARCH_COOLDOWN = timedelta(minutes=15)
BEG_COOLDOWN = timedelta(minutes=5)
ROB_COOLDOWN = timedelta(hours=2)
WITHDRAW_ROB_PROTECTION = timedelta(minutes=5)
SLUT_COOLDOWN = timedelta(minutes=10)
INTEREST_COOLDOWN = timedelta(hours=6)
WEEKLY_MIN_ACCOUNT_AGE_DAYS = 7
MONTHLY_MIN_ACCOUNT_AGE_DAYS = 30

# Prefix anti-flood: a gyors Ctrl+C/Ctrl+V spam nem fut le újra és újra.
PREFIX_ACTION_MIN_INTERVAL_SECONDS = 1.25

# --- Stabil aktív income ---
# A Daily és Monthly többé nem free-money claim. A konstansok csak legacy kompatibilitásból 0-k.
DAILY_REWARD = (0, 0)
WEEKLY_REWARD = (300_000, 450_000)  # heti összegzéskor ennek 1/5-e a kis kiegészítés
MONTHLY_REWARD = (0, 0)

# Első RP economy baseline: az alkalmi munka átlagosan ~85k / 8 perc.
# Ez Miskolcon kb. 26 perc alatt teszi elérhetővé a Szállót, miközben
# a B jogsi és az első olcsó autó már többórás mérföldkő marad.
WORK_REWARD = (50_000, 120_000)
WORK_JOBS = [
    ("pizzát szállítottál ki", 55_000, 82_000),
    ("egy raktárban pakoltál", 65_000, 98_000),
    ("autókat szereltél", 72_000, 108_000),
    ("egy weboldalon dolgoztál", 85_000, 120_000),
    ("takarítottál egy irodában", 55_000, 80_000),
    ("kutyákat sétáltattál", 52_000, 75_000),
    ("egy étteremben mosogattál", 60_000, 88_000),
    ("csomagokat kézbesítettél", 65_000, 100_000),
    ("egy koncerten biztonsági őr voltál", 75_000, 112_000),
    ("videókat vágtál egy streamernek", 82_000, 120_000),
    ("egy építkezésen segítettél", 70_000, 108_000),
    ("éjszakai műszakot vállaltál", 85_000, 120_000),
]

# Utcai opportunityk: kiegészítő pénzforrások, nem alternatív főállások.
BEG_OUTCOMES = [
    ("Egy járókelő megsajnált", 3_000, 10_000),
    ("Egy gazdag üzletember adott egy kis aprót", 7_000, 22_000),
    ("Találtál néhány érmét a földön", 2_000, 8_000),
    ("Egy idős néni kisegített", 4_000, 14_000),
    ("Senki sem állt meg melletted", 0, 0),
]

SEARCH_PLACES = [
    ("a kanapé párnái között", 4_000, 16_000),
    ("egy elhagyott hátizsákban", 8_000, 34_000),
    ("a parkolóban", 4_000, 20_000),
    ("egy automata alatt", 3_000, 14_000),
    ("a régi kabátod zsebében", 5_000, 22_000),
    ("egy sikátorban", 10_000, 60_000),
    ("a buszmegálló mellett", 4_000, 18_000),
    ("egy poros fiókban", 6_000, 28_000),
]

# Bűnözés: gyorsabb vagyonépítési út, de nagyobb szórással és következménnyel.
CRIME_REWARD = (180_000, 480_000)
CRIME_FINE = (140_000, 380_000)
CRIME_SCENARIOS = [
    ("feltörtél egy italautomatát", 0.75),
    ("elloptál egy biciklit", 0.72),
    ("meghekkeltél egy parkolóórát", 0.70),
    ("kirámoltál egy kisboltot", 0.66),
    ("elloptál egy autót", 0.58),
    ("kifosztottál egy raktárt", 0.62),
    ("hamis jegyeket adtál el", 0.69),
    ("kaszinózsetonokat csempésztél ki", 0.56),
]
CRIME_JAIL_CHANCE = 0.35
CRIME_JAIL_MIN_MINUTES = 5
CRIME_JAIL_MAX_MINUTES = 12

SLUT_SUCCESS_CHANCE = 0.60
SLUT_REWARD = (90_000, 260_000)
SLUT_FINE = (80_000, 220_000)

# Rob: vagyon-átrendezés, nem pénznyomtatás. A sikeres steal share kifejezetten 60%.
ROB_SUCCESS_SHARE = 0.60
ROB_SUCCESS_CHANCE = 0.25
ROB_BOOSTED_MAX_CHANCE = 0.35
ROB_FAIL_FINE = (60_000, 250_000)
ROB_FAIL_FINE_SHARE = (0.15, 0.25)
ROB_MIN_COVERAGE_SHARE = 0.05
ROB_MIN_ATTEMPT_WALLET = 100_000
ROB_MIN_VICTIM_WALLET = 250_000

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

# --- Community gambling ---
JACKPOT_MIN_ENTRY = 5_000
JACKPOT_SECONDS = 60
JACKPOT_PAYOUT_SHARE = 0.95
LOTTERY_TICKET_PRICE = 25_000
LOTTERY_INTERVAL_HOURS = 1
LOTTERY_PAYOUT_SHARE = 0.90
LOTTERY_MIN_POT = 25_000
LOTTERY_MAX_TICKETS_PER_BUY = 1_000


# --- Feketepiac kínálati beállítások ---
BLACK_MARKET_PRICE_MULTIPLIER = (0.70, 0.85)

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

# --- Shop árak: canonical source = app/shop_config.py ---
SHOP_PRICES = dict(shop_cfg.SHOP_PRICES)


# --- Befektetések • napi piac ---
# A spread eszközönként eltér: a stabilabb eszköz olcsóbban fordítható vissza,
# a spekulatívabb pozícióknál nagyobb a rövid távú veszteség. Ez természetes
# pénznyelő, miközben nem tiltja meg a hosszabb távú nyereséget.
MARKET_ASSETS = {
    "silver": {"min_price": 75_000, "max_price": 150_000, "min_stock": 40, "max_stock": 90, "sell_ratio": 0.95},
    "gold": {"min_price": 500_000, "max_price": 1_000_000, "min_stock": 8, "max_stock": 24, "sell_ratio": 0.94},
    "diamond": {"min_price": 2_000_000, "max_price": 4_000_000, "min_stock": 2, "max_stock": 8, "sell_ratio": 0.92},
    "bond_fund": {"min_price": 900_000, "max_price": 1_100_000, "min_stock": 30, "max_stock": 70, "sell_ratio": 0.98},
    "duna_index": {"min_price": 2_500_000, "max_price": 4_000_000, "min_stock": 12, "max_stock": 30, "sell_ratio": 0.96},
    "real_estate_fund": {"min_price": 7_000_000, "max_price": 10_000_000, "min_stock": 6, "max_stock": 16, "sell_ratio": 0.96},
    "tech_fund": {"min_price": 12_000_000, "max_price": 24_000_000, "min_stock": 3, "max_stock": 9, "sell_ratio": 0.94},
    "crypto_index": {"min_price": 25_000_000, "max_price": 75_000_000, "min_stock": 1, "max_stock": 5, "sell_ratio": 0.90},
}
MARKET_SELL_RATIO = 0.90  # legacy/fallback; a normál piac eszközönkénti spreadet használ.

# --- Shop ---
SHOP_SELL_RATIO = 0.50


# --- Szervezet alapértékek ---
CREW_CREATE_COST = 2_000_000
CREW_UPGRADE_COSTS = {1: 5_000_000, 2: 15_000_000, 3: 40_000_000, 4: 100_000_000}


# --- Wealth progression mérföldkövek ---
WEALTH_ACHIEVEMENT_TARGETS = {
    "millionaire": 1_000_000,
    "ten_million": 10_000_000,
    "wealth_1b": 1_000_000_000,
    "wealth_5b": 5_000_000_000,
}

# --- Search item dropok ---
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
