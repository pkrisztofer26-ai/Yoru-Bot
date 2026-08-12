from __future__ import annotations

from dataclasses import dataclass

BUSINESS_ENABLED_KEY = "business_enabled"
BUSINESS_ACTIVITY_LEVEL_KEY = "business_required_activity_level"
BUSINESS_PRESTIGE_KEY = "business_required_prestige"
BUSINESS_LICENSE_PRICE_KEY = "business_license_price"
BUSINESS_TAX_PERCENT_KEY = "business_tax_percent"
BUSINESS_OFFLINE_CAP_HOURS_KEY = "business_offline_cap_hours"
BUSINESS_BASE_PROPERTY_CAP_KEY = "business_base_property_cap"
BUSINESS_PRESTIGE_STEP_KEY = "business_prestige_step"
BUSINESS_ABSOLUTE_CAP_KEY = "business_absolute_property_cap"
BUSINESS_CITY_CAP_KEY = "business_city_property_cap"
BUSINESS_INCOME_MULTIPLIER_KEY = "business_income_multiplier_percent"
BUSINESS_WORKER_DAYS_KEY = "business_worker_contract_days"

DEFAULT_ENABLED = True
DEFAULT_REQUIRED_ACTIVITY_LEVEL = 20
DEFAULT_REQUIRED_PRESTIGE = 1
DEFAULT_LICENSE_PRICE = 15_000_000
DEFAULT_TAX_PERCENT = 12
DEFAULT_OFFLINE_CAP_HOURS = 24
DEFAULT_BASE_PROPERTY_CAP = 3
DEFAULT_PRESTIGE_STEP = 2
DEFAULT_ABSOLUTE_CAP = 8
DEFAULT_CITY_CAP = 2
DEFAULT_INCOME_MULTIPLIER_PERCENT = 100
DEFAULT_WORKER_CONTRACT_DAYS = 7

MIN_LICENSE_PRICE = 100_000
MAX_LICENSE_PRICE = 10_000_000_000_000
MIN_TAX_PERCENT = 0
MAX_TAX_PERCENT = 60
MIN_OFFLINE_CAP_HOURS = 1
MAX_OFFLINE_CAP_HOURS = 168
MIN_PROPERTY_CAP = 1
MAX_PROPERTY_CAP = 20
MIN_PRESTIGE_STEP = 1
MAX_PRESTIGE_STEP = 20
MIN_INCOME_MULTIPLIER_PERCENT = 25
MAX_INCOME_MULTIPLIER_PERCENT = 500
MIN_WORKER_CONTRACT_DAYS = 1
MAX_WORKER_CONTRACT_DAYS = 30

MAX_BUSINESS_LEVEL = 5
MAX_REPUTATION = 1000
PROPERTY_OFFER_HOURS = 24
PROPERTY_TRANSFER_TAX_PERCENT = 4
FACTION_BONUS_PERCENT = 2
FACTION_XP_PER_CLAIM = 25


def upgrade_cost(base_price: int, current_level: int) -> int:
    current_level = max(1, min(MAX_BUSINESS_LEVEL, int(current_level)))
    return int(base_price * (0.30 + 0.18 * (current_level - 1)))


def upgrade_required_reputation(current_level: int) -> int:
    # Requirement for upgrading FROM current_level TO current_level + 1.
    return max(0, 80 * int(current_level) * int(current_level - 1))


@dataclass(frozen=True)
class PropertyTemplate:
    key: str
    name: str
    emoji: str
    category: str
    city: str
    district: str
    street: str
    base_price: int
    hourly_revenue: int
    hourly_upkeep: int
    max_workers: int


# Real Hungarian place/street labels are used only as game-world flavour.
# Every business/property name is fictional.
PROPERTY_TEMPLATES: tuple[PropertyTemplate, ...] = (
    PropertyTemplate("miskolc_holdfeny", "Holdfény Kávéház", "☕", "Vendéglátás", "Miskolc", "Belváros", "Széchenyi István út", 28_000_000, 190_000, 24_000, 2),
    PropertyTemplate("eger_vorosmacska", "Vörös Macska Bistro", "🍽️", "Vendéglátás", "Eger", "Belváros", "Dobó tér", 36_000_000, 245_000, 31_000, 2),
    PropertyTemplate("nyh_pixelpek", "PixelPék", "🥐", "Vendéglátás", "Nyíregyháza", "Belváros", "Kossuth tér", 32_000_000, 220_000, 28_000, 2),
    PropertyTemplate("pecs_tulipan", "Fekete Tulipán Boutique", "🛍️", "Kereskedelem", "Pécs", "Belváros", "Király utca", 48_000_000, 315_000, 43_000, 2),
    PropertyTemplate("deb_aranykakas", "Aranykakas Grill", "🍗", "Vendéglátás", "Debrecen", "Belváros", "Piac utca", 56_000_000, 370_000, 48_000, 3),
    PropertyTemplate("szeged_tiszatech", "Tisza Tech Repair", "🔧", "Szolgáltatás", "Szeged", "Belváros", "Kárász utca", 62_000_000, 405_000, 52_000, 3),
    PropertyTemplate("gyor_novafit", "Nova Fitness", "🏋️", "Szolgáltatás", "Győr", "Belváros", "Baross Gábor út", 78_000_000, 510_000, 72_000, 3),
    PropertyTemplate("deb_keletiauto", "Keleti Autókozmetika", "🚗", "Szolgáltatás", "Debrecen", "Belváros", "Hatvan utca", 88_000_000, 575_000, 82_000, 3),
    PropertyTemplate("bp_yoruarcade", "Yoru Arcade", "🕹️", "Szórakozás", "Budapest", "XI. kerület", "Bartók Béla út", 98_000_000, 640_000, 91_000, 4),
    PropertyTemplate("bp_neonbyte", "NeonByte Studio", "💻", "Technológia", "Budapest", "XIII. kerület", "Váci út", 125_000_000, 820_000, 118_000, 4),
    PropertyTemplate("szeged_paprikanet", "Paprika Labs", "🧪", "Technológia", "Szeged", "Belváros", "Tisza Lajos körút", 145_000_000, 940_000, 136_000, 4),
    PropertyTemplate("miskolc_borsodlog", "Borsod Logistics", "🚚", "Logisztika", "Miskolc", "Belváros", "Szentpáli utca", 165_000_000, 1_060_000, 165_000, 4),
    PropertyTemplate("pecs_mecsekevent", "Mecsek Event Hall", "🎟️", "Rendezvény", "Pécs", "Belváros", "Rákóczi út", 195_000_000, 1_230_000, 198_000, 5),
    PropertyTemplate("eger_lofthotel", "Egri Loft Hotel", "🏨", "Turizmus", "Eger", "Belváros", "Széchenyi István utca", 215_000_000, 1_360_000, 225_000, 5),
    PropertyTemplate("bp_midnightmedia", "Midnight Media HQ", "🎬", "Média", "Budapest", "VII. kerület", "Rákóczi út", 260_000_000, 1_640_000, 285_000, 5),
)


@dataclass(frozen=True)
class WorkerDefinition:
    key: str
    name: str
    emoji: str
    tier: str
    revenue_bonus_percent: int
    hire_fee: int
    wage_per_hour: int


WORKERS: tuple[WorkerDefinition, ...] = (
    WorkerDefinition("anna", "Anna • Üzletvezető", "👩‍💼", "Profi", 12, 2_500_000, 24_000),
    WorkerDefinition("balazs", "Balázs • Értékesítő", "🧑‍💼", "Profi", 10, 2_000_000, 19_000),
    WorkerDefinition("lili", "Lili • Social Manager", "📱", "Szakértő", 18, 4_500_000, 38_000),
    WorkerDefinition("mate", "Máté • Operációs vezető", "📊", "Szakértő", 20, 5_200_000, 44_000),
    WorkerDefinition("nora", "Nóra • Könyvelő", "🧾", "Profi", 8, 1_800_000, 16_000),
    WorkerDefinition("dani", "Dani • Technikus", "🛠️", "Haladó", 7, 1_250_000, 12_000),
    WorkerDefinition("zsofi", "Zsófi • Brand Designer", "🎨", "Haladó", 9, 1_600_000, 14_000),
    WorkerDefinition("bence", "Bence • Logisztikus", "📦", "Haladó", 8, 1_450_000, 13_000),
    WorkerDefinition("eszter", "Eszter • Host", "✨", "Profi", 11, 2_250_000, 20_000),
    WorkerDefinition("marci", "Marci • Junior", "🧑‍🔧", "Tanonc", 5, 650_000, 7_000),
)
WORKER_BY_KEY = {worker.key: worker for worker in WORKERS}
