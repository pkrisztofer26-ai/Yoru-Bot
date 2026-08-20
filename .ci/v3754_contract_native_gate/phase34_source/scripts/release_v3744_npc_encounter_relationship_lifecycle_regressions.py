from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def need(source: str, token: str, label: str) -> None:
    if token not in source:
        raise AssertionError(f"Missing {label}: {token}")


def forbid(source: str, token: str, label: str) -> None:
    if token in source:
        raise AssertionError(f"Forbidden {label}: {token}")


version = text("VERSION").strip()
try:
    version_line = tuple(int(part) for part in version.split(".")[:2])
except ValueError:
    version_line = (0, 0)
if version_line < (3, 74):
    raise AssertionError(f"W13.5 regression gate requires v3.74+ line, got {version}")

npc = text("app/npc_config.py")
memory = text("app/services/memory.py")
adapters = text("app/services/memory_adapters.py")
followups = text("app/services/npc_followups.py")
opportunities = text("app/services/opportunities.py")
housing = text("app/services/housing.py")
training = text("app/services/training.py")
vehicles = text("app/services/vehicles.py")
business = text("app/services/business.py")
community = text("app/cogs/community.py")
social = text("app/services/social_economy.py")
police = text("app/services/police.py")
crew = text("app/services/crew.py")
main = text("app/main.py")
favor_cfg = text("app/npc_favor_config.py")

# Canonical encounter registry: every W13.4 content NPC has an explicit real-domain source.
for token in (
    "NPC_FIRST_CONTACT_SOURCES",
    '"bence_business_contact": frozenset({"business_license_purchased"})',
    '"zoli_black_market_broker": frozenset({"black_market_purchase", "crime_success"})',
    '"reka_property_agent": frozenset({"housing_purchase"})',
    '"akos_training_mentor": frozenset({"training_enrolled", "training_completed"})',
    '"eszter_merchant": frozenset({"business_property_purchased", "player_market_trade"})',
    '"marci_city_contact": frozenset({"travel_completed"})',
    '"tamas_organization_contact": frozenset({"organization_created", "organization_joined"})',
):
    need(npc, token, "first-contact source contract")
for source in (
    "police_crime_incident", "police_street_incident", "police_robbery_incident", "police_heist_incident"
):
    need(npc, source, "Dóra authority encounter source")

# Memory owns semantic, insert-once contact state only.
need(memory, "async def record_first_contact", "first-contact persistence")
need(memory, 'memory_key = _clean_key(f"npc.{npc_key}:first_contact"', "stable first-contact idempotency key")
need(memory, '"contact_unlocked": True', "contact unlock flag")
need(memory, 'flags.setdefault("contact_source", first_source)', "immutable first encounter source")
need(memory, "async def age_resolved_relationships", "resolved relationship lifecycle aging")
need(memory, "AND rival_state='resolved'", "resolved-only aging guard")

# Adapter contract validates source + keeps derived memory post-settlement.
need(adapters, "async def npc_first_contact", "canonical first-contact adapter")
need(adapters, "first_contact_sources", "source allowlist validation")
for method in (
    "training_enrolled", "housing_purchased", "travel_completed", "black_market_purchased",
    "player_market_trade", "organization_membership", "police_incident", "business_property_purchased",
):
    need(adapters, f"async def {method}", f"{method} adapter")
need(adapters, 'npc_key="bence_business_contact", source_key="business_license_purchased"', "Bence license encounter")
need(adapters, 'npc_key="zoli_black_market_broker", source_key="crime_success"', "Zoli crime-success encounter")

# Phone / opportunity lifecycle remains semantic and non-authoritative.
need(followups, "FIRST_CONTACT_FOLLOWUP_HOURS = 72", "first-contact follow-up window")
need(followups, 'key=f"npc_contact_{npc.key}"', "new-contact opportunity")
need(followups, 'required_relationship_flags=("contact_unlocked",)', "contact eligibility flag")
need(followups, "async def notify_first_contact", "first-contact notification")
need(followups, 'status = "Ismerős"', "semantic contact summary")
need(opportunities, "Lifecycle retries/click replays are idempotent", "history lifecycle idempotency")
need(opportunities, "COALESCE(cycle_id,'')=COALESCE(?,'')", "cycle-aware lifecycle dedupe")

# Owning-domain event sources: hooks appear after their authoritative commit path.
for source, token, label in (
    (housing, "housing_purchased(", "housing -> Réka"),
    (training, "training_enrolled(", "training -> Ákos"),
    (vehicles, "travel_completed(", "travel -> Marci"),
    (business, "business_property_purchased(", "business property -> Eszter"),
    (community, "black_market_purchased(", "black market -> Zoli"),
    (social, "player_market_trade(", "player market -> Eszter"),
    (police, "police_incident(", "police incident -> Dóra"),
    (crew, "organization_membership(", "organization -> Tamás"),
):
    need(source, token, label)

need(main, "HousingService(self.database, self.characters, self.memory_adapters)", "housing memory wiring")
need(main, "PoliceService(self.database, self.characters, self.world, self.memory_adapters)", "police memory wiring")
need(crew, "import contextlib", "CrewService runtime suppress import hotfix")

# W13.5 deliberately adds no new favor/economy authority.
for forbidden in ("add_wallet(", "remove_wallet(", "add_item(", "remove_item(", "award_xp("):
    forbid(followups, forbidden, "relationship settlement authority")
    forbid(npc, forbidden, "NPC registry settlement authority")
effect_keys = set(re.findall(r'^\s*"([a-z0-9_]+)"\s*,\s*$', favor_cfg, flags=re.MULTILINE))
# Avoid depending on formatting for count: explicitly require the existing three and forbid W13.5 additions by known class count.
for key in ("jani_repair_discount", "misi_dealership_discount", "bence_business_license_discount"):
    need(favor_cfg, key, f"existing favor effect {key}")
if favor_cfg.count("FavorEffectDefinition(") != 3:
    raise AssertionError("W13.5 must not add a new effectful favor without an owning-domain transaction contract")

# No raw relationship tuning is introduced into the new player-facing follow-up copy.
for raw in ("trust_score", "favor_owed_to_player=", "favor_owed_by_player="):
    forbid(followups, raw, "raw relationship value in follow-up service")

print("W13.5 NPC ENCOUNTER SOURCES / RELATIONSHIP LIFECYCLE REGRESSION PASS")
