from __future__ import annotations

"""Phase 12 Tier 3 AI Game Master foundation contract.

The Game Master layer may narrate only host-owned facts that were already
resolved by canonical deterministic services.  It never chooses gameplay truth,
branches, rewards, success/failure, permissions, inventory or state mutation.
W22.6 opens bounded player-facing presentation only behind explicit test-guild opt-in; host services remain authoritative.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping


GAME_MASTER_CONTRACT_VERSION = "tier3-game-master-surface-v6"
GAME_MASTER_RUNTIME_ENABLED_DEFAULT = False
GAME_MASTER_FAMILIES = frozenset({
    "big_job",
    "npc_story",
    "consequence_recall",
    "chapter",
    "world_story",
    "legendary_event",
})
GAME_MASTER_TITLE_MAX = 120
GAME_MASTER_DESCRIPTION_MAX = 760
GAME_MASTER_FACT_VALUE_MAX = 220

_ALLOWED_FACT_KEYS: Mapping[str, frozenset[str]] = {
    "big_job": frozenset({"target_name", "phase_label", "approach_label", "route_label", "host_resolution", "consequence_note"}),
    "npc_story": frozenset({"npc_name", "npc_role", "relationship_band", "recalled_event", "current_story_state"}),
    "consequence_recall": frozenset({"subject_label", "memory_category", "remembered_event", "current_relevance"}),
    "chapter": frozenset({"chapter_title", "stage_title", "world_story_title", "community_note", "host_ending"}),
    "world_story": frozenset({"national_title", "story_title", "beat_title", "city_label", "world_note"}),
    "legendary_event": frozenset({"event_name", "access_context", "phase_label", "host_resolution", "legacy_note"}),
}

_FORBIDDEN_FACT_KEYS = frozenset({
    "amount", "reward", "payout", "money", "wallet", "bank", "xp", "score", "weight", "weights",
    "trust_score", "inventory", "item", "items", "cooldown", "chance", "probability", "roll", "rng",
    "success", "failed", "outcome", "settlement", "heat", "police", "choice", "choices", "branch",
    "mechanical_intent", "requirements", "user_id", "guild_id", "run_id", "lobby_id", "case_id",
    "chapter_run_id", "property_id", "vehicle_id", "contract_id", "memory_id",
})

_FORBIDDEN_OUTPUT_RE = re.compile(
    r"(?:\d|\b(?:ft|forint|jutalom|kifizetés|payout|esély|százalék|cooldown|xp|inventory|wallet|bank|rng|"
    r"garantált\s+siker|biztos\s+siker|biztosan\s+nyersz|válaszd|kattints|parancs)\b|<@|https?://)",
    re.IGNORECASE,
)
_FORBIDDEN_META_OUTPUT_RE = re.compile(
    r"\b(?:canonical|authority|mechanikai|validator|fallback|provider|contract|host[_ -]?fact|schema|json)\b",
    re.IGNORECASE,
)
_FORBIDDEN_AUTHORITY_CLAIM_RE = re.compile(
    r"\b(?:eldönti|meghatározza|garantálja|megváltoztatja|jóváhagyja|feloldja)\b.{0,50}\b(?:eredmény|jutalom|"
    r"kimenetel|ág|branch|állapot|hozzáférés)\b",
    re.IGNORECASE | re.DOTALL,
)

# Human-review-derived Tier 3 presentation quality regressions. These rules are
# presentation-only and never change gameplay truth; they only force the
# deterministic fallback when generated Hungarian is awkward or overstates the
# host-owned facts.
_HUMAN_DERIVED_SURFACE_REJECTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:részsiker|siker)\s+lezárást\s+kapott\b", re.IGNORECASE), "unnatural_resolution_phrase"),
    (re.compile(r"\bfelé\s+(?:közeledik|ért)\b", re.IGNORECASE), "unsupported_temporal_progression"),
    (re.compile(r"\.\s+[a-záéíóöőúüű]", re.UNICODE), "lowercase_sentence_start"),
    (re.compile(r"\b(?:örökre|legendákban|legendává|emlékezetes(?:\s+kaland)?|mesékben)\b", re.IGNORECASE), "unsupported_embellishment"),
    (re.compile(r"\b([a-záéíóöőúüű]{3,})\s+\1\b", re.IGNORECASE), "repeated_word"),
    (re.compile(r"\ba\s+[aáeéiíoóöőuúüű]", re.IGNORECASE), "wrong_hungarian_article"),
    (re.compile(r"\btörténetszál\s+[^.!?]{1,80}\s+pontja\b", re.IGNORECASE), "awkward_story_beat_phrase"),
    (re.compile(r"\bhangulatban\s+(?:áll|van)\s+veled\b", re.IGNORECASE), "awkward_npc_relation_phrase"),
    (re.compile(r"\bállapota\s+húzódik\b", re.IGNORECASE), "awkward_chapter_background_phrase"),
    (re.compile(r"\blezárása\b.{0,36}\bzárult\b", re.IGNORECASE | re.DOTALL), "redundant_closure_phrase"),
)
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")


class AIDirectorGameMasterValidationError(ValueError):
    pass


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _sentence_lead(value: str) -> str:
    text = str(value).strip()
    if not text:
        return text
    return text[:1].upper() + text[1:]


def game_master_surface_quality_errors(packet: AIDirectorGameMasterPacket, title: str, description: str) -> tuple[str, ...]:
    merged = f"{str(title).strip()}\n{str(description).strip()}"
    errors: list[str] = []
    for pattern, label in _HUMAN_DERIVED_SURFACE_REJECTIONS:
        if pattern.search(merged):
            errors.append(label)
    causal_re = re.compile(
        r"\b(?:hiszen|mivel|ezért|emiatt|ennek\s+köszönhetően|következtében)\b",
        re.IGNORECASE,
    )
    if packet.family in {"npc_story", "consequence_recall"} and causal_re.search(merged):
        errors.append("unsupported_memory_causality")
    if packet.family == "npc_story":
        npc_name = str(packet.facts.get("npc_name", "")).strip()
        npc_role = str(packet.facts.get("npc_role", "")).strip()
        if npc_name and npc_role and re.search(
            r"(?:^|[\n.!?]\s*)" + re.escape(npc_name) + r"\s*,\s*" + re.escape(npc_role) + r"\s*[.!?]",
            merged,
            re.IGNORECASE,
        ):
            errors.append("awkward_npc_role_fragment")

    facts_folded = _fold(" ".join(str(value) for value in packet.facts.values()))
    merged_folded = _fold(merged)
    # Human-review-derived ambient/world expansion tokens. These are allowed only
    # when the host facts already contain the same concept.
    for token in ("kornyek", "pletyka", "sajto", "tanu", "hatosag"):
        if token in merged_folded and token not in facts_folded:
            errors.append("unsupported_ambient_expansion")
            break
    if packet.family == "big_job":
        target = str(packet.facts.get("target_name", "")).strip()
        if target and _fold(target) in merged_folded and not re.search(r"(?<!\w)" + re.escape(target) + r"(?!\w)", merged, re.IGNORECASE):
            errors.append("inflected_target_label")
    if packet.family == "chapter":
        stage = _fold(packet.facts.get("stage_title", "")).strip()
        if stage and re.search(r"\b" + re.escape(stage) + r"\s+szakaszban\b", merged_folded):
            errors.append("awkward_chapter_stage_case")
    if packet.family == "world_story":
        beat = _fold(packet.facts.get("beat_title", "")).strip()
        if beat and re.search(re.escape(beat) + r"[^a-z0-9]{0,4}pontja\b", merged_folded):
            errors.append("awkward_story_beat_phrase")
        city = str(packet.facts.get("city_label", "")).strip()
        if city and _fold(city) in merged_folded and not re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", merged, re.IGNORECASE):
            errors.append("inflected_city_label")
        if "csendben" in merged_folded and "csendben" not in facts_folded:
            errors.append("unsupported_narrative_modifier")
    if packet.family == "legendary_event":
        for token in ("emlek", "mese"):
            if token in merged_folded and token not in facts_folded:
                errors.append("unsupported_legacy_reframing")
                break
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class AIDirectorGameMasterPacket:
    story_key: str
    family: str
    semantic_slot: str
    fallback_title: str
    fallback_description: str
    facts: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False, repr=False)
    required_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    contract_version: str = GAME_MASTER_CONTRACT_VERSION

    def digest(self) -> str:
        payload = {
            "story_key": self.story_key,
            "family": self.family,
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
class AIDirectorGameMasterSurface:
    story_key: str
    family: str
    title: str
    description: str
    source: str
    packet_digest: str
    contract_version: str


def validate_game_master_packet(packet: AIDirectorGameMasterPacket) -> AIDirectorGameMasterPacket:
    for value, label in (
        (packet.story_key, "story_key"),
        (packet.family, "family"),
        (packet.semantic_slot, "semantic_slot"),
        (packet.contract_version, "contract_version"),
    ):
        if not _KEY_RE.fullmatch(str(value or "")):
            raise AIDirectorGameMasterValidationError(f"Érvénytelen {label}: {value!r}")
    if packet.family not in GAME_MASTER_FAMILIES:
        raise AIDirectorGameMasterValidationError(f"Nem Tier 3 Game Master family: {packet.family}")
    if packet.contract_version != GAME_MASTER_CONTRACT_VERSION:
        raise AIDirectorGameMasterValidationError("Ismeretlen Tier 3 Game Master contract verzió.")
    if not packet.fallback_title.strip() or len(packet.fallback_title) > GAME_MASTER_TITLE_MAX:
        raise AIDirectorGameMasterValidationError("Hibás Game Master fallback title.")
    if not packet.fallback_description.strip() or len(packet.fallback_description) > GAME_MASTER_DESCRIPTION_MAX:
        raise AIDirectorGameMasterValidationError("Hibás Game Master fallback description.")
    if len(packet.facts) > 8 or len(packet.required_terms) > 6 or len(packet.tags) > 8:
        raise AIDirectorGameMasterValidationError("Túl nagy Tier 3 Game Master packet.")
    allowed = _ALLOWED_FACT_KEYS[packet.family]
    for key, value in packet.facts.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in _FORBIDDEN_FACT_KEYS or normalized_key not in allowed:
            raise AIDirectorGameMasterValidationError(f"Tiltott/unknown Game Master fact: {key}")
        text = str(value).strip()
        if not text or len(text) > GAME_MASTER_FACT_VALUE_MAX:
            raise AIDirectorGameMasterValidationError(f"Hibás Game Master fact érték: {key}")
        if _FORBIDDEN_OUTPUT_RE.search(text):
            raise AIDirectorGameMasterValidationError(f"Mechanikai/numerikus Game Master fact nem adható át: {key}")
    return packet


def validate_game_master_surface(packet: AIDirectorGameMasterPacket, raw: Mapping[str, Any]) -> tuple[str, str]:
    validate_game_master_packet(packet)
    if not isinstance(raw, Mapping):
        raise AIDirectorGameMasterValidationError("A Tier 3 AI surface nem objektum.")
    if {str(key) for key in raw.keys()} != {"title", "description"}:
        raise AIDirectorGameMasterValidationError("A Tier 3 AI surface csak title + description lehet.")
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "").strip()
    if not title or len(title) > GAME_MASTER_TITLE_MAX:
        raise AIDirectorGameMasterValidationError("Hibás Tier 3 title.")
    if not description or len(description) > GAME_MASTER_DESCRIPTION_MAX:
        raise AIDirectorGameMasterValidationError("Hibás Tier 3 description.")
    merged = f"{title}\n{description}"
    if _FORBIDDEN_OUTPUT_RE.search(merged):
        raise AIDirectorGameMasterValidationError("A Tier 3 AI mechanikai/numerikus állítást próbált hozzáadni.")
    if _FORBIDDEN_META_OUTPUT_RE.search(merged):
        raise AIDirectorGameMasterValidationError("A Tier 3 AI belső rendszerzsargont próbált player-facing szövegbe tenni.")
    if _FORBIDDEN_AUTHORITY_CLAIM_RE.search(merged):
        raise AIDirectorGameMasterValidationError("A Tier 3 AI authority-jellegű állítást próbált tenni.")
    quality_errors = game_master_surface_quality_errors(packet, title, description)
    if quality_errors:
        raise AIDirectorGameMasterValidationError(
            "A Tier 3 AI human-review quality guardon bukott: " + ",".join(quality_errors)
        )
    folded = _fold(merged)
    for term in packet.required_terms:
        anchor = _fold(str(term).strip())
        if anchor and anchor not in folded:
            raise AIDirectorGameMasterValidationError(f"Hiányzó Tier 3 grounding anchor: {term}")
    return title, description


def fallback_game_master_surface(packet: AIDirectorGameMasterPacket) -> AIDirectorGameMasterSurface:
    validate_game_master_packet(packet)
    return AIDirectorGameMasterSurface(
        story_key=packet.story_key,
        family=packet.family,
        title=packet.fallback_title.strip(),
        description=packet.fallback_description.strip(),
        source="deterministic_scenario_v2_fallback",
        packet_digest=packet.digest(),
        contract_version=packet.contract_version,
    )


def _packet(
    family: str,
    semantic_slot: str,
    facts: Mapping[str, str],
    title: str,
    description: str,
    *,
    required: tuple[str, ...],
) -> AIDirectorGameMasterPacket:
    packet = AIDirectorGameMasterPacket(
        story_key=f"{family}.{semantic_slot}",
        family=family,
        semantic_slot=semantic_slot,
        fallback_title=title,
        fallback_description=description,
        facts=dict(facts),
        required_terms=required,
        tags=("tier3", "game_master", "foundation", "test_guild"),
    )
    return validate_game_master_packet(packet)


def big_job_packet(*, target_name: str, phase_label: str, approach_label: str, route_label: str, host_resolution: str, consequence_note: str) -> AIDirectorGameMasterPacket:
    return _packet(
        "big_job", "resolved_scene",
        {"target_name": target_name, "phase_label": phase_label, "approach_label": approach_label, "route_label": route_label,
         "host_resolution": host_resolution, "consequence_note": consequence_note},
        "A Nagy Meló visszhangja",
        f"„{target_name}” — az akció lezárása: {host_resolution}. Megközelítés: {approach_label}. Útvonal: {route_label}. {_sentence_lead(consequence_note)}.",
        required=(target_name, host_resolution),
    )


def npc_story_packet(*, npc_name: str, npc_role: str, relationship_band: str, recalled_event: str, current_story_state: str) -> AIDirectorGameMasterPacket:
    return _packet(
        "npc_story", "relationship_callback",
        {"npc_name": npc_name, "npc_role": npc_role, "relationship_band": relationship_band,
         "recalled_event": recalled_event, "current_story_state": current_story_state},
        f"{npc_name} emlékszik",
        f"{npc_name} szerepe: {npc_role}. Kapcsolati állapot: {relationship_band}. Felidézett esemény: {_sentence_lead(recalled_event)}. Jelenlegi történeti helyzet: {_sentence_lead(current_story_state)}.",
        required=(npc_name, recalled_event),
    )


def consequence_recall_packet(*, subject_label: str, memory_category: str, remembered_event: str, current_relevance: str) -> AIDirectorGameMasterPacket:
    return _packet(
        "consequence_recall", "memory_echo",
        {"subject_label": subject_label, "memory_category": memory_category, "remembered_event": remembered_event,
         "current_relevance": current_relevance},
        "Egy régi döntés visszhangja",
        f"{_sentence_lead(subject_label)} kapcsán újra előkerül, hogy {remembered_event}. A jelenlegi összefüggés: {current_relevance}.",
        required=(subject_label, remembered_event),
    )


def chapter_packet(*, chapter_title: str, stage_title: str, world_story_title: str, community_note: str, host_ending: str | None = None) -> AIDirectorGameMasterPacket:
    facts = {"chapter_title": chapter_title, "stage_title": stage_title, "world_story_title": world_story_title, "community_note": community_note}
    if host_ending:
        facts["host_ending"] = host_ending
        desc = f"A „{chapter_title}” fejezet lezárása: {host_ending}. Utolsó szakasz: {stage_title}. Háttértörténet: {world_story_title}. {_sentence_lead(community_note)}."
        required = (chapter_title, host_ending)
    else:
        desc = f"A „{chapter_title}” fejezet jelenlegi szakasza: {stage_title}. Háttértörténet: {world_story_title}. {_sentence_lead(community_note)}."
        required = (chapter_title, stage_title)
    return _packet("chapter", "chapter_scene", facts, "A fejezet helyzete", desc, required=required)


def world_story_packet(*, national_title: str, story_title: str, beat_title: str, city_label: str, world_note: str) -> AIDirectorGameMasterPacket:
    return _packet(
        "world_story", "world_beat",
        {"national_title": national_title, "story_title": story_title, "beat_title": beat_title,
         "city_label": city_label, "world_note": world_note},
        story_title,
        f"Országos háttér: „{national_title}”. Történetszál: „{story_title}”. Aktuális pont: „{beat_title}”. Helyszín: {city_label}. {_sentence_lead(world_note)}.",
        required=(story_title, beat_title),
    )


def legendary_event_packet(*, event_name: str, access_context: str, phase_label: str, host_resolution: str, legacy_note: str) -> AIDirectorGameMasterPacket:
    return _packet(
        "legendary_event", "legendary_resolution",
        {"event_name": event_name, "access_context": access_context, "phase_label": phase_label,
         "host_resolution": host_resolution, "legacy_note": legacy_note},
        "Legendás ügy",
        f"„{event_name}” történetének lezárása: {host_resolution}. Szakasz: {phase_label}. {_sentence_lead(legacy_note)}.",
        required=(event_name, host_resolution),
    )
