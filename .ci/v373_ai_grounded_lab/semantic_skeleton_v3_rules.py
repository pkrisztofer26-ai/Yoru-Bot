from __future__ import annotations

"""W12.3 semantic skeleton v5 seed-guided surface hardening.

v5 keeps every v4 semantic/authority regression, but stops treating raw
Hungarian wording as a tiny exact-token language. The model is now a
seed-guided surface paraphraser. Host validation remains authoritative.
"""

from pathlib import Path
from difflib import SequenceMatcher
import base64 as _base64
import copy as _copy
import gzip as _gzip
import json as _json
import re as _re

import semantic_skeleton_v3_rules_v4 as _v4
from semantic_skeleton_v3_rules_v4 import *

CONTRACT_VERSION = "w12.3-semantic-skeleton-v5"
CONFIG = _copy.deepcopy(_v4.CONFIG)
CONFIG["version"] = CONTRACT_VERSION

# Human-equivalent surface forms observed in the real v4 120B canary.
# These are phrasing aliases only; they do not add facts or authority.
ANCHOR_ALIASES = {
    "work_miskolc_canteen": {
        2: ["késő szállít", "szállítási kés", "késve érkez"],
        4: ["összehangol", "koordinál"],
    },
}

# v4 raw-surface QA exposed fluent-looking additions / Hungarian failures that
# were not supplied by the packet. These remain deterministic hard rejects;
# v5 can replace a failed surface slot with its curated seed without a provider retry.
_canteen = CONFIG["packets"]["work_miskolc_canteen"]
for _name, _pattern in [
    ("canteen_unsupplied_queue_actor", r"(?i)\bvendég\w*\b"),
    ("canteen_invented_urgency", r"(?i)\b(?:sürgős|rohanó)\w*\b"),
    ("canteen_bad_article_elokeszites", r"(?i)\b(?:csak\s+)?a\s+előkészít\w*\b"),
    ("canteen_bad_compound", r"(?i)\balapanyag\s+szállítás\b"),
]:
    if not any(existing == _name for existing, _ in _canteen.get("forbidden", [])):
        _canteen.setdefault("forbidden", []).append([_name, _pattern])

# Align every imported layer with the merged current config/version.
_v4.CONFIG = CONFIG
_v4.CONTRACT_VERSION = CONTRACT_VERSION
try:
    _v4._v3.CONFIG = CONFIG
    _v4._v3.CONTRACT_VERSION = CONTRACT_VERSION
    _v4._v3._v2.CONFIG = CONFIG
    _v4._v3._v2.CONTRACT_VERSION = CONTRACT_VERSION
    _v4._v3._v2._v1.CONFIG = CONFIG
    _v4._v3._v2._v1.CONTRACT_VERSION = CONTRACT_VERSION
except Exception:
    pass


def _norm_surface_text(value: str) -> str:
    text = str(value or "").casefold().replace("-", " ")
    text = _re.sub(r"[^\wáéíóöőúüű]+", " ", text, flags=_re.UNICODE)
    return _re.sub(r"\s+", " ", text).strip()


def _anchor_match(packet, text: str, group_index: int, group: list[str]) -> bool:
    low = _norm_surface_text(text)
    tokens = list(group)
    tokens.extend(ANCHOR_ALIASES.get(packet.key, {}).get(group_index, []))
    return any(_norm_surface_text(token) in low for token in tokens if str(token).strip())


# Golden corpus is the positive quality oracle and also the host fallback source.
_GOLDEN_CACHE = None


def golden_rows() -> list[dict]:
    global _GOLDEN_CACHE
    if _GOLDEN_CACHE is None:
        path = Path(__file__).resolve().parent / "w123_shadow_golden.b64"
        packed = _base64.b64decode(path.read_text(encoding="ascii"))
        doc = _json.loads(_gzip.decompress(packed).decode("utf-8"))
        _GOLDEN_CACHE = list(doc["items"])
    return _GOLDEN_CACHE


def golden_surface(packet) -> dict:
    rows = [r for r in golden_rows() if r.get("packet") == packet.key]
    by_slot = {str(r["slot"]): r for r in rows}
    if set(by_slot) != set(SLOT_IDS):
        raise RuntimeError(f"golden coverage mismatch for {packet.key}")
    return {
        "items": [
            {
                "slot": slot,
                "title": str(by_slot[slot]["title"]).strip(),
                "description": str(by_slot[slot]["description"]).strip(),
            }
            for slot in SLOT_IDS
        ]
    }


def system_prompt_v3(packet) -> str:
    extra = {
        "heist": " Heistnél maradj filmszerű és magas szintű; valós végrehajtási módszer tilos.",
        "crime": " Bűnügyi helyzetben végrehajtási, elrejtési vagy elkerülési módszer tilos.",
        "npc": " Az NPC-ről csak a megadott jelenlegi kapcsolat/kérdés használható.",
        "memory": " Csak a megadott múltbeli eseményt idézd fel; új kapcsolat vagy közös múlt tilos.",
        "world": " Ez hírszerű world-context; új ok, hely, közlekedési mód vagy player action tilos.",
    }.get(packet.profile, "")
    return (
        "Te a Yoru magyar surface renderere vagy. A host kész, ellenőrzött SEED mondatokat ad. "
        "Feladatod csak könnyű, természetes magyar átfogalmazás ugyanazzal a jelentéssel. "
        "Ne találj ki új konkrét főnevet, szereplőt, tárgyat, okot, reakciót, időpontot, helyet, "
        "kapcsolatot, mechanikát vagy következményt. Pontosan öt JSON itemet adj a schema szerint. "
        "A slot értékét tartsd meg. Ne írj choice-ot, ID-t vagy technikai mezőt." + extra
    )


def user_prompt_v3(packet, prior_keys: list[str]) -> str:
    facts = [{"id": f.fact_id, "text": f.text} for f in packet.facts]
    seeds = golden_surface(packet)["items"]
    doc = {
        "packet": packet.key,
        "hard_facts": facts,
        "allowed_entities": list(packet.entities),
        "surface_seeds": seeds,
    }
    return (
        "Írd át enyhén az öt surface seedet. A seed jelentését ne bővítsd és ne fordítsd meg. "
        "Pontosan ugyanaz az öt slot kell, mindegyikhez rövid természetes cím és egy rövid mondat. "
        "Ha bizonytalan vagy, maradj nagyon közel a seedhez.\n"
        + _json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    )


def semantic_errors(lab, packet, payload: dict) -> list[str]:
    # Keep all v4 structural/language/semantic rules, but recalculate anchor
    # coverage with the v5 phrase-aware matcher.
    errors = [
        e for e in _v4.semantic_errors(lab, packet, payload)
        if "semantic anchor coverage too weak" not in e
        and "packet anchor coverage too weak" not in e
    ]
    cfg = packet_cfg(packet)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    anchors = list(cfg.get("anchors", []))
    minimum = 3 if len(anchors) >= 5 else (2 if anchors else 0)

    seeds = {row["slot"]: row for row in golden_surface(packet)["items"]}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        desc = _v4._v3._v2._v1._clean_text(item.get("description"))
        matched = [
            gi for gi, group in enumerate(anchors, 1)
            if _anchor_match(packet, desc, gi, group)
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


    for gi, group in enumerate(anchors, 1):
        coverage = sum(
            1 for item in items
            if isinstance(item, dict)
            and _anchor_match(
                packet,
                _v4._v3._v2._v1._clean_text(item.get("description")),
                gi,
                group,
            )
        )
        if coverage < 3:
            errors.append(
                f"packet anchor coverage too weak group={gi}:{'/'.join(group)} "
                f"coverage={coverage}/5"
            )
    return errors
