from __future__ import annotations

from dataclasses import dataclass

HEIST_ENABLED_KEY = "heist_enabled"
HEIST_ACTIVITY_LEVEL_KEY = "heist_required_activity_level"
HEIST_PRESTIGE_KEY = "heist_required_prestige"
HEIST_COOLDOWN_HOURS_KEY = "heist_cooldown_hours"
HEIST_JAIL_MINUTES_KEY = "heist_jail_minutes"
HEIST_FINE_PERCENT_KEY = "heist_fine_percent"
HEIST_GEAR_LOSS_PERCENT_KEY = "heist_gear_loss_percent"
HEIST_REWARD_MULTIPLIER_KEY = "heist_reward_multiplier_percent"
HEIST_LOBBY_EXPIRE_KEY = "heist_lobby_expire_minutes"
HEIST_MAX_PARTY_KEY = "heist_max_party_size"

DEFAULT_ENABLED = True
DEFAULT_REQUIRED_ACTIVITY_LEVEL = 25
DEFAULT_REQUIRED_PRESTIGE = 1
DEFAULT_COOLDOWN_HOURS = 8
DEFAULT_JAIL_MINUTES = 45
DEFAULT_FINE_PERCENT = 12
DEFAULT_GEAR_LOSS_PERCENT = 35
DEFAULT_REWARD_MULTIPLIER_PERCENT = 100

MIN_ACTIVITY_LEVEL = 0
MAX_ACTIVITY_LEVEL = 500
MIN_PRESTIGE = 0
MAX_PRESTIGE = 100
MIN_COOLDOWN_HOURS = 1
MAX_COOLDOWN_HOURS = 168
MIN_JAIL_MINUTES = 0
MAX_JAIL_MINUTES = 1440
MIN_FINE_PERCENT = 0
MAX_FINE_PERCENT = 50
MIN_GEAR_LOSS_PERCENT = 0
MAX_GEAR_LOSS_PERCENT = 100
MIN_REWARD_MULTIPLIER_PERCENT = 25
MAX_REWARD_MULTIPLIER_PERCENT = 500

LOBBY_EXPIRE_MINUTES = 30
MAX_PARTY_SIZE = 4
PHASE_LABELS = (
    ("prep", "🧠 Felkészülés"),
    ("execution", "⚙️ Végrehajtás"),
    ("escape", "🏁 Kijutás"),
)


@dataclass(frozen=True)
class HeistTarget:
    key: str
    name: str
    emoji: str
    location: str
    flavor: str
    difficulty: int
    min_party: int
    max_party: int
    reward_min: int
    reward_max: int
    activity_level: int
    prestige: int


# Valós magyar helynevek csak játékvilág-hangulatként szerepelnek. A célpontok
# teljesen fikciósak; nincs valós bankfiók, biztonsági rendszer vagy műveleti leírás.
HEIST_TARGETS: tuple[HeistTarget, ...] = (
    HeistTarget("miskolc_hollo", "Fekete Holló Raktár", "🦅", "Miskolc • Belváros", "Fikciós éjszakai raktár-meló.", 38, 2, 4, 24_000_000, 38_000_000, 25, 1),
    HeistTarget("eger_smaragd", "Smaragd Galéria", "🖼️", "Eger • Belváros", "Fikciós műkincsraktár-játékcélpont.", 46, 2, 4, 34_000_000, 52_000_000, 30, 1),
    HeistTarget("debrecen_orbit", "Orbit Data Hub", "💾", "Debrecen • Belváros", "Absztrakt tech-heist célpont, valós infrastruktúra nélkül.", 54, 2, 4, 48_000_000, 72_000_000, 35, 2),
    HeistTarget("szeged_aranyhid", "Aranyhíd Logistics", "🚚", "Szeged • Belváros", "Fikciós logisztikai nagy meló.", 62, 3, 4, 68_000_000, 98_000_000, 45, 2),
    HeistTarget("budapest_neonvault", "Neon Vault Központ", "🌃", "Budapest • XIII. kerület", "Endgame, teljesen kitalált vault-heist.", 72, 3, 4, 105_000_000, 155_000_000, 60, 3),
    HeistTarget("budapest_dunacrown", "Duna Crown Holding", "👑", "Budapest • V. kerület", "Elite, absztrakt kooperatív endgame célpont.", 82, 4, 4, 165_000_000, 245_000_000, 75, 4),
)
TARGET_BY_KEY = {target.key: target for target in HEIST_TARGETS}


@dataclass(frozen=True)
class HeistRole:
    key: str
    name: str
    emoji: str
    prep_bonus: int
    execution_bonus: int
    escape_bonus: int


HEIST_ROLES: tuple[HeistRole, ...] = (
    HeistRole("planner", "Tervező", "🧠", 12, 2, 2),
    HeistRole("specialist", "Specialista", "🛠️", 2, 12, 2),
    HeistRole("driver", "Sofőr", "🏎️", 2, 2, 12),
    HeistRole("support", "Támogató", "🤝", 5, 5, 5),
)
ROLE_BY_KEY = {role.key: role for role in HEIST_ROLES}


@dataclass(frozen=True)
class HeistGear:
    key: str
    name: str
    emoji: str
    description: str
    price: int
    prep_bonus: int
    execution_bonus: int
    escape_bonus: int


HEIST_GEAR: tuple[HeistGear, ...] = (
    HeistGear("intel_pack", "Intel Pack", "📡", "Absztrakt előkészítési boost.", 4_500_000, 9, 0, 0),
    HeistGear("toolkit", "Toolkit", "🧰", "Absztrakt végrehajtási boost.", 6_500_000, 0, 11, 0),
    HeistGear("escape_kit", "Escape Kit", "🎒", "Absztrakt kijutási boost.", 6_000_000, 0, 0, 11),
    HeistGear("disguise_set", "Disguise Set", "🎭", "Kiegyensúlyozott, tisztán játékmechanikai boost.", 9_500_000, 4, 4, 4),
)
GEAR_BY_KEY = {gear.key: gear for gear in HEIST_GEAR}
