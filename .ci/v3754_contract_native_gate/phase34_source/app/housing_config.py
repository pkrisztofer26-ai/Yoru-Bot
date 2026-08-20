from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HousingTierDefinition:
    key: str
    name: str
    emoji: str
    summary: str
    has_stable_address: bool
    storage_capacity: int
    garage_slots: int


@dataclass(frozen=True, slots=True)
class CityHousingCosts:
    shelter_entry: int
    shelter_weekly: int
    rental_entry: int
    rental_weekly: int
    owned_purchase: int
    owned_weekly: int
    premium_upgrade: int
    premium_weekly: int


HOUSING_TIERS: dict[str, HousingTierDefinition] = {
    "street": HousingTierDefinition(
        "street", "Utca", "🏚️",
        "Nincs állandó lakhatásod. Az első célod, hogy biztos helyet szerezz magadnak.",
        False, 5, 0,
    ),
    "shelter": HousingTierDefinition(
        "shelter", "Szálló", "🛏️",
        "Egyszerű, de stabil hely. Már van használható címed és biztos pontod a városban.",
        True, 15, 0,
    ),
    "rental": HousingTierDefinition(
        "rental", "Albérlet", "🏠",
        "Saját bérelt otthon, nagyobb stabilitással és több későbbi lehetőséggel.",
        True, 40, 0,
    ),
    "owned": HousingTierDefinition(
        "owned", "Saját lakás", "🔑",
        "Saját tulajdonú otthon. Költözéskor megtarthatod, később pedig el is adhatod.",
        True, 100, 1,
    ),
    "premium": HousingTierDefinition(
        "premium", "Prémium ingatlan", "🏡",
        "Kiemelt saját ingatlan nagy tárolóval, több garázshellyel és ritkább személyes lehetőségekkel.",
        True, 250, 3,
    ),
}

# v3.58 balance: az Albérlet továbbra is early/mid milestone; a Saját lakás
# már komoly vagyon, a Prémium ingatlan pedig tudatos endgame státusz-sink.
CITY_HOUSING_COSTS: dict[str, CityHousingCosts] = {
    "miskolc": CityHousingCosts(350_000, 100_000, 3_500_000, 350_000, 38_000_000, 250_000, 120_000_000, 650_000),
    "eger": CityHousingCosts(390_000, 110_000, 4_500_000, 450_000, 46_000_000, 300_000, 145_000_000, 750_000),
    "szeged": CityHousingCosts(420_000, 120_000, 5_200_000, 520_000, 54_000_000, 350_000, 170_000_000, 850_000),
    "debrecen": CityHousingCosts(450_000, 130_000, 6_000_000, 650_000, 62_000_000, 400_000, 195_000_000, 950_000),
    "budapest": CityHousingCosts(500_000, 150_000, 7_500_000, 850_000, 82_000_000, 550_000, 260_000_000, 1_250_000),
    # Ezek a városok egyelőre nem teljes travel/home-city célok, de a költségmodell
    # kompatibilitásból megmarad a későbbi városbővítéshez.
    "pecs": CityHousingCosts(410_000, 115_000, 4_800_000, 480_000, 50_000_000, 325_000, 155_000_000, 800_000),
    "nyiregyhaza": CityHousingCosts(380_000, 105_000, 4_000_000, 400_000, 42_000_000, 275_000, 132_000_000, 700_000),
    "gyor": CityHousingCosts(460_000, 135_000, 6_300_000, 680_000, 68_000_000, 425_000, 210_000_000, 1_000_000),
}

BILLING_PERIOD_DAYS = 7
GRACE_PERIOD_HOURS = 72
RENTED_TIERS = ("shelter", "rental")
PROPERTY_TIERS = ("owned", "premium")
PURCHASABLE_TIERS = ("shelter", "rental", "owned", "premium")
PROGRESSION_ORDER = ("street", "shelter", "rental", "owned", "premium")

# Eladásnál a vételár egy része végleg kikerül az economyból. A prémium ingatlan
# valamivel jobban tartja az értékét, de egyik sem veszteségmentes parkolóhely a pénznek.
PROPERTY_RESALE_BP = {
    "owned": 8_000,
    "premium": 8_200,
}

# A Prémium ingatlan ritka személyes opportunityja egy világciklusban stabilan
# ugyanannak a játékosnak jelenik meg vagy nem jelenik meg; panelnyitás nem reroll.
PREMIUM_OPPORTUNITY_MODULUS = 8
PREMIUM_OPPORTUNITY_REWARDS: tuple[str, ...] = (
    "mystery_box", "mystery_box", "mystery_box", "mystery_box", "mystery_box",
    "rare_crate", "rare_crate", "rare_crate", "epic_crate",
)


def tier_name(key: str) -> str:
    tier = HOUSING_TIERS.get(str(key))
    return tier.name if tier else str(key)


def tier_emoji(key: str) -> str:
    tier = HOUSING_TIERS.get(str(key))
    return tier.emoji if tier else "🏠"


def tier_definition(key: str) -> HousingTierDefinition:
    try:
        return HOUSING_TIERS[str(key)]
    except KeyError as exc:
        raise ValueError("Ismeretlen lakhatási szint.") from exc


def costs_for_city(city_key: str) -> CityHousingCosts:
    try:
        return CITY_HOUSING_COSTS[str(city_key)]
    except KeyError as exc:
        raise ValueError("Ebben a városban még nincs elérhető lakhatási rendszer.") from exc


def entry_price(city_key: str, tier_key: str) -> int:
    costs = costs_for_city(city_key)
    if tier_key == "shelter":
        return costs.shelter_entry
    if tier_key == "rental":
        return costs.rental_entry
    if tier_key == "owned":
        return costs.owned_purchase
    if tier_key == "premium":
        return costs.premium_upgrade
    raise ValueError("Ez a lakhatási szint jelenleg nem vásárolható meg.")


def weekly_cost(city_key: str, tier_key: str) -> int:
    costs = costs_for_city(city_key)
    if tier_key == "shelter":
        return costs.shelter_weekly
    if tier_key == "rental":
        return costs.rental_weekly
    if tier_key == "owned":
        return costs.owned_weekly
    if tier_key == "premium":
        return costs.premium_weekly
    return 0


def next_tier(current_tier_key: str) -> str | None:
    try:
        index = PROGRESSION_ORDER.index(str(current_tier_key))
    except ValueError:
        return None
    if index + 1 >= len(PROGRESSION_ORDER):
        return None
    return PROGRESSION_ORDER[index + 1]


def property_total_value(city_key: str, tier_key: str) -> int:
    costs = costs_for_city(city_key)
    if tier_key == "owned":
        return int(costs.owned_purchase)
    if tier_key == "premium":
        return int(costs.owned_purchase + costs.premium_upgrade)
    raise ValueError("Ez nem saját tulajdonú ingatlan.")


def property_sale_value(city_key: str, tier_key: str) -> int:
    bp = int(PROPERTY_RESALE_BP.get(str(tier_key), 0))
    if bp <= 0:
        raise ValueError("Ez az ingatlan nem értékesíthető.")
    value = property_total_value(city_key, tier_key) * bp // 10_000
    # Kerek, jól olvasható árak.
    return max(100_000, int(round(value / 100_000)) * 100_000)


def storage_capacity(tier_key: str) -> int:
    return int(tier_definition(tier_key).storage_capacity)


def garage_slots(tier_key: str) -> int:
    return int(tier_definition(tier_key).garage_slots)
