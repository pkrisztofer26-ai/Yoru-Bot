from __future__ import annotations

"""Canonical Phase 3 NPC registry.

The registry owns stable NPC identity keys, Hungarian display forms and coarse
role capabilities only. It does not own relationship state, rewards, contracts,
world eligibility or dialogue history. Those remain in their deterministic
services / ConsequenceMemoryService.

W13.4 expands the roster deliberately: every new identity has a concrete Yoru
system destination, but no invented biography, employer, city history or reward.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NPCRoleDefinition:
    key: str
    label: str
    relationship_capable: bool = True
    private_opportunity_capable: bool = True
    notification_capable: bool = True


@dataclass(frozen=True, slots=True)
class NPCDefinition:
    key: str
    display_name: str
    role_key: str
    role_label: str
    emoji: str
    with_name: str
    tags: tuple[str, ...] = ()
    relationship_capable: bool = True
    private_opportunity_capable: bool = True
    notification_capable: bool = True


NPC_ROLES: tuple[NPCRoleDefinition, ...] = (
    NPCRoleDefinition("job_agent", "Munkaközvetítő"),
    NPCRoleDefinition("car_dealer", "Autónepper"),
    NPCRoleDefinition("mechanic", "Szerelő"),
    NPCRoleDefinition("dispatcher", "Fuvaros / diszpécser"),
    NPCRoleDefinition("business_contact", "Vállalkozói kontakt"),
    NPCRoleDefinition("black_market_broker", "Feketepiaci közvetítő"),
    NPCRoleDefinition("legal_contact", "Jogi / hatósági kontakt"),
    NPCRoleDefinition("property_agent", "Ingatlanos"),
    NPCRoleDefinition("training_mentor", "Képzési mentor"),
    NPCRoleDefinition("merchant", "Kereskedő"),
    NPCRoleDefinition("city_contact", "Helyi kapcsolat"),
    NPCRoleDefinition("organization_contact", "Szervezeti kapcsolat"),
)
ROLE_BY_KEY: dict[str, NPCRoleDefinition] = {item.key: item for item in NPC_ROLES}


# The original four came from the W12 Human-QA benchmark. W13.4 adds an
# intentionally small first content pack around already-existing systems.
# No identity below asserts biography beyond its role/tags.
NPCS: tuple[NPCDefinition, ...] = (
    NPCDefinition("kata_job_agent", "Kata", "job_agent", "Munkaközvetítő", "💼", "Katával", ("career", "jobs")),
    NPCDefinition("misi_car_dealer", "Misi", "car_dealer", "Autónepper", "🚗", "Misivel", ("vehicle", "market")),
    NPCDefinition("jani_mechanic", "Jani", "mechanic", "Szerelő", "🔧", "Janival", ("vehicle", "repair")),
    NPCDefinition("lilla_dispatcher", "Lilla", "dispatcher", "Fuvaros / diszpécser", "📦", "Lillával", ("career", "transport")),

    NPCDefinition("bence_business_contact", "Bence", "business_contact", "Vállalkozói kontakt", "🏢", "Bencével", ("business", "license")),
    NPCDefinition("zoli_black_market_broker", "Zoli", "black_market_broker", "Feketepiaci közvetítő", "🌑", "Zolival", ("blackmarket", "market")),
    NPCDefinition("dora_legal_contact", "Dóra", "legal_contact", "Jogi / hatósági kontakt", "⚖️", "Dórával", ("authority", "legal")),
    NPCDefinition("reka_property_agent", "Réka", "property_agent", "Ingatlanos", "🏠", "Rékával", ("housing", "property")),
    NPCDefinition("akos_training_mentor", "Ákos", "training_mentor", "Képzési mentor", "🎓", "Ákossal", ("training", "qualification")),
    NPCDefinition("eszter_merchant", "Eszter", "merchant", "Kereskedő", "🛍️", "Eszterrel", ("business", "market")),
    NPCDefinition("marci_city_contact", "Marci", "city_contact", "Helyi kapcsolat", "📍", "Marcival", ("world", "travel")),
    NPCDefinition("tamas_organization_contact", "Tamás", "organization_contact", "Szervezeti kapcsolat", "🤝", "Tamással", ("organization", "community")),
)
NPC_BY_KEY: dict[str, NPCDefinition] = {item.key: item for item in NPCS}

# W13.2 reserved these roles. W13.4 deliberately names them, so no current
# role slot is implicitly free for ad-hoc creation.
RESERVED_ROLE_SLOTS: frozenset[str] = frozenset()


# W13.5 deterministic first-contact source contract. These are technical
# lifecycle source keys only; they do not add biography, dialogue or rewards.
# A source may unlock a contact only after its owning domain action has already
# settled successfully.
NPC_FIRST_CONTACT_SOURCES: dict[str, frozenset[str]] = {
    "bence_business_contact": frozenset({"business_license_purchased"}),
    "zoli_black_market_broker": frozenset({"black_market_purchase", "crime_success"}),
    "dora_legal_contact": frozenset({
        "police_crime_incident", "police_street_incident",
        "police_robbery_incident", "police_heist_incident",
    }),
    "reka_property_agent": frozenset({"housing_purchase"}),
    "akos_training_mentor": frozenset({"training_enrolled", "training_completed"}),
    "eszter_merchant": frozenset({"business_property_purchased", "player_market_trade"}),
    "marci_city_contact": frozenset({"travel_completed"}),
    "tamas_organization_contact": frozenset({"organization_created", "organization_joined"}),
}


def first_contact_sources(npc_key: str) -> frozenset[str]:
    return NPC_FIRST_CONTACT_SOURCES.get(npc(npc_key).key, frozenset())


def npc(key: str) -> NPCDefinition:
    value = NPC_BY_KEY.get(str(key).strip().lower())
    if value is None:
        raise KeyError(f"Ismeretlen NPC: {key}")
    return value


def maybe_npc(key: str | None) -> NPCDefinition | None:
    if not key:
        return None
    return NPC_BY_KEY.get(str(key).strip().lower())


def role(key: str) -> NPCRoleDefinition:
    value = ROLE_BY_KEY.get(str(key).strip().lower())
    if value is None:
        raise KeyError(f"Ismeretlen NPC szerepkör: {key}")
    return value
