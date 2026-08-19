from __future__ import annotations

"""Final FULL Human-QA overlay for W12.3 v8."""

import copy as _copy
import re as _re
import semantic_skeleton_v3_rules as _v7
from semantic_skeleton_v3_rules import *
from semantic_skeleton_v3_rules_v8_config import VERSION as CONTRACT_VERSION, build_config
from semantic_skeleton_v3_rules_v8_golden1 import OVERRIDES as _GOLDEN_1
from semantic_skeleton_v3_rules_v8_golden2 import OVERRIDES as _GOLDEN_2
from semantic_skeleton_v3_rules_v8_golden3 import OVERRIDES as _GOLDEN_3
from semantic_skeleton_v3_rules_v8_golden4 import OVERRIDES as _GOLDEN_4

CONFIG = build_config(_v7.CONFIG)
_FINAL_GOLDEN_OVERRIDES = {**_GOLDEN_1, **_GOLDEN_2, **_GOLDEN_3, **_GOLDEN_4}


def _v8_golden_rows():
    rows = _copy.deepcopy(_v7._v7_golden_rows())
    for row in rows:
        override = _FINAL_GOLDEN_OVERRIDES.get((str(row.get("packet") or ""), str(row.get("slot") or "")))
        if override:
            row.update(override)
    return rows


_v7._v5._GOLDEN_CACHE = _v8_golden_rows()
_v7.CONFIG = CONFIG
_v7.CONTRACT_VERSION = CONTRACT_VERSION
_v7._v5.CONFIG = CONFIG
_v7._v5.CONTRACT_VERSION = CONTRACT_VERSION
try:
    _v7._v5._v4.CONFIG = CONFIG
    _v7._v5._v4.CONTRACT_VERSION = CONTRACT_VERSION
    _v7._v5._v4._v3.CONFIG = CONFIG
    _v7._v5._v4._v3.CONTRACT_VERSION = CONTRACT_VERSION
    _v7._v5._v4._v3._v2.CONFIG = CONFIG
    _v7._v5._v4._v3._v2.CONTRACT_VERSION = CONTRACT_VERSION
    _v7._v5._v4._v3._v2._v1.CONFIG = CONFIG
    _v7._v5._v4._v3._v2._v1.CONTRACT_VERSION = CONTRACT_VERSION
except Exception:
    pass


def semantic_errors(lab, packet, payload: dict) -> list[str]:
    errors = list(_v7.semantic_errors(lab, packet, payload))
    items = payload.get("items") if isinstance(payload, dict) else []
    joined = " ".join(
        str(item.get("title") or "") + " " + str(item.get("description") or "")
        for item in (items or []) if isinstance(item, dict)
    )
    if packet.profile == "heist" and _re.search(r"(?i)\b(?:magas\s+szint(?:ű|en)?|fiktív)\b", joined):
        errors.append("packet: player-facing internal heist wording")
    return errors
