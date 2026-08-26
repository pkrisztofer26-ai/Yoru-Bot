from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from app import ai_director_config as cfg

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")


class AIDirectorValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AIDirectorPacket:
    """Host-owned semantic packet handed to the narrative layer.

    All authoritative facts are supplied before the provider is called.  The
    provider cannot add choices, mechanics or settlement data through this
    contract.
    """

    content_key: str
    family: str
    semantic_slot: str
    fallback_title: str
    fallback_description: str
    facts: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False, repr=False)
    required_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    contract_version: str = cfg.AI_DIRECTOR_CONTRACT_VERSION

    def digest(self) -> str:
        payload = {
            "content_key": self.content_key,
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
class AIDirectorSurface:
    content_key: str
    family: str
    title: str
    description: str
    source: str
    packet_digest: str
    contract_version: str

    @property
    def ai_generated(self) -> bool:
        return self.source == "ai_cached"


class AIDirectorProvider(Protocol):
    async def generate_surface(self, packet: AIDirectorPacket) -> Mapping[str, Any]: ...


def validate_packet(packet: AIDirectorPacket) -> AIDirectorPacket:
    for value, label in (
        (packet.content_key, "content_key"),
        (packet.family, "family"),
        (packet.semantic_slot, "semantic_slot"),
        (packet.contract_version, "contract_version"),
    ):
        if not _KEY_RE.fullmatch(str(value or "")):
            raise AIDirectorValidationError(f"Érvénytelen {label}: {value!r}")
    if packet.family not in cfg.AI_DIRECTOR_TIER1_FAMILIES:
        raise AIDirectorValidationError(f"Nem Tier 1 AI family: {packet.family}")
    if not packet.fallback_title.strip() or len(packet.fallback_title) > cfg.AI_DIRECTOR_TITLE_MAX:
        raise AIDirectorValidationError("Hibás deterministic fallback title.")
    if not packet.fallback_description.strip() or len(packet.fallback_description) > cfg.AI_DIRECTOR_DESCRIPTION_MAX:
        raise AIDirectorValidationError("Hibás deterministic fallback description.")
    if len(packet.facts) > 24 or len(packet.required_terms) > 16 or len(packet.tags) > 16:
        raise AIDirectorValidationError("Túl nagy AI grounding packet.")
    for key, value in packet.facts.items():
        if not _KEY_RE.fullmatch(str(key or "")):
            raise AIDirectorValidationError(f"Érvénytelen grounding fact key: {key!r}")
        if len(str(value)) > 240:
            raise AIDirectorValidationError(f"Túl hosszú grounding fact: {key}")
    return packet


def validate_provider_surface(packet: AIDirectorPacket, raw: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(raw, Mapping):
        raise AIDirectorValidationError("Az AI surface nem objektum.")
    keys = {str(key) for key in raw.keys()}
    if keys & cfg.AI_DIRECTOR_FORBIDDEN_FIELDS:
        raise AIDirectorValidationError("Az AI tiltott mechanikai mezőt adott vissza.")
    if keys != {"title", "description"}:
        raise AIDirectorValidationError("Az AI surface csak title + description mezőt tartalmazhat.")
    title = str(raw.get("title") or "").strip()
    description = str(raw.get("description") or "").strip()
    if not title or len(title) > cfg.AI_DIRECTOR_TITLE_MAX:
        raise AIDirectorValidationError("Hibás AI title.")
    if not description or len(description) > cfg.AI_DIRECTOR_DESCRIPTION_MAX:
        raise AIDirectorValidationError("Hibás AI description.")

    # Required anchors are host-owned semantic facts.  This is intentionally a
    # conservative first production gate: losing an anchor is a validation
    # failure and returns the deterministic fallback instead of guessing.
    def _anchor_fold(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", str(value).casefold())
        return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    merged = _anchor_fold(f"{title}\n{description}")
    for term in packet.required_terms:
        normalized = _anchor_fold(str(term).strip())
        if normalized and normalized not in merged:
            raise AIDirectorValidationError(f"Hiányzó grounding anchor: {term}")
    return title, description


def fallback_surface(packet: AIDirectorPacket) -> AIDirectorSurface:
    validate_packet(packet)
    return AIDirectorSurface(
        content_key=packet.content_key,
        family=packet.family,
        title=packet.fallback_title.strip(),
        description=packet.fallback_description.strip(),
        source="deterministic_fallback",
        packet_digest=packet.digest(),
        contract_version=packet.contract_version,
    )
