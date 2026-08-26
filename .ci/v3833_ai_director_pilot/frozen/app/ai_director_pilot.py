from __future__ import annotations

"""W22.3 opt-in/test-guild Tier 1 player-facing pilot.

The pilot serves ONLY the human-reviewed W22.2.1 static bundle.  It never calls
an external provider, never reads the generic AI cache and never receives or
returns gameplay authority.  Selection is deterministic presentation logic
performed after authoritative gameplay has already settled.
"""

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.ai_director import AIDirectorSurface, validate_provider_surface
from app.ai_director_review import review_surface_quality_errors
from app.ai_director_tier1 import TIER1_REVIEW_PACKETS


W22_2_1_REVIEW_RUN_ID = 32969015798
W22_2_1_REVIEW_ARTIFACT_ID = 9606860343
W22_2_1_REVIEW_ARTIFACT_SHA256 = "fe40bcb859652367dd4d8f8468fbbda0320f8eed12ec78a4b6e0e1b2b3b3fc37"
W22_2_1_HUMAN_QA = "15/15 GO"
PILOT_FIELD_NAME = "🌙 Yoru Director • teszt"


_REVIEWED_TEXT: Mapping[str, tuple[str, str]] = MappingProxyType({
    "work_shift_opening_warehouse": (
        "Indul a műszak",
        "A raktárban lassan felpörög a műszak, mindenki elfoglalja a helyét.",
    ),
    "work_shift_routine_cnc": (
        "Megváltozott a ritmus",
        "A CNC környékén átrendeződik a napi munkaritmus, de a feladat menete változatlan marad.",
    ),
    "work_break_room_note": (
        "Szünet előtti moraj",
        "A pihenő közelében mindenki a következő munkaszakaszra készül.",
    ),
    "crime_street_rumor": (
        "Furcsa szóbeszéd járja az utcát",
        "Az utcán egy bizonytalan pletyka terjed, de semmi sem utal biztos lehetőségre.",
    ),
    "crime_quiet_corner": (
        "Túl nagy a csend",
        "A környék szokatlanul csendes, ezért minden mozdulat feltűnőbbnek tűnik.",
    ),
    "crime_contact_delay": (
        "Késik a jelzés",
        "A kapcsolat felől egyelőre nem érkezik új jelzés, a helyzet nyitott marad.",
    ),
    "search_bus_stop": (
        "Valami feltűnik a megállónál",
        "A buszmegálló környékén akad egy apró részlet, ami egy pillanatra magára vonja a figyelmet.",
    ),
    "search_market_edge": (
        "A piac szélén",
        "A piac szélén a megszokottnál több apró részlet kerül szem elé.",
    ),
    "search_station_walk": (
        "Kör az állomásnál",
        "Az állomás környékén sétálva néhány szokatlan részlet kerül előtérbe.",
    ),
    "beg_square_crowd": (
        "Mozgalmasabb lett a tér",
        "A téren változik a járókelők ritmusa, de senki reakciója nincs előre eldöntve.",
    ),
    "beg_station_flow": (
        "Hullámokban érkeznek az emberek",
        "Az állomás előtt hol sűrűbb, hol ritkább a gyalogosforgalom.",
    ),
    "beg_market_exit": (
        "Záráshoz közeledik a piac",
        "A piac kijáratánál lassan átrendeződik a tömeg, ahogy közeleg a nap vége.",
    ),
    "career_generic_team_handoff": (
        "Műszakváltás",
        "A csapat átadja a következő feladatokhoz szükséges információkat.",
    ),
    "career_generic_busy_period": (
        "Sűrűbb lett a nap",
        "A munkahelyen több feladat kerül egyszerre előtérbe, ezért fontosabbá válik a sorrend.",
    ),
    "career_generic_end_of_shift": (
        "Közeledik a műszak vége",
        "A csapat a műszak utolsó feladatait rendezi és készül az átadásra.",
    ),
})


_PACKETS_BY_KEY = {packet.content_key: packet for packet in TIER1_REVIEW_PACKETS}
if set(_REVIEWED_TEXT) != set(_PACKETS_BY_KEY):
    raise RuntimeError("A W22.3 reviewed bundle nem egyezik a lezárt Tier 1 packet-katalógussal.")


def _build_reviewed_surfaces() -> Mapping[str, AIDirectorSurface]:
    rows: dict[str, AIDirectorSurface] = {}
    for content_key, (candidate_title, candidate_description) in _REVIEWED_TEXT.items():
        packet = _PACKETS_BY_KEY[content_key]
        title, description = validate_provider_surface(
            packet,
            {"title": candidate_title, "description": candidate_description},
        )
        quality_errors = review_surface_quality_errors(packet, title, description)
        if quality_errors:
            raise RuntimeError(
                f"A human-reviewed W22.3 bundle surface guardot sért: {content_key}: {quality_errors}"
            )
        rows[content_key] = AIDirectorSurface(
            content_key=content_key,
            family=packet.family,
            title=title,
            description=description,
            source="human_reviewed_cache",
            packet_digest=packet.digest(),
            contract_version=packet.contract_version,
        )
    return MappingProxyType(rows)


REVIEWED_TIER1_SURFACES = _build_reviewed_surfaces()
_SURFACES_BY_FAMILY: Mapping[str, tuple[AIDirectorSurface, ...]] = MappingProxyType({
    family: tuple(
        REVIEWED_TIER1_SURFACES[packet.content_key]
        for packet in TIER1_REVIEW_PACKETS
        if packet.family == family
    )
    for family in sorted({packet.family for packet in TIER1_REVIEW_PACKETS})
})


@dataclass(frozen=True, slots=True)
class AIDirectorPilotPolicy:
    enabled: bool = False
    test_guild_id: int | None = None

    def active_for_guild(self, guild_id: int | None) -> bool:
        return bool(
            self.enabled
            and self.test_guild_id is not None
            and guild_id is not None
            and int(guild_id) == int(self.test_guild_id)
        )


class AIDirectorPilot:
    """Read-only, test-guild-only presentation selector over reviewed content."""

    def __init__(self, *, enabled: bool = False, test_guild_id: int | None = None) -> None:
        self.policy = AIDirectorPilotPolicy(bool(enabled), test_guild_id)

    @property
    def enabled(self) -> bool:
        return self.policy.enabled

    def active_for_guild(self, guild_id: int | None) -> bool:
        return self.policy.active_for_guild(guild_id)

    def surface(
        self,
        guild_id: int | None,
        user_id: int | None,
        family: str,
        *,
        variant_token: str = "",
    ) -> AIDirectorSurface | None:
        if not self.active_for_guild(guild_id):
            return None
        candidates = _SURFACES_BY_FAMILY.get(str(family))
        if not candidates:
            return None
        # This hash only chooses among already human-reviewed presentation
        # variants.  It is never fed back into gameplay and cannot affect RNG,
        # rewards, cooldowns, inventory or state mutation.
        seed = (
            f"w22.3:{int(guild_id or 0)}:{int(user_id or 0)}:{family}:"
            f"{str(variant_token)}:{candidates[0].contract_version}"
        ).encode("utf-8")
        index = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big") % len(candidates)
        return candidates[index]

    def field_value(
        self,
        guild_id: int | None,
        user_id: int | None,
        family: str,
        *,
        variant_token: str = "",
    ) -> str | None:
        surface = self.surface(guild_id, user_id, family, variant_token=variant_token)
        if surface is None:
            return None
        return f"**{surface.title}**\n{surface.description}"[:1024]
