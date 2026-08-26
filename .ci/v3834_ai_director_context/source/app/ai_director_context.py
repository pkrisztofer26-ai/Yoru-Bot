from __future__ import annotations

"""Phase 12 Tier 2 bounded Context AI contract.

Tier 2 may receive a small set of already-known presentation facts, but it still
owns no gameplay truth.  The host chooses the domain, fact schema, fallback and
required anchors before a provider is called.  Provider output remains
presentation-only ``title`` + ``description``.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping


CONTEXT_CONTRACT_VERSION = "tier2-context-surface-v2"
CONTEXT_FIELD_NAME = "🌙 Yoru Director • Kontext teszt"
CONTEXT_DOMAINS = frozenset({"career", "business", "travel", "housing", "npc", "tips", "case"})
CONTEXT_TITLE_MAX = 120
CONTEXT_DESCRIPTION_MAX = 560
CONTEXT_FACT_VALUE_MAX = 160

_CONTEXT_ALLOWED_FACT_KEYS: Mapping[str, frozenset[str]] = {
    "career": frozenset({"career_name", "employer", "city", "position"}),
    "business": frozenset({"business_name", "category", "city", "operating_model"}),
    "travel": frozenset({"current_city", "destination_city", "travel_mode"}),
    "housing": frozenset({"home_city", "housing_tier", "location_state"}),
    "npc": frozenset({"npc_name", "npc_role", "relationship_state"}),
    "tips": frozenset({"topic", "source_label", "certainty"}),
    "case": frozenset({"case_type", "case_status", "subject"}),
}

_FORBIDDEN_FACT_KEYS = frozenset({
    "amount", "reward", "payout", "money", "wallet", "bank", "xp", "score",
    "inventory", "item", "items", "cooldown", "chance", "probability", "roll",
    "rng", "success", "failed", "outcome", "settlement", "heat", "police",
    "choice", "choices", "branch", "mechanical_intent", "requirements", "user_id",
    "guild_id", "case_id", "property_id", "vehicle_id", "contract_id",
})

# Live context output receives a stricter language gate than the offline Tier 1
# paraphraser.  The context contract deliberately carries no numeric facts, so
# digits/currency/probability/mechanical promises are always suspicious.
_FORBIDDEN_OUTPUT_RE = re.compile(
    r"(?:\d|\b(?:ft|forint|jutalom|kifizetés|payout|esély|százalék|cooldown|xp|inventory|"
    r"wallet|bank|rng|garantált\s+siker|biztos\s+siker|biztosan\s+nyersz)\b|<@|https?://)",
    re.IGNORECASE,
)
_FORBIDDEN_META_OUTPUT_RE = re.compile(
    r"\b(?:canonical|authority|mechanikai|validator|fallback|provider|contract)\b",
    re.IGNORECASE,
)
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")


class AIDirectorContextValidationError(ValueError):
    pass


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass(frozen=True, slots=True)
class AIDirectorContextPacket:
    context_key: str
    domain: str
    semantic_slot: str
    fallback_title: str
    fallback_description: str
    facts: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False, repr=False)
    required_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    contract_version: str = CONTEXT_CONTRACT_VERSION

    def digest(self) -> str:
        payload = {
            "context_key": self.context_key,
            "domain": self.domain,
            "semantic_slot": self.semantic_slot,
            "fallback_title": self.fallback_title,
            "fallback_description": self.fallback_description,
            "facts": {str(k): str(v) for k, v in sorted(self.facts.items())},
            "required_terms": list(self.required_terms),
            "tags": list(self.tags),
            "contract_version": self.contract_version,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AIDirectorContextSurface:
    context_key: str
    domain: str
    title: str
    description: str
    source: str
    packet_digest: str
    contract_version: str


def validate_context_packet(packet: AIDirectorContextPacket) -> AIDirectorContextPacket:
    for value, label in (
        (packet.context_key, "context_key"),
        (packet.domain, "domain"),
        (packet.semantic_slot, "semantic_slot"),
        (packet.contract_version, "contract_version"),
    ):
        if not _KEY_RE.fullmatch(str(value or "")):
            raise AIDirectorContextValidationError(f"Érvénytelen {label}: {value!r}")
    if packet.domain not in CONTEXT_DOMAINS:
        raise AIDirectorContextValidationError(f"Nem Tier 2 context domain: {packet.domain}")
    if packet.contract_version != CONTEXT_CONTRACT_VERSION:
        raise AIDirectorContextValidationError("Ismeretlen Tier 2 context contract verzió.")
    if not packet.fallback_title.strip() or len(packet.fallback_title) > CONTEXT_TITLE_MAX:
        raise AIDirectorContextValidationError("Hibás context fallback title.")
    if not packet.fallback_description.strip() or len(packet.fallback_description) > CONTEXT_DESCRIPTION_MAX:
        raise AIDirectorContextValidationError("Hibás context fallback description.")
    if len(packet.facts) > 8 or len(packet.required_terms) > 6 or len(packet.tags) > 8:
        raise AIDirectorContextValidationError("Túl nagy Tier 2 context packet.")
    allowed = _CONTEXT_ALLOWED_FACT_KEYS[packet.domain]
    for key, value in packet.facts.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in _FORBIDDEN_FACT_KEYS or normalized_key not in allowed:
            raise AIDirectorContextValidationError(f"Tiltott/unknown context fact: {key}")
        text = str(value).strip()
        if not text or len(text) > CONTEXT_FACT_VALUE_MAX:
            raise AIDirectorContextValidationError(f"Hibás context fact érték: {key}")
        if _FORBIDDEN_OUTPUT_RE.search(text):
            raise AIDirectorContextValidationError(f"Mechanikai/numerikus context fact nem adható át: {key}")
    return packet


def validate_context_surface(packet: AIDirectorContextPacket, raw: Mapping[str, Any]) -> tuple[str, str]:
    validate_context_packet(packet)
    if not isinstance(raw, Mapping):
        raise AIDirectorContextValidationError("A Tier 2 AI surface nem objektum.")
    if {str(key) for key in raw.keys()} != {"title", "description"}:
        raise AIDirectorContextValidationError("A Tier 2 AI surface csak title + description lehet.")
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "").strip()
    if not title or len(title) > CONTEXT_TITLE_MAX:
        raise AIDirectorContextValidationError("Hibás Tier 2 title.")
    if not description or len(description) > CONTEXT_DESCRIPTION_MAX:
        raise AIDirectorContextValidationError("Hibás Tier 2 description.")
    merged = f"{title}\n{description}"
    if _FORBIDDEN_OUTPUT_RE.search(merged):
        raise AIDirectorContextValidationError("A Tier 2 AI mechanikai/numerikus állítást próbált hozzáadni.")
    if _FORBIDDEN_META_OUTPUT_RE.search(merged):
        raise AIDirectorContextValidationError("A Tier 2 AI belső rendszerzsargont próbált player-facing szövegbe tenni.")
    folded = _fold(merged)
    for term in packet.required_terms:
        anchor = _fold(str(term).strip())
        if anchor and anchor not in folded:
            raise AIDirectorContextValidationError(f"Hiányzó Tier 2 grounding anchor: {term}")
    return title, description


def fallback_context_surface(packet: AIDirectorContextPacket) -> AIDirectorContextSurface:
    validate_context_packet(packet)
    return AIDirectorContextSurface(
        context_key=packet.context_key,
        domain=packet.domain,
        title=packet.fallback_title.strip(),
        description=packet.fallback_description.strip(),
        source="deterministic_context_fallback",
        packet_digest=packet.digest(),
        contract_version=packet.contract_version,
    )


def _packet(domain: str, semantic_slot: str, facts: Mapping[str, str], title: str, description: str, *, required: tuple[str, ...]) -> AIDirectorContextPacket:
    packet = AIDirectorContextPacket(
        context_key=f"{domain}.{semantic_slot}", domain=domain, semantic_slot=semantic_slot,
        fallback_title=title, fallback_description=description, facts=dict(facts),
        required_terms=required, tags=("tier2", "context", "test_guild"),
    )
    return validate_context_packet(packet)


def career_context_packet(*, career_name: str, employer: str, city: str, position: str) -> AIDirectorContextPacket:
    return _packet(
        "career", "employment_snapshot",
        {"career_name": career_name, "employer": employer, "city": city, "position": position},
        "Munkahelyi helyzetkép",
        f"A {employer} csapatánál {career_name} munkakörben dolgozol {city} területén. Jelenlegi szerepköröd: {position}.",
        required=(career_name, city, employer),
    )


def business_context_packet(*, business_name: str, category: str, city: str, operating_model: str) -> AIDirectorContextPacket:
    return _packet(
        "business", "portfolio_snapshot",
        {"business_name": business_name, "category": category, "city": city, "operating_model": operating_model},
        "Üzleti helyzetkép",
        f"A {business_name} {city} területén működő, {category} profilú vállalkozás. Működési iránya: {operating_model}.",
        required=(business_name, city, operating_model),
    )


def travel_context_packet(*, current_city: str, destination_city: str | None = None, travel_mode: str | None = None) -> AIDirectorContextPacket:
    facts = {"current_city": current_city}
    if destination_city:
        facts["destination_city"] = destination_city
    if travel_mode:
        facts["travel_mode"] = travel_mode
    if destination_city:
        if travel_mode:
            desc = f"Jelenleg {current_city} területén vagy; úticélod {destination_city}, a választott közlekedési mód pedig {travel_mode}."
        else:
            desc = f"Jelenleg {current_city} területén vagy; úticélod {destination_city}."
        required = (current_city, destination_city)
    else:
        desc = f"Jelenleg {current_city} területén vagy. Innen az elérhető útvonalak közül választhatsz."
        required = (current_city,)
    return _packet("travel", "route_snapshot", facts, "Utazási helyzetkép", desc, required=required)


def housing_context_packet(*, home_city: str, housing_tier: str, location_state: str) -> AIDirectorContextPacket:
    return _packet(
        "housing", "home_snapshot",
        {"home_city": home_city, "housing_tier": housing_tier, "location_state": location_state},
        "Otthoni helyzetkép",
        f"Az otthonod {home_city} területén található; típusa: {housing_tier}. Jelenlegi helyzet: {location_state}.",
        required=(home_city, housing_tier),
    )


def npc_context_packet(*, npc_name: str, npc_role: str, relationship_state: str) -> AIDirectorContextPacket:
    return _packet(
        "npc", "relationship_snapshot",
        {"npc_name": npc_name, "npc_role": npc_role, "relationship_state": relationship_state},
        "Kapcsolati helyzetkép",
        f"{npc_name} ({npc_role}) felől most {relationship_state} jellegű ügy látszik.",
        required=(npc_name, npc_role),
    )


def tips_context_packet(*, topic: str, source_label: str, certainty: str) -> AIDirectorContextPacket:
    return _packet(
        "tips", "tip_snapshot",
        {"topic": topic, "source_label": source_label, "certainty": certainty},
        "Füles a háttérben",
        f"{topic} témában a {source_label} felől érkezett {certainty}. Ez önmagában még nem jelez biztos kimenetelt.",
        required=(topic, source_label),
    )


def case_context_packet(*, case_type: str, case_status: str, subject: str) -> AIDirectorContextPacket:
    return _packet(
        "case", "case_snapshot",
        {"case_type": case_type, "case_status": case_status, "subject": subject},
        "Ügyhelyzet",
        f"{subject} jelenleg {case_status} {case_type} ügyként szerepel.",
        required=(subject, case_status),
    )
