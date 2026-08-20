from __future__ import annotations

from dataclasses import dataclass

JOBS_ENABLED_KEY = "jobs_enabled"
JOB_ENABLED_PREFIX = "jobs_enabled_"
JOBS_LOG_CHANNEL_KEY = "jobs_log_channel_id"
JOB_REWARD_MULTIPLIER_KEY = "jobs_reward_multiplier_bp"  # 10000 = 1.00x

DEFAULT_REWARD_MULTIPLIER_BP = 10_000
MAX_MASTERY_LEVEL = 50
SESSION_TIMEOUT_SECONDS = 300

# One shared Career shift cooldown. Alkalmi munka keeps its own short cooldown.
JOB_COOLDOWN_SECONDS = 30 * 60
ABANDON_COOLDOWN_SECONDS = 10 * 60

# Borsodi Lopkodás is an illegal activity, not employment. Its pacing must not
# lock or be locked by a legal Career V2 shift.
BORSOD_COOLDOWN_SECONDS = 30 * 60
BORSOD_ABANDON_COOLDOWN_SECONDS = 10 * 60

# Decision windows are intentionally generous: Jobs are decisions, not reflex tests.
DECISION_TIMEOUT_SECONDS = 30.0
WAREHOUSE_ANIMATION_SECONDS = 2.8
SHIFT_INTRO_SECONDS = 1.6
WAREHOUSE_MEMORIZE_SECONDS = 5.5
WAREHOUSE_DECISION_TIMEOUT_SECONDS = 35.0
BORSOD_DECISION_TIMEOUT_SECONDS = 30.0
TRANSPORT_DECISION_TIMEOUT_SECONDS = 30.0
ROUTE_ANIMATION_HOLD_SECONDS = 2.9
BORSOD_REVEAL_HOLD_SECONDS = 2.1

ACTIVE_CITIES = ("miskolc", "eger", "szeged", "debrecen", "budapest")


@dataclass(frozen=True, slots=True)
class JobDefinition:
    key: str
    name: str
    emoji: str
    description: str
    accent: tuple[int, int, int]
    base_mastery_xp: int


@dataclass(frozen=True, slots=True)
class CareerDefinition:
    key: str
    name: str
    emoji: str
    employer: str
    summary: str
    cities: tuple[str, ...]
    pay_min: int
    pay_max: int
    qualification_key: str | None = None
    qualification_name: str | None = None
    min_housing_tier: str | None = None
    vehicle_role: str | None = None
    specialized_job: str | None = None


# Legal work experience source-of-truth. Borsodi Lopkodás is deliberately not
# in this tuple: it remains a crime activity for compatibility/history only.
JOBS: tuple[JobDefinition, ...] = (
    JobDefinition("warehouse", "Raktáros", "📦", "Áruátvétel, sorrendek és változó raktári helyzetek.", (84, 120, 255), 44),
    JobDefinition("shelf_stocker", "Árufeltöltő", "🛒", "Polcok, készlet és vevői helyzetek egy pörgős műszakban.", (70, 165, 120), 38),
    JobDefinition("cleaner", "Takarító", "🧹", "Területek, sürgős kérések és váratlan műszakhelyzetek.", (88, 160, 185), 36),
    JobDefinition("kitchen_helper", "Konyhai kisegítő", "🍽️", "Előkészítés, mosogatás és konyhai prioritások.", (220, 145, 70), 40),
    JobDefinition("factory_operator", "Gyári operátor", "🏭", "Termelési ütem, minőség és műszak közbeni döntések.", (145, 135, 180), 44),
    JobDefinition("courier", "Futár", "🚚", "Útvonalak, spontán események és helyzetfüggő döntések.", (81, 190, 145), 48),
    JobDefinition("taxi", "Taxi", "🚕", "Fuvarok, spontán fordulatok, borravaló és teljesítmény.", (247, 204, 70), 48),
    JobDefinition("forklift_operator", "Targoncás", "🏗️", "Nagyobb felelősségű raktári és rakodási feladatok.", (215, 160, 55), 52),
    JobDefinition("security_guard", "Vagyonőr", "🛡️", "Beléptetés, objektumvédelem és konfliktushelyzetek.", (82, 105, 150), 52),
    JobDefinition("hospitality", "Vendéglátós", "🍹", "Vendégek, rendelési helyzetek és esti pörgés.", (205, 95, 145), 50),
)

BORSOD_JOB = JobDefinition(
    "borsod", "Borsodi Lopkodás", "🔌",
    "5×5 keresési terület • váratlan helyzetek • illegális ügy.",
    (240, 165, 50), 42,
)

JOB_BY_KEY = {j.key: j for j in (*JOBS, BORSOD_JOB)}
LEGAL_JOB_KEYS = frozenset(j.key for j in JOBS)

# Active employment catalog. An employment is city-bound: travelling away does
# not delete the job, but a shift can only be started in the employment city.
CAREERS: tuple[CareerDefinition, ...] = (
    CareerDefinition(
        "shelf_stocker", "Árufeltöltő", "🛒", "Helyi szupermarket",
        "Belépőszintű kereskedelmi állás. Képesítés nélkül is vállalható.",
        ACTIVE_CITIES, 235_000, 330_000,
    ),
    CareerDefinition(
        "cleaner", "Takarító", "🧹", "Városi szolgáltató",
        "Egyszerű belépőszintű munka, változó helyszínekkel és prioritásokkal.",
        ACTIVE_CITIES, 225_000, 320_000,
    ),
    CareerDefinition(
        "kitchen_helper", "Konyhai kisegítő", "🍽️", "Belvárosi étterem",
        "Konyhai belépőállás. Jó ugródeszka a vendéglátós pálya felé.",
        ACTIVE_CITIES, 245_000, 345_000,
    ),
    CareerDefinition(
        "factory_operator", "Gyári operátor", "🏭", "Ipari üzem",
        "Termelési alapmunka. Stabil, de a műszak közben figyelni kell a minőségre.",
        ("miskolc", "szeged", "debrecen", "budapest"), 270_000, 380_000,
    ),
    CareerDefinition(
        "warehouse", "Raktáros", "📦", "Logisztikai központ",
        "Áruátvétel és raktári műszak. Képesítés nélkül elkezdhető.",
        ("miskolc", "eger", "szeged", "debrecen", "budapest"), 285_000, 410_000,
        specialized_job="warehouse",
    ),
    CareerDefinition(
        "courier", "Futár", "🚚", "Yoru Express",
        "Saját, vezethető járművel végzett városi kézbesítés.",
        ACTIVE_CITIES, 315_000, 455_000,
        qualification_key="driving_b", qualification_name="B kategóriás jogosítvány",
        vehicle_role="courier", specialized_job="courier",
    ),
    CareerDefinition(
        "taxi", "Taxi", "🚕", "Városi Taxi",
        "Saját személyautóval végzett fuvarozás.",
        ACTIVE_CITIES, 330_000, 480_000,
        qualification_key="driving_b", qualification_name="B kategóriás jogosítvány",
        vehicle_role="taxi", specialized_job="taxi",
    ),
    CareerDefinition(
        "forklift_operator", "Targoncás", "🏗️", "Logisztikai központ",
        "Magasabb felelősségű raktári állás targoncavezetői képesítéssel.",
        ("miskolc", "szeged", "debrecen", "budapest"), 350_000, 500_000,
        qualification_key="forklift", qualification_name="Targoncavezetői képesítés",
    ),
    CareerDefinition(
        "security_guard", "Vagyonőr", "🛡️", "Őrzés-védelmi szolgálat",
        "Objektumvédelem és beléptetés. Képesítés és stabil lakcím szükséges.",
        ACTIVE_CITIES, 340_000, 495_000,
        qualification_key="security", qualification_name="Vagyonőri képesítés",
        min_housing_tier="shelter",
    ),
    CareerDefinition(
        "hospitality", "Vendéglátós", "🍹", "Szálloda és rendezvényhelyszín",
        "Pult, felszolgálás és vendégkezelés képzett dolgozóknak.",
        ("eger", "szeged", "debrecen", "budapest"), 325_000, 475_000,
        qualification_key="hospitality", qualification_name="Vendéglátói képesítés",
    ),
)
CAREER_BY_KEY = {item.key: item for item in CAREERS}

RATING_ORDER = ("D", "C", "B", "A", "S")
RATING_SCORE = {"D": 0, "C": 45, "B": 62, "A": 78, "S": 92}


def mastery_level_for_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = 1
    spent = 0
    while level < MAX_MASTERY_LEVEL:
        need = 90 + (level - 1) * 22 + ((level - 1) ** 2) * 2
        if xp < spent + need:
            break
        spent += need
        level += 1
    return level


def mastery_progress(xp: int) -> tuple[int, int, int]:
    xp = max(0, int(xp))
    level = mastery_level_for_xp(xp)
    spent = 0
    for lv in range(1, level):
        spent += 90 + (lv - 1) * 22 + ((lv - 1) ** 2) * 2
    if level >= MAX_MASTERY_LEVEL:
        return level, 1, 1
    need = 90 + (level - 1) * 22 + ((level - 1) ** 2) * 2
    return level, max(0, xp - spent), need


def rating_for_score(score: int) -> str:
    score = max(0, min(100, int(score)))
    if score >= 92:
        return "S"
    if score >= 78:
        return "A"
    if score >= 62:
        return "B"
    if score >= 45:
        return "C"
    return "D"


# Experience no longer multiplies salary. It changes the player's natural
# position label and unlocks richer shift situations instead of becoming a
# visible/invisible +X% income stat.
EXPERIENCE_TIERS: tuple[tuple[int, str], ...] = (
    (35, "Elismert"),
    (23, "Rutinos"),
    (12, "Tapasztalt"),
    (5, "Gyakorlott"),
    (1, "Újonc"),
)

POSITION_TIERS: tuple[tuple[int, str], ...] = (
    (35, "Műszakvezető"),
    (23, "Senior munkatárs"),
    (12, "Önálló munkatárs"),
    (5, "Betanult munkatárs"),
    (1, "Új belépő"),
)


def experience_tier(level_or_xp: int, *, is_xp: bool = False) -> str:
    level = mastery_level_for_xp(int(level_or_xp)) if is_xp else max(1, int(level_or_xp))
    for minimum, label in EXPERIENCE_TIERS:
        if level >= minimum:
            return label
    return "Újonc"


def position_tier(level_or_xp: int, *, is_xp: bool = False) -> str:
    level = mastery_level_for_xp(int(level_or_xp)) if is_xp else max(1, int(level_or_xp))
    for minimum, label in POSITION_TIERS:
        if level >= minimum:
            return label
    return "Új belépő"


def career(key: str) -> CareerDefinition:
    try:
        return CAREER_BY_KEY[str(key)]
    except KeyError as exc:
        raise ValueError("Ismeretlen állás.") from exc


def career_pay(key: str) -> tuple[int, int]:
    item = career(key)
    return int(item.pay_min), int(item.pay_max)
