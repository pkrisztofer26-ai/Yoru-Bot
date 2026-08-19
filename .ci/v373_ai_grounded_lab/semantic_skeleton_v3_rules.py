from __future__ import annotations

"""W12.3 semantic skeleton v6 human-canary hardening.

v6 consumes the completed 35-scenario v5 canary as a human-QA regression.
The provider remains a seed-guided surface paraphraser, but subtle meaning
inversions and unsupplied scope broadening found by humans now trigger the
existing atomic curated-golden packet fallback.
"""

import copy as _copy
import re as _re

import semantic_skeleton_v3_rules_v5 as _v5
from semantic_skeleton_v3_rules_v5 import *

CONTRACT_VERSION = "w12.3-semantic-skeleton-v6"
CONFIG = _copy.deepcopy(_v5.CONFIG)
CONFIG["version"] = CONTRACT_VERSION

# Human mini-QA host-owned agency/copy fixes live in the current overlay so
# the historical v1 packet config remains immutable evidence.
CONFIG["packets"]["npc_lilla_dispatcher"]["choices"] = [
    {"label": "Vállalod a későbbi egyeztetést", "consequence": "Lillának jelzed, hogy ráérsz majd beszélni."},
    {"label": "Nem vállalod az egyeztetést", "consequence": "Lillának egyértelműen jelzed, hogy ezt az egyeztetést nem vállalod."},
]
CONFIG["packets"]["memory_nora_wallet"]["choices"] = [
    {"label": "Köszönsz Nórának", "consequence": "Röviden reagálsz arra, hogy felismer."},
    {"label": "Felidézed a pénztárcás találkozást", "consequence": "A beszélgetés a már megtörtént eseménynél marad."},
]


def _append_forbidden(packet_key: str, name: str, pattern: str) -> None:
    rows = CONFIG["packets"][packet_key].setdefault("forbidden", [])
    if not any(existing == name for existing, _ in rows):
        rows.append([name, pattern])


# Human mini-QA: the packet says the measurement SHOWS a deviation on the part.
# It does not say the measurement itself is inaccurate or defective.
_append_forbidden(
    "career_cnc_quality",
    "cnc_measurement_accuracy_inversion",
    r"(?i)(?:\bmérés\w*.{0,28}\b(?:pontatlan|hibás)\w*|\b(?:pontatlan|hibás)\w*.{0,28}\bmérés\w*)",
)
_append_forbidden(
    "career_cnc_quality",
    "cnc_unnatural_artifact_wording",
    r"(?i)\bCNC[-\s]?alkotás\w*\b",
)

# Human mini-QA: a growing queue does not establish a peak-hour fact.
_append_forbidden(
    "work_miskolc_canteen",
    "canteen_unsupplied_peak_period",
    r"(?i)\bcsúcsidő\w*\b",
)

# Human mini-QA: "munkaügyi" narrows the supplied generic work-related meeting
# into a different domain meaning.
_append_forbidden(
    "npc_lilla_dispatcher",
    "lilla_munkaugyi_scope_drift",
    r"(?i)\bmunkaügyi\b",
)

# Human mini-QA: recognition does not establish that Nóra greeted first, and
# ambiguous "ő" phrasing may flip who returned the wallet.
_append_forbidden(
    "memory_nora_wallet",
    "nora_ambiguous_actor_pronoun",
    r"(?i)(?:korábban\s+ő\s+találta|segítség\s+miatt\s*:\s*ő\s+találta)",
)

# Human mini-QA: fewer people staying outside is not an imposed restriction.
_append_forbidden(
    "world_eger_heat",
    "world_heat_imposed_restriction_drift",
    r"(?i)\b(?:korlátoz|tilt)\w*\b",
)

# Polish the two old curated panic phrasings through atomic fallback.
_append_forbidden(
    "store_heist_teammate_panic",
    "panic_awkward_communication_wording",
    r"(?i)(?:röviden\s+a\s+bizonytalan\s+kommunikáció\s+rendezésére\s+figyel|megtöri\s+a\s+csapat\s+addigi\s+kommunikációját)",
)

# Align imported layers with the merged current config/version.
_v5.CONFIG = CONFIG
_v5.CONTRACT_VERSION = CONTRACT_VERSION
try:
    _v5._v4.CONFIG = CONFIG
    _v5._v4.CONTRACT_VERSION = CONTRACT_VERSION
    _v5._v4._v3.CONFIG = CONFIG
    _v5._v4._v3.CONTRACT_VERSION = CONTRACT_VERSION
    _v5._v4._v3._v2.CONFIG = CONFIG
    _v5._v4._v3._v2.CONTRACT_VERSION = CONTRACT_VERSION
    _v5._v4._v3._v2._v1.CONFIG = CONFIG
    _v5._v4._v3._v2._v1.CONTRACT_VERSION = CONTRACT_VERSION
except Exception:
    pass



def semantic_errors(lab, packet, payload: dict) -> list[str]:
    return list(_v5.semantic_errors(lab, packet, payload))
