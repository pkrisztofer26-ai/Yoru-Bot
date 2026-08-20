from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VehicleModel:
    key: str
    name: str
    emoji: str
    category: str
    base_price: int
    summary: str


@dataclass(frozen=True, slots=True)
class VehicleCondition:
    key: str
    name: str
    emoji: str
    value_bp: int
    drivable: bool


@dataclass(frozen=True, slots=True)
class RouteCost:
    train: int
    bus: int
    car: int
    driver: int


@dataclass(frozen=True, slots=True)
class HiddenIssue:
    key: str
    name: str
    repair_bp: int
    sale_penalty_bp: int
    travel_wear_bonus_bp: int
    reveal_text: str


VEHICLE_MODELS: dict[str, VehicleModel] = {
    "suzuki_swift_2005": VehicleModel(
        "suzuki_swift_2005", "2005 Suzuki Swift", "🚗", "Olcsó közlekedés", 4_200_000,
        "Egyszerű, olcsón fenntartható városi autó.",
    ),
    "opel_astra_g_2004": VehicleModel(
        "opel_astra_g_2004", "2004 Opel Astra G", "🚙", "Hétköznapi autó", 5_000_000,
        "Tipikus mindenes: munkába járásra és hétköznapi használatra.",
    ),
    "ford_focus_2006": VehicleModel(
        "ford_focus_2006", "2006 Ford Focus", "🚙", "Hétköznapi autó", 5_800_000,
        "Kiegyensúlyozott, gyakori használt autó.",
    ),
    "vw_golf_v_2006": VehicleModel(
        "vw_golf_v_2006", "2006 Volkswagen Golf V", "🚙", "Hétköznapi autó", 7_200_000,
        "Keresett, kompakt mindenes autó.",
    ),
    "skoda_octavia_2008": VehicleModel(
        "skoda_octavia_2008", "2008 Škoda Octavia", "🚘", "Hétköznapi autó", 8_500_000,
        "Tágasabb, munkára és hosszabb utakra is praktikus.",
    ),
    "toyota_corolla_2008": VehicleModel(
        "toyota_corolla_2008", "2008 Toyota Corolla", "🚘", "Jobb autó", 10_500_000,
        "Megbízhatóbb, valamivel értékesebb használt autó.",
    ),
    "bmw_320d_2008": VehicleModel(
        "bmw_320d_2008", "2008 BMW 320d", "🏎️", "Jobb autó", 16_000_000,
        "Erősebb, drágább autó, már komolyabb státuszértékkel.",
    ),
    "mercedes_c220_2009": VehicleModel(
        "mercedes_c220_2009", "2009 Mercedes C220", "🏎️", "Prémium autó", 22_000_000,
        "Kényelmesebb, prémiumabb autó magasabb fenntartási kockázattal.",
    ),
    "ford_transit_2009": VehicleModel(
        "ford_transit_2009", "2009 Ford Transit", "🚐", "Munkajármű", 12_000_000,
        "Furgon fuvaros, futár- és vállalkozási feladatokhoz.",
    ),
    "renault_master_2011": VehicleModel(
        "renault_master_2011", "2011 Renault Master", "🚐", "Munkajármű", 18_000_000,
        "Nagyobb furgon komolyabb szállítási feladatokhoz.",
    ),
}


CONDITIONS: dict[str, VehicleCondition] = {
    "excellent": VehicleCondition("excellent", "Kiváló", "✨", 10_500, True),
    "good": VehicleCondition("good", "Jó", "✅", 9_500, True),
    "used": VehicleCondition("used", "Használt", "🛠️", 8_000, True),
    "poor": VehicleCondition("poor", "Rossz", "⚠️", 6_500, True),
    "broken": VehicleCondition("broken", "Üzemképtelen", "⛔", 3_500, False),
}

CONDITION_ORDER: tuple[str, ...] = ("broken", "poor", "used", "good", "excellent")
MARKET_CONDITION_KEYS: tuple[str, ...] = ("excellent", "good", "good", "used", "used", "used", "poor")
MARKET_OFFER_COUNT = 5
MARKET_ROTATION_HOURS = 12
MARKET_PRICE_JITTER_BP = 700  # +/- 7%

# A kereskedés kiszámíthatóbb és drágább, mint az utcai használtautó-piac.
DEALERSHIP_PRICE_BP = 11_500
DEALERSHIP_CONDITION_KEY = "excellent"

# Gyors kereskedői visszavásárlás. A játékos nem kapja vissza a teljes becsült értéket.
VEHICLE_SELL_BP = 8_200

# A szerviz egy állapotlépcsőt javít egyszerre. A százalék a modell alapárából számolódik.
REPAIR_BP_BY_CONDITION: dict[str, int] = {
    "broken": 1_500,
    "poor": 1_000,
    "used": 700,
    "good": 500,
}
MIN_REPAIR_PRICE = 120_000

# Saját autós városközi utaknál ritkán romolhat az állapot. Ez nem kilométer- vagy alkatrész-szimulátor:
# egyetlen természetes állapotlépcső kezeli a kopást.
TRAVEL_WEAR_BP_BY_CONDITION: dict[str, int] = {
    "excellent": 450,
    "good": 700,
    "used": 1_050,
    "poor": 1_700,
    "broken": 10_000,
}

HIDDEN_ISSUES: dict[str, HiddenIssue] = {
    "minor": HiddenIssue(
        "minor", "Kisebb rejtett hiba", 350, 250, 350,
        "Menet közben előjött egy kisebb, korábban nem látható műszaki probléma.",
    ),
    "moderate": HiddenIssue(
        "moderate", "Komolyabb rejtett hiba", 750, 600, 700,
        "A használat során kiderült, hogy a járműnek komolyabb, korábban nem jelzett hibája van.",
    ),
    "serious": HiddenIssue(
        "serious", "Súlyos rejtett hiba", 1_300, 1_150, 1_250,
        "A járműnél egy súlyosabb, vásárláskor nem látható probléma jelentkezett.",
    ),
}

# A jó állapotú autóknál tényleg ritka; a rosszabb, olcsóbb autóknál valamivel gyakoribb.
HIDDEN_ISSUE_CHANCE_BP_BY_CONDITION: dict[str, int] = {
    "excellent": 0,
    "good": 250,
    "used": 900,
    "poor": 2_000,
    "broken": 0,
}

TRAVEL_EVENT_CHANCE_BP: dict[str, int] = {
    "train": 1_800,
    "bus": 1_600,
    "car": 2_200,
    "driver": 1_100,
}

TRAVEL_EVENT_TEXTS: dict[str, tuple[str, ...]] = {
    "train": (
        "A MÁV hozta a formáját, de a fennakadás végül nem változtatott az utadon.",
        "Jegyellenőrzés volt útközben; minden rendben találtak.",
        "A szerelvény rövid ideig vesztegelt, aztán továbbindult.",
    ),
    "bus": (
        "Egy útlezárás miatt kerülőt tett a busz, de rendben megérkeztél.",
        "Ellenőrzés volt az útvonalon; az utazás folytatódott.",
        "Rövid műszaki megálló után továbbindultatok.",
    ),
    "car": (
        "Útközben sűrűbb forgalomba futottál, de különösebb gond nélkül megérkeztél.",
        "Rendőri ellenőrzés mellett haladtál el; nem történt semmi rendkívüli.",
        "Az út rosszabb szakaszai jobban megdolgoztatták az autót a szokásosnál.",
    ),
    "driver": (
        "A sofőr kerülőúton vitt tovább egy torlódás miatt.",
        "Rövid ellenőrzés után folytattátok az utat.",
        "Kisebb fennakadás volt az úton, de neked nem kellett vele foglalkoznod.",
    ),
}

# First travel release intentionally supports the five full RP cities only.
TRAVEL_CITY_KEYS: tuple[str, ...] = ("budapest", "miskolc", "debrecen", "eger", "szeged")

# One-way, one-time travel costs. Own-car cost is a simplified route cost; there
# is deliberately no fuel tank, litre counter, insurance or other hidden fee.
_ROUTE_COSTS: dict[frozenset[str], RouteCost] = {
    frozenset(("budapest", "miskolc")): RouteCost(65_000, 50_000, 55_000, 180_000),
    frozenset(("budapest", "eger")): RouteCost(50_000, 40_000, 45_000, 145_000),
    frozenset(("budapest", "debrecen")): RouteCost(75_000, 60_000, 70_000, 210_000),
    frozenset(("budapest", "szeged")): RouteCost(70_000, 55_000, 65_000, 200_000),
    frozenset(("miskolc", "eger")): RouteCost(30_000, 25_000, 35_000, 100_000),
    frozenset(("miskolc", "debrecen")): RouteCost(45_000, 35_000, 45_000, 135_000),
    frozenset(("miskolc", "szeged")): RouteCost(75_000, 60_000, 80_000, 230_000),
    frozenset(("eger", "debrecen")): RouteCost(50_000, 40_000, 50_000, 150_000),
    frozenset(("eger", "szeged")): RouteCost(80_000, 65_000, 85_000, 245_000),
    frozenset(("debrecen", "szeged")): RouteCost(55_000, 45_000, 60_000, 175_000),
}


def model(key: str) -> VehicleModel:
    try:
        return VEHICLE_MODELS[str(key)]
    except KeyError as exc:
        raise ValueError("Ez a járműmodell már nem elérhető.") from exc


def condition(key: str) -> VehicleCondition:
    try:
        return CONDITIONS[str(key)]
    except KeyError as exc:
        raise ValueError("Ismeretlen járműállapot.") from exc


def hidden_issue(key: str | None) -> HiddenIssue | None:
    if not key:
        return None
    return HIDDEN_ISSUES.get(str(key))


def estimated_value(model_key: str, condition_key: str) -> int:
    vehicle = model(model_key)
    state = condition(condition_key)
    return max(1, vehicle.base_price * state.value_bp // 10_000)


def dealership_price(model_key: str) -> int:
    return max(1, model(model_key).base_price * DEALERSHIP_PRICE_BP // 10_000)


def next_better_condition(condition_key: str) -> str | None:
    key = str(condition_key)
    try:
        index = CONDITION_ORDER.index(key)
    except ValueError:
        return None
    if index >= len(CONDITION_ORDER) - 1:
        return None
    return CONDITION_ORDER[index + 1]


def next_worse_condition(condition_key: str) -> str | None:
    key = str(condition_key)
    try:
        index = CONDITION_ORDER.index(key)
    except ValueError:
        return None
    if index <= 0:
        return None
    return CONDITION_ORDER[index - 1]


def repair_price(model_key: str, condition_key: str, issue_key: str | None = None) -> int:
    current = str(condition_key)
    if current == "excellent" and not issue_key:
        return 0
    bp = REPAIR_BP_BY_CONDITION.get(current, 0)
    issue = hidden_issue(issue_key)
    if issue is not None:
        bp += issue.repair_bp
    if bp <= 0:
        return 0
    return max(MIN_REPAIR_PRICE, model(model_key).base_price * bp // 10_000)


def sell_value(model_key: str, condition_key: str, issue_key: str | None = None) -> int:
    value = estimated_value(model_key, condition_key)
    bp = VEHICLE_SELL_BP
    issue = hidden_issue(issue_key)
    if issue is not None:
        bp = max(1_000, bp - issue.sale_penalty_bp)
    return max(1, value * bp // 10_000)


def route_cost(from_city: str, to_city: str) -> RouteCost:
    if from_city == to_city:
        raise ValueError("Már ebben a városban vagy.")
    if from_city not in TRAVEL_CITY_KEYS or to_city not in TRAVEL_CITY_KEYS:
        raise ValueError("Erre a városra még nincs aktív utazási útvonal.")
    try:
        return _ROUTE_COSTS[frozenset((str(from_city), str(to_city)))]
    except KeyError as exc:
        raise ValueError("Erre az útvonalra még nincs aktív utazás.") from exc


def mode_cost(from_city: str, to_city: str, mode_key: str) -> int:
    costs = route_cost(from_city, to_city)
    if mode_key == "train":
        return costs.train
    if mode_key == "bus":
        return costs.bus
    if mode_key == "car":
        return costs.car
    if mode_key == "driver":
        return costs.driver
    raise ValueError("Ismeretlen utazási mód.")


def taxi_job_eligible_model(model_key: str) -> bool:
    return model(model_key).category != "Munkajármű"


def courier_job_eligible_model(model_key: str) -> bool:
    # Futárként bármely vezethető saját jármű használható.
    return model_key in VEHICLE_MODELS
