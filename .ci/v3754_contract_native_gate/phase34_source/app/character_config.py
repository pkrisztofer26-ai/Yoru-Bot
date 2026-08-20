from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CityDefinition:
    key: str
    name: str
    emoji: str
    summary: str
    startable: bool = True


@dataclass(frozen=True, slots=True)
class BackgroundDefinition:
    key: str
    name: str
    emoji: str
    summary: str


# Stable internal keys are stored in the DB. Player-facing wording can change
# later without rewriting every character row.
CITIES: dict[str, CityDefinition] = {
    "budapest": CityDefinition(
        "budapest",
        "Budapest",
        "🏙️",
        "Sokféle munka és nagy piac, de a lakhatás és az élet is drágább.",
    ),
    "miskolc": CityDefinition(
        "miskolc",
        "Miskolc",
        "🏭",
        "Ipar, logisztika és olcsóbb indulás; kisebb prémium piac.",
    ),
    "debrecen": CityDefinition(
        "debrecen",
        "Debrecen",
        "🏗️",
        "Stabil ipari és műszaki lehetőségek, fejlődő üzleti közeg.",
    ),
    "eger": CityDefinition(
        "eger",
        "Eger",
        "🏰",
        "Turizmus, vendéglátás és szolgáltatások; erősebb szezonális időszakok.",
    ),
    "szeged": CityDefinition(
        "szeged",
        "Szeged",
        "🌉",
        "Kiegyensúlyozott szolgáltatói és kereskedelmi lehetőségek.",
    ),
    # Existing Business assets already exist in these cities. They stay in the
    # world registry so no legacy property ever has to be deleted or moved.
    "pecs": CityDefinition("pecs", "Pécs", "🏘️", "Jelenleg kiegészítő város.", startable=False),
    "nyiregyhaza": CityDefinition("nyiregyhaza", "Nyíregyháza", "🌳", "Jelenleg kiegészítő város.", startable=False),
    "gyor": CityDefinition("gyor", "Győr", "🏢", "Jelenleg kiegészítő város.", startable=False),
}

STARTING_CITY_KEYS: tuple[str, ...] = tuple(key for key, city in CITIES.items() if city.startable)


BACKGROUNDS: dict[str, BackgroundDefinition] = {
    "worker_family": BackgroundDefinition(
        "worker_family",
        "Munkáscsalád",
        "🔧",
        "A hétköznapi munka és a gyakorlati világ közelebb áll hozzád.",
    ),
    "business_family": BackgroundDefinition(
        "business_family",
        "Vállalkozói háttér",
        "💼",
        "Az üzleti és tárgyalási helyzetek ismerősebben hatnak.",
    ),
    "hard_upbringing": BackgroundDefinition(
        "hard_upbringing",
        "Nehéz körülmények",
        "🧱",
        "Korán megtanultál alkalmazkodni és rögtönözni.",
    ),
    "intellectual_family": BackgroundDefinition(
        "intellectual_family",
        "Értelmiségi család",
        "📚",
        "A tanulási és formális helyzetek világa ismerősebb számodra.",
    ),
    "average_family": BackgroundDefinition(
        "average_family",
        "Átlagos háttér",
        "🏠",
        "Kiegyensúlyozott indulás, különösen erős irány nélkül.",
    ),
}

BACKGROUND_KEYS: tuple[str, ...] = tuple(BACKGROUNDS)

CHARACTER_SCHEMA_VERSION = 1
DRAFT_TTL_HOURS = 24 * 7
MIN_AGE = 18
MAX_AGE = 80
MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 32
MIN_BIRTHPLACE_LENGTH = 2
MAX_BIRTHPLACE_LENGTH = 80


def city_name(key: str) -> str:
    city = CITIES.get(str(key))
    return city.name if city else str(key)


def background_name(key: str) -> str:
    bg = BACKGROUNDS.get(str(key))
    return bg.name if bg else str(key)
