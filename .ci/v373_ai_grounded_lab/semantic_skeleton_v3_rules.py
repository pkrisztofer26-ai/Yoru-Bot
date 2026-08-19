from __future__ import annotations

"""W12.3 semantic skeleton v4 canary-efficiency hardening.

v4 keeps all v3 semantic/language regressions but relaxes only the per-item
anchor threshold that caused the first v3 canary false reject. Packet-level
anchor coverage remains mandatory, so canonical facts cannot disappear across
the five-variant packet.
"""

import copy as _copy
import semantic_skeleton_v3_rules_v3 as _v3
from semantic_skeleton_v3_rules_v3 import *

CONTRACT_VERSION = "w12.3-semantic-skeleton-v4"
CONFIG = _copy.deepcopy(_v3.CONFIG)
CONFIG["version"] = CONTRACT_VERSION

# Align the imported rule layers with the merged current config/version.
_v3.CONFIG = CONFIG
_v3.CONTRACT_VERSION = CONTRACT_VERSION
try:
    _v3._v2.CONFIG = CONFIG
    _v3._v2.CONTRACT_VERSION = CONTRACT_VERSION
    _v3._v2._v1.CONFIG = CONFIG
    _v3._v2._v1.CONTRACT_VERSION = CONTRACT_VERSION
except Exception:
    pass


def user_prompt_v3(packet, prior_keys: list[str]) -> str:
    text = _v3.user_prompt_v3(packet, prior_keys)
    old = (
        "Minden slot title + description felületi megfogalmazás legyen. "
        "Egy leírásnak nem kell az összes anchor csoportot szó szerint ismételnie: "
        "legalább a csoportok többségét tartsa meg, az öt slot együtt pedig fedje le mindet. "
    )
    new = (
        "Minden slot title + description felületi megfogalmazás legyen. "
        "Egy leírásnak nem kell az összes anchor csoportot szó szerint ismételnie: "
        "három vagy négy anchor esetén legalább kettőt, öt anchor esetén legalább hármat tartson meg. "
        "Az öt slot együtt minden anchor csoportot legalább három külön variánsban fedjen le. "
    )
    return text.replace(old, new)


def semantic_errors(lab, packet, payload: dict) -> list[str]:
    # Keep every v3 structural/language/semantic rule and the packet-level
    # 3/5 anchor requirement. Replace only v2's overly strict per-item rule.
    errors = [
        e for e in _v3.semantic_errors(lab, packet, payload)
        if not (e.startswith("items[") and "semantic anchor coverage too weak" in e)
    ]
    cfg = packet_cfg(packet)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    anchors = list(cfg.get("anchors", []))
    minimum = max(2, (len(anchors) + 1) // 2) if anchors else 0

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        desc = _v3._v2._v1._clean_text(item.get("description"))
        matched = [
            gi for gi, group in enumerate(anchors, 1)
            if _v3._v2._v1._matches_group(desc, group)
        ]
        if len(matched) < minimum:
            missing = [
                f"{gi}:{'/'.join(group)}"
                for gi, group in enumerate(anchors, 1)
                if gi not in matched
            ]
            errors.append(
                f"items[{i}]: semantic anchor coverage too weak "
                f"matched={len(matched)}/{len(anchors)} minimum={minimum} "
                f"missing={';'.join(missing)}"
            )
    return errors
