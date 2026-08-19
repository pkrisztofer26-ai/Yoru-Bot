from __future__ import annotations

"""W12.3 semantic skeleton v3 shadow-lab hardening.

v3 preserves the first-live v2 rules and adds semantic regressions discovered
by the zero-token Shadow Lab. The provider remains a surface renderer only.
"""

import copy as _copy
import semantic_skeleton_v3_rules_v2 as _v2
from semantic_skeleton_v3_rules_v2 import *

CONTRACT_VERSION = "w12.3-semantic-skeleton-v3"
CONFIG = _copy.deepcopy(_v2.CONFIG)
CONFIG["version"] = CONTRACT_VERSION


def _add_forbidden(packet_key: str, name: str, pattern: str) -> None:
    rows = CONFIG["packets"][packet_key].setdefault("forbidden", [])
    if not any(existing == name for existing, _ in rows):
        rows.append([name, pattern])


# Shadow Lab gap 1: archive labels are known to be inconsistent, so sorting by
# the bad label itself contradicts the canonical constraint.
_add_forbidden(
    "work_mezokovesd_archive",
    "archive_wrong_label_sort",
    r"(?i)(?:hibás|rossz)\s+címk\w*.{0,28}(?:alapján|szerint).{0,28}(?:rendez|tesz|helyez|pakol)",
)

# Shadow Lab gap 2: the retail situation is explicitly professional/human, not
# a disciplinary case.
_add_forbidden(
    "career_retail_training",
    "retail_disciplinary_invention",
    r"(?i)\b(?:fegyelmi(?:\s+(?:ügy|eljárás))?|büntet\w*|megrov\w*)\b",
)

# Shadow Lab gap 3: suffixes/compounds bypassed the original supplier/ETA regex.
_add_forbidden(
    "career_mechanic_part_delay",
    "supplier_eta_suffix_invention",
    r"(?i)(?:szállító\w*|pontos\s+érkezési\s+idő\w*)",
)

# Shadow Lab gap 4: Lilla only asks whether a later work-related coordination is
# acceptable; no concrete job or exact appointment exists.
_add_forbidden(
    "npc_lilla_dispatcher",
    "lilla_concrete_job_time_invention",
    r"(?i)(?:konkrét\s+(?:fuvar|munka|műszak)\w*|pontos\s+időpont\w*|munkakezd\w*)",
)

# Shado Lab gap 5: Misi asks only whether the player is generally looking for a
# car; a specific vehicle or price is new deal truth.
_add_forbidden(
    "npc_misi_car_dealer",
    "misi_concrete_deal_suffix",
    r"(?i)(?:konkrét\s+autó\w*|\b(?:ár|alku|kedvezmény)\w*)",
)

# Shado Lab gap 6: the memory contains exactly one help event. Compounded car # repair / debt / invented joint-event wording is not a valid recall.
_add_forbidden(
    "memory_jani_tools",
    "jani_memory_joint_event_invention",
    r"(?i)(?:közös\s+(?:munka|esenény|javítás)\w*|autó\w*javít\w*|tartoz\w*|fizets\w*)",
)

# Imported v2 functions resolve CONFIG/CONTRACT_VERSION in the v2 module.
_v2.CONFIG = CONFIG
_v2.CONTRACT_VERSION = CONTRACT_VERSION

# Re-exported functions call into v2 -> v1. Keep every layer aligned with the
# current merged configuration/version.
try:
    _v2._v1.CONFIG = CONFIG
    _v2._v1.CONTRACT_VERSION = CONTRACT_VERSION
except Exception:
    pass
