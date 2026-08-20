from __future__ import annotations

from dataclasses import dataclass

# Phase 4 starts with a deliberately small canonical objective vocabulary.
# Domain services remain the source of truth for whether an event actually
# happened; ContractService only consumes explicit, state-backed event refs.


@dataclass(frozen=True, slots=True)
class ContractObjectiveDefinition:
    key: str
    label: str
    event_type: str
    unit_label: str


OBJECTIVE_DEFINITIONS: tuple[ContractObjectiveDefinition, ...] = (
    ContractObjectiveDefinition("item_delivery", "Tárgy átadása", "item_delivered", "db"),
    ContractObjectiveDefinition("city_delivery", "Városok közti szállítás", "city_delivery_completed", "fuvar"),
    ContractObjectiveDefinition("business_delivery", "Vállalkozási szállítás", "business_delivery_completed", "teljesítés"),
    ContractObjectiveDefinition("vehicle_service", "Járműszerviz", "vehicle_service_completed", "szerviz"),
    ContractObjectiveDefinition("contribution", "Hozzájárulás", "contribution_recorded", "egység"),
    ContractObjectiveDefinition("system_participation", "Rendszeresemény-részvétel", "system_participation", "részvétel"),
)
OBJECTIVE_BY_KEY = {item.key: item for item in OBJECTIVE_DEFINITIONS}
EVENT_TO_OBJECTIVE = {item.event_type: item.key for item in OBJECTIVE_DEFINITIONS}

CONTRACT_STATUSES = frozenset({"open", "active", "settled", "cancelled", "expired"})
TERMINAL_STATUSES = frozenset({"settled", "cancelled", "expired"})
ESCROW_STATES = frozenset({"held", "released", "refunded"})

# Audit source-of-truth. These legacy systems stay authoritative in their own
# domains; W14.1 does not rewrite/migrate them into contracts.
EXISTING_TRANSACTION_PRIMITIVES: dict[str, str] = {
    "business_offers": "player property offer escrow / expiry / refund / accepted transfer",
    "pvp_duels": "two-party wager reserve / timeout-refund / restart recovery",
    "player_market_listings": "item reservation / expiry return / atomic trade",
    "crew_wars": "objective stat / target / pending-active-resolved lifecycle",
}

# W14.2 player-board safety limits. These are deliberately conservative while
# the contract economy is new; they can be tuned later from observed telemetry.
PLAYER_MIN_REWARD = 50_000
PLAYER_MAX_REWARD = 2_000_000_000
PLAYER_MAX_DEADLINE_DAYS = 7
PLAYER_MAX_ACTIVE_CREATED = 5
PLAYER_MAX_ACTIVE_ASSIGNED = 3
PLAYER_MAX_CREATES_24H = 12
RECIPROCAL_TELEMETRY_DAYS = 7


# W14.4 deterministic modifier contract. Modifier keys are allowlisted here;
# UI/AI text cannot invent mechanical effects. Basis points keep calculations
# integer-only and deterministic.


@dataclass(frozen=True, slots=True)
class ContractModifierDefinition:
    key: str
    label: str
    description: str
    reward_multiplier_bp: int = 10_000
    deadline_multiplier_bp: int = 10_000
    required_multiplier_bp: int = 10_000
    objective_types: tuple[str, ...] = ()


MODIFIER_DEFINITIONS: tuple[ContractModifierDefinition, ...] = (
    ContractModifierDefinition(
        "public_freelance", "Nyilvános",
        "Minden jogosult játékos számára elérhető determinisztikus Yoru-megbízás.",
    ),
    ContractModifierDefinition(
        "service_job", "Szolgáltatási munka",
        "A teljesítést egy meglévő szolgáltatási domain igazolja.",
        objective_types=("vehicle_service",),
    ),
    ContractModifierDefinition(
        "relationship_private", "Privát kapcsolat",
        "Kapcsolati feltételhez kötött, célzott megbízás.",
    ),
    ContractModifierDefinition(
        "priority_window", "Sürgős",
        "Rövidebb határidőért magasabb, előre rögzített díj jár.",
        reward_multiplier_bp=11_500, deadline_multiplier_bp=7_500,
        objective_types=("city_delivery", "vehicle_service", "business_delivery"),
    ),
    ContractModifierDefinition(
        "bulk_support", "Nagyobb tétel",
        "Nagyobb mennyiségű üzleti ellátmány, determinisztikusan emelt díjjal.",
        reward_multiplier_bp=12_500, required_multiplier_bp=20_000,
        objective_types=("business_delivery",),
    ),
)
MODIFIER_BY_KEY = {item.key: item for item in MODIFIER_DEFINITIONS}


@dataclass(frozen=True, slots=True)
class ContractModifierEffect:
    keys: tuple[str, ...]
    reward_multiplier_bp: int
    deadline_multiplier_bp: int
    required_multiplier_bp: int


def modifier_effect(modifiers: tuple[str, ...] | list[str], objective_types: tuple[str, ...] | list[str]) -> ContractModifierEffect:
    keys: list[str] = []
    reward_bp = deadline_bp = required_bp = 10_000
    objective_set = {str(item) for item in objective_types}
    for raw in modifiers:
        key = str(raw).strip().lower()
        definition = MODIFIER_BY_KEY.get(key)
        if definition is None:
            raise ValueError(f"Ismeretlen contract modifier: {key}")
        if definition.objective_types and not objective_set.intersection(definition.objective_types):
            raise ValueError(f"A(z) {key} modifier nem alkalmazható erre az objective-re.")
        if key in keys:
            continue
        keys.append(key)
        reward_bp = reward_bp * int(definition.reward_multiplier_bp) // 10_000
        deadline_bp = deadline_bp * int(definition.deadline_multiplier_bp) // 10_000
        required_bp = required_bp * int(definition.required_multiplier_bp) // 10_000
    return ContractModifierEffect(tuple(keys), reward_bp, deadline_bp, required_bp)


def modifier_labels(modifiers: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(MODIFIER_BY_KEY[key].label for key in (str(item).strip().lower() for item in modifiers) if key in MODIFIER_BY_KEY)


# Service-economy discovery is presentation/orchestration only. The actual
# completion still belongs to VehicleService / BusinessService / travel.
SERVICE_OBJECTIVE_TYPES = frozenset({"city_delivery", "vehicle_service", "business_delivery"})
SERVICE_LABEL_BY_OBJECTIVE = {
    "city_delivery": "Fuvarozás",
    "vehicle_service": "Szerviz",
    "business_delivery": "Üzleti támogatás",
}

# Anti-abuse observability only. These thresholds create telemetry, never an
# automatic punishment or settlement denial.
CONTRACT_HIGH_VALUE_THRESHOLD = 50_000_000
CONTRACT_RAPID_COMPLETION_SECONDS = 5 * 60
CONTRACT_REPEATED_PAIR_DAYS = 7
CONTRACT_REPEATED_PAIR_THRESHOLD = 3

# W14.5 closure hardening. Telemetry is audit-only and must remain bounded.
# Cleanup never changes contract settlement or eligibility.
CONTRACT_TELEMETRY_RETENTION_DAYS = 90
CONTRACT_TELEMETRY_MAX_ROWS_PER_GUILD = 50_000


# W14.3 deterministic public/private freelance sources. Rewards are fixed by
# Yoru config and may only be paid from the audited daily budget below. AI,
# relationship text and Discord UI never determine payout values.

@dataclass(frozen=True, slots=True)
class ContractSourceDefinition:
    key: str
    label: str
    title: str
    source_type: str
    objective_type: str
    reward_amount: int
    budget_key: str
    budget_daily_limit: int
    deadline_hours: int = 24
    npc_key: str | None = None
    required_trust_bands: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    objective_target_ref: str = ""
    objective_item_id: str = ""
    objective_required_value: int = 1


SOURCE_DEFINITIONS: tuple[ContractSourceDefinition, ...] = (
    ContractSourceDefinition(
        "lilla_public_courier", "Lilla • Fuvarszervezés", "Nyilvános városközi fuvar",
        "public", "city_delivery", 240_000, "npc_public_freelance", 12_000_000, 24,
        npc_key="lilla_dispatcher", modifiers=("public_freelance",),
    ),
    ContractSourceDefinition(
        "jani_public_service", "Jani • Szerviz", "Szervizbesegítés",
        "public", "vehicle_service", 180_000, "npc_public_freelance", 12_000_000, 24,
        npc_key="jani_mechanic", modifiers=("service_job",), objective_target_ref="service:repair",
    ),
    ContractSourceDefinition(
        "marci_public_courier", "Marci • Helyi fuvar", "Sürgős városközi fuvar",
        "public", "city_delivery", 200_000, "npc_public_freelance", 12_000_000, 24,
        npc_key="marci_city_contact", modifiers=("public_freelance", "priority_window"),
    ),
    ContractSourceDefinition(
        "lilla_private_courier", "Lilla • Privát megbízás", "Kiemelt privát fuvar",
        "private", "city_delivery", 420_000, "npc_private_contracts", 9_000_000, 24,
        npc_key="lilla_dispatcher", required_trust_bands=("warm", "trusted"),
        modifiers=("relationship_private",),
    ),
    ContractSourceDefinition(
        "marci_private_courier", "Marci • Privát fuvar", "Sürgős privát fuvar",
        "private", "city_delivery", 320_000, "npc_private_contracts", 9_000_000, 24,
        npc_key="marci_city_contact", required_trust_bands=("warm", "trusted"),
        modifiers=("relationship_private", "priority_window"),
    ),
    ContractSourceDefinition(
        "jani_private_service", "Jani • Privát szerviz", "Kiemelt szervizbesegítés",
        "private", "vehicle_service", 260_000, "npc_private_contracts", 9_000_000, 24,
        npc_key="jani_mechanic", required_trust_bands=("warm", "trusted"),
        modifiers=("relationship_private", "service_job", "priority_window"), objective_target_ref="service:repair",
    ),
    ContractSourceDefinition(
        "bence_private_business_support", "Bence • Üzleti beszerzés", "Kiemelt üzleti ellátmány",
        "private", "business_delivery", 360_000, "npc_private_contracts", 9_000_000, 24,
        npc_key="bence_business_contact", required_trust_bands=("warm", "trusted"),
        modifiers=("relationship_private", "bulk_support"), objective_item_id="used_phone", objective_required_value=1,
    ),
)
SOURCE_BY_KEY = {item.key: item for item in SOURCE_DEFINITIONS}

SYSTEM_SOURCE_TYPES = frozenset({"public", "private"})
SYSTEM_BUDGET_KEYS = frozenset({item.budget_key for item in SOURCE_DEFINITIONS})


def source_definition_from_ref(source_ref: str):
    raw = str(source_ref or "")
    key = raw.split(":", 1)[0]
    return SOURCE_BY_KEY.get(key)


def source_label(source_ref: str, source_type: str = "player") -> str:
    definition = source_definition_from_ref(source_ref)
    if definition is not None:
        return definition.label
    if str(source_type) == "player":
        return "Játékos megbízás"
    return "Yoru megbízás"
