from __future__ import annotations

"""Phase 12 Tier 3 AI Game Master foundation contract.

The Game Master layer may narrate only host-owned facts that were already
resolved by canonical deterministic services.  It never chooses gameplay truth,
branches, rewards, success/failure, permissions, inventory or state mutation.
W22.5/W22.5.1/W22.5.1.1 deliberately ship no player-facing call sites.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping


GAME_MASTER_CONTRACT_VERSION = "tier3-game-master-surface-v3"
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

    facts_folded = _fold(" ".join(str(value) for value in packet.facts.values()))
    merged_folded = _fold(merged)
    # Human-review-derived ambient/world expansion tokens. These are allowed only
    # when the host facts already contain the same concept.
    for token in ("kornyek", "pletyka", "sajto", "tanu", "hatosag"):
        if token in merged_folded and token not in facts_folded:
            errors.append("unsupported_ambient_expansion")
            break
    if packet.family == "world_story":
        beat = _fold(packet.facts.get("beat_title", "")).strip()
        if beat and re.search(re.escape(beat) + r"[^a-z0-9]{0,4}pontja\b", merged_folded):
            errors.append("awkward_story_beat_phrase")
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
        (packet.family, "family"��="2