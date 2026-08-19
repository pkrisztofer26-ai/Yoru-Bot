from __future__ import annotations

"""W12.3 semantic skeleton v2 live-derived hardening.

This wrapper preserves the frozen v1 rules module and applies the first-live
regressions without mutating the W12.2/W12.3-v1 evidence source.
"""

import copy as _copy
import re as _re
import semantic_skeleton_v3_rules_v1 as _v1
from semantic_skeleton_v3_rules_v1 import *

CONTRACT_VERSION = "w12.3-semantic-skeleton-v2"
CONFIG = _copy.deepcopy(_v1.CONFIG)
CONFIG["version"] = CONTRACT_VERSION

# Live run 32255317034 exposed fluent-looking but invalid Hungarian / semantic drift.
_extra_broken = [
    ["live_heveredik", r"(?i)\bheveredik\w*\b"],
    ["live_keso_jovoben", r"(?i)késő\s+jövőben\s+érkező"],
    ["live_object_szaradjon", r"(?i)(?:maradékot|többit)\s+(?:pedig\s+)?száradjon"],
]
_seen = {name for name, _ in CONFIG["global"].get("broken_patterns", [])}
CONFIG["global"].setdefault("broken_patterns", []).extend(row for row in _extra_broken if row[0] not in _seen)
CONFIG["global"]["semantic_forbidden"] = [
    [
        "unsupported_player_team_leadership",
        r"(?i)(?:(?:játékos|kisegítő|munkás)\w*.{0,28}(?:irányít|vezet)\w*.{0,18}csapat|csapat\w*.{0,18}(?:irányít|vezet)\w*.{0,28}(?:játékos|kisegítő|munkás))",
    ]
]

_warehouse = CONFIG["packets"]["work_miskolc_warehouse"]
if not any(name == "warehouse_known_location_invention" for name, _ in _warehouse.get("forbidden", [])):
    _warehouse.setdefault("forbidden", []).append([
        "warehouse_known_location_invention",
        r"(?i)(?:megfelelő|helyes)\s+hely\w*",
    ])

# Functions imported from v1 retain v1's globals; point them at the merged config/version.
_v1.CONFIG = CONFIG
_v1.CONTRACT_VERSION = CONTRACT_VERSION


def user_prompt_v3(packet, prior_keys: list[str]) -> str:
    text = _v1.user_prompt_v3(packet, prior_keys)
    return text.replace(
        "Minden slot title + description felületi megfogalmazás legyen; a descriptionben minden required_anchor_groups csoportból legalább egy fogalom maradjon felismerhető. ",
        "Minden slot title + description felületi megfogalmazás legyen. Egy leírásnak nem kell az összes anchor csoportot szó szerint ismételnie: legalább a csoportok többségét tartsa meg, az öt slot együtt pedig fedje le mindet. ",
    )


def semantic_errors(lab, packet, payload: dict) -> list[str]:
    # Keep every v1 structural, semantic and diversity rule except the overly strict
    # per-item all-anchor requirement. That rule caused repetitive wording and one
    # false-negative live packet for a single omitted noun.
    errors = [
        e for e in _v1.semantic_errors(lab, packet, payload)
        if "missing semantic anchor group" not in e
    ]
    cfg = packet_cfg(packet)
    items = payload.get("items", []) if isinstance(payload, dict) else []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        here = f"items[{i}]"
        title = _v1._clean_text(item.get("title"))
        desc = _v1._clean_text(item.get("description"))
        text = title + " " + desc
        for name, pattern in CONFIG["global"].get("semantic_forbidden", []):
            if _re.search(pattern, text):
                errors.append(f"{here}: W12.3 global semantic regression: {name}")

        anchors = list(cfg.get("anchors", []))
        matched = [gi for gi, group in enumerate(anchors, 1) if _v1._matches_group(desc, group)]
        minimum = max(2, len(anchors) - 1) if anchors else 0
        if len(matched) < minimum:
            missing = [
                f"{gi}:{'/'.join(group)}"
                for gi, group in enumerate(anchors, 1)
                if gi not in matched
            ]
            errors.append(
                f"{here}: semantic anchor coverage too weak "
                f"matched={len(matched)}/{len(anchors)} missing={';'.join(missing)}"
            )

    # Packet-level coverage: every anchor must still be explicit in a majority of
    # the five variants, so relaxing one variant cannot erase a canonical fact.
    anchors = list(cfg.get("anchors", []))
    for gi, group in enumerate(anchors, 1):
        coverage = sum(
            1 for item in items
            if isinstance(item, dict)
            and _v1._matches_group(_v1._clean_text(item.get("description")), group)
        )
        if coverage < 3:
            errors.append(
                f"packet anchor coverage too weak group={gi}:{'/'.join(group)} "
                f"coverage={coverage}/5"
            )
    return errors
