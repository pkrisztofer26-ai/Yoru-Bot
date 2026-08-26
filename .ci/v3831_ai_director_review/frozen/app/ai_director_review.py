from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable

from app.ai_director import AIDirectorPacket, AIDirectorSurface, fallback_surface


_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", str(text).casefold()).strip()


# Human QA-derived, non-authoritative surface-language guards.  These do not
# infer gameplay facts; they only prevent a reviewed Hungarian wording
# regression from being accepted again by the automated review gate.
_HUMAN_DERIVED_SURFACE_REJECTIONS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "beg_square_crowd": (
        (re.compile(r"\ba\s+térben\b", re.IGNORECASE), "unnatural_square_locative"),
    ),
}


def review_surface_quality_errors(packet: AIDirectorPacket, title: str, description: str) -> tuple[str, ...]:
    text = f"{title}\n{description}"
    errors: list[str] = []
    for pattern, label in _HUMAN_DERIVED_SURFACE_REJECTIONS.get(packet.content_key, ()):
        if pattern.search(text):
            errors.append(label)
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class AIDirectorReviewRow:
    content_key: str
    family: str
    packet_digest: str
    fallback_title: str
    fallback_description: str
    candidate_title: str
    candidate_description: str
    candidate_source: str
    automated_status: str
    cache_seed_eligible: bool
    human_groundedness: str = ""
    human_hungarian: str = ""
    human_yoru_tone: str = ""
    human_new_fact: str = ""
    human_decision: str = ""
    human_notes: str = ""


@dataclass(frozen=True, slots=True)
class AIDirectorReviewArtifact:
    contract_version: str
    status: str
    total: int
    ai_validated: int
    deterministic_fallbacks: int
    exact_duplicate_groups: int
    player_facing_ai: bool
    production_runtime_enabled: bool
    human_review_required: bool
    rows: tuple[AIDirectorReviewRow, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_csv(self) -> str:
        buffer = io.StringIO()
        if not self.rows:
            return ""
        fieldnames = list(asdict(self.rows[0]).keys())
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in self.rows:
            writer.writerow(asdict(row))
        return buffer.getvalue()


def build_review_artifact(
    packets: Iterable[AIDirectorPacket],
    surfaces: Iterable[AIDirectorSurface],
) -> AIDirectorReviewArtifact:
    packet_items = tuple(packets)
    surface_items = tuple(surfaces)
    if len(packet_items) != len(surface_items):
        raise ValueError("A review packet/surface elemszám eltér.")
    if not packet_items:
        raise ValueError("Üres AI Director review batch.")

    seen_surface: dict[tuple[str, str], list[str]] = {}
    rows: list[AIDirectorReviewRow] = []
    ai_validated = fallbacks = 0
    for packet, surface in zip(packet_items, surface_items, strict=True):
        if packet.content_key != surface.content_key or packet.digest() != surface.packet_digest:
            raise ValueError(f"Review identity mismatch: {packet.content_key}")
        fallback = fallback_surface(packet)
        is_ai = surface.source == "ai_cached"
        ai_validated += int(is_ai)
        fallbacks += int(not is_ai)
        if is_ai:
            seen_surface.setdefault((_norm(surface.title), _norm(surface.description)), []).append(packet.content_key)
        rows.append(AIDirectorReviewRow(
            content_key=packet.content_key,
            family=packet.family,
            packet_digest=packet.digest(),
            fallback_title=fallback.title,
            fallback_description=fallback.description,
            candidate_title=surface.title,
            candidate_description=surface.description,
            candidate_source=surface.source,
            automated_status="PASS" if is_ai else "FALLBACK",
            cache_seed_eligible=is_ai,
        ))

    duplicate_groups = sum(1 for keys in seen_surface.values() if len(keys) > 1)
    status = "PENDING_HUMAN" if ai_validated == len(rows) and duplicate_groups == 0 else "AUTOMATED_HOLD"
    if duplicate_groups:
        rows = [
            AIDirectorReviewRow(**{
                **asdict(row),
                "automated_status": (
                    "DUPLICATE_HOLD" if any(
                        row.content_key in keys for keys in seen_surface.values() if len(keys) > 1
                    ) else row.automated_status
                ),
                "cache_seed_eligible": (
                    False if any(row.content_key in keys for keys in seen_surface.values() if len(keys) > 1)
                    else row.cache_seed_eligible
                ),
            }) for row in rows
        ]

    return AIDirectorReviewArtifact(
        contract_version=packet_items[0].contract_version,
        status=status,
        total=len(rows),
        ai_validated=ai_validated,
        deterministic_fallbacks=fallbacks,
        exact_duplicate_groups=duplicate_groups,
        player_facing_ai=False,
        production_runtime_enabled=False,
        human_review_required=True,
        rows=tuple(rows),
    )
