from __future__ import annotations

"""Yoru v3.73 W12.3 Content Quality / Semantic Skeleton lab (DEV-only).

W12.2 proved schema/provider/authority boundaries but failed human content QA.
W12.3 narrows the model to a surface renderer:
- provider owns only slot + title + one-sentence Hungarian description;
- host owns IDs, grounding, tags, choice agency, choice consequences and world no-choice behavior;
- regression validators are derived from the full 120-item W12.2 human review.
"""

from pathlib import Path
from typing import Any
from difflib import SequenceMatcher
import importlib.util
import json
import gzip
import base64
import os
import re
import sys

HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "fast_resume_v2.py"
CONFIG_PATH = HERE / "semantic_skeleton_v3.json"
REGRESSION_CHUNKS = tuple(sorted(HERE.glob("w123_regression_corpus.part*.b64")))
CONTRACT_VERSION = "w12.3-semantic-skeleton-v1"
GATE_NAME = "Yoru v3.73 W12.3 Content Quality / Semantic Skeleton"
SLOT_IDS = ("focus_a", "focus_b", "focus_c", "focus_d", "focus_e")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_module(V2_PATH, "yoru_w122_fast_resume_v2_for_w123")
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def packet_cfg(packet) -> dict[str, Any]:
    try:
        return CONFIG["packets"][packet.key]
    except KeyError as exc:
        raise KeyError(f"missing W12.3 semantic config for {packet.key}") from exc


def focus_fact_ids(packet, slot_index: int) -> list[str]:
    """Deterministic focus subsets; all packet facts remain hard boundaries."""
    ids = list(packet.fact_ids)
    n = len(ids)
    if n == 3:
        patterns = ((0, 1), (1, 2), (0, 2), (0, 1, 2), (1,))
    elif n == 4:
        patterns = ((2, 3), (0, 2), (1, 2), (0, 3), (1, 3))
    elif n >= 5:
        patterns = ((0, 2, n - 1), (1, 2, n - 1), (0, 1, 2), (2, 3, n - 1), tuple(range(n)))
    else:
        patterns = tuple(tuple(range(n)) for _ in SLOT_IDS)
    return [ids[i] for i in patterns[slot_index] if 0 <= i < n]


def surface_output_schema(packet) -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "slot": {"type": "string", "enum": list(SLOT_IDS)},
            "title": {"type": "string", "minLength": 2, "maxLength": 80},
            "description": {"type": "string", "minLength": 20, "maxLength": 320},
        },
        "required": ["slot", "title", "description"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": packet.count,
                "maxItems": packet.count,
                "items": item,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def system_prompt_v3(packet) -> str:
    profile_extra = {
        "heist": " A heist csak filmszerű, magas szintű helyzetleírás; valós végrehajtási módszert ne írj.",
        "crime": " Bűnügyi helyzetben ne adj végrehajtási, elrejtési, szállítási vagy elkerülési módszert.",
        "npc": " Az NPC mai magyar szereplő. Csak a supplied jelenlegi kérdést és supplied kapcsolatot használd.",
        "memory": " Csak a supplied múltbeli eseményt hívd vissza. Új kapcsolat, gesztus vagy közös múlt tilos.",
        "world": " Ez hírszerű world-context. Ne adj player actiont, új okot, új helyet, közlekedési módot vagy új world truth-ot.",
    }.get(packet.profile, "")
    return (
        "Yoru magyar life-RP surface renderer vagy, nem történetíró és nem játékszabály-motor. "
        "A host már rögzítette a jelenet szemantikai vázát. Neked kizárólag természetes magyar címet és egy rövid leíró mondatot kell megfogalmaznod minden slothoz. "
        "Tilos megváltoztatni, ki cselekszik, kinek szól a kérés, mi az objektum, merre irányul a kérés, mi az ok, milyen kapcsolat áll fenn vagy milyen folyamat történik. "
        "Ne találj ki új konkrét főnevet, szereplőt, eszközt, készletet, szervezeti rendszert, helyet, időpontot, reakciót, következményt vagy mechanikát. "
        "A required anchor fogalmaknak a descriptionben láthatóan meg kell maradniuk. "
        "A cím legyen természetes, rövid és tartalmi: ne legyen számozott, ne szerepeljen benne 'változat', 'döntés', 'helyzet' mint meta címke. "
        "Description: egy mondat, mai magyar, nincs AI-klisé, nincs fejlesztői/meta nyelv. "
        "Ne generálj choice-ot, consequence-et, ID-t, taget vagy grounding mezőt; ezeket a host adja hozzá." + profile_extra
    )


def user_prompt_v3(packet, prior_keys: list[str]) -> str:
    cfg = packet_cfg(packet)
    facts = {f.fact_id: f.text for f in packet.facts}
    slots = []
    for index, slot in enumerate(SLOT_IDS):
        focus = focus_fact_ids(packet, index)
        slots.append({
            "slot": slot,
            "focus_fact_ids": focus,
            "focus_facts": [facts[x] for x in focus],
        })
    grounding = {
        "packet_key": packet.key,
        "brief": packet.brief,
        "profile": packet.profile,
        "all_facts_are_hard_boundaries": [{"fact_id": f.fact_id, "text": f.text} for f in packet.facts],
        "allowed_entities": list(packet.entities),
        "required_anchor_groups": cfg["anchors"],
        "semantic_slots": slots,
        "already_used_keys": prior_keys[-20:],
    }
    return (
        "Adj vissza pontosan öt itemet, egyet-egyet a semantic_slots minden slotjára. "
        "Minden slot title + description felületi megfogalmazás legyen; a descriptionben minden required_anchor_groups csoportból legalább egy fogalom maradjon felismerhető. "
        "A focus_facts adja az adott variáns hangsúlyát, de nem írhat felül és nem bővíthet egyetlen all_facts_are_hard_boundaries tényt sem. "
        "Az öt leírás ne ugyanaz a mondat legyen minimális szócsere mellett. Új konkrét részletet inkább hagyj ki, mint hogy kitaláld.\n\n"
        "SEMANTIC_SKELETON:\n" + json.dumps(grounding, ensure_ascii=False, indent=2)
    )


def choice_rows(packet, slot_index: int) -> list[dict[str, str]]:
    choices = list(packet_cfg(packet).get("choices") or [])
    if not choices:
        return []
    if len(choices) == 1:
        picked = [choices[0]]
    elif len(choices) == 2:
        picked = choices
    elif len(choices) == 3:
        patterns = ((0, 1), (1, 2), (0, 2), (0, 1), (1, 2))
        picked = [choices[i] for i in patterns[slot_index]]
    else:
        patterns = ((0, 1), (1, 2), (2, 3), (0, 3), (1, 3))
        picked = [choices[i] for i in patterns[slot_index]]
    return [
        {"key": f"choice_{i:02d}", "label": str(c["label"]).strip(), "consequence_hint": str(c["consequence"]).strip()}
        for i, c in enumerate(picked, 1)
    ]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonicalize_surface_payload(lab, packet, payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) != packet.count:
        raise ValueError(f"semantic surface expected {packet.count} items")
    by_slot: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("semantic surface item is not an object")
        slot = str(raw.get("slot", ""))
        if slot not in SLOT_IDS:
            raise ValueError(f"unknown semantic slot: {slot!r}")
        if slot in by_slot:
            raise ValueError(f"duplicate semantic slot: {slot}")
        by_slot[slot] = raw
    if set(by_slot) != set(SLOT_IDS):
        raise ValueError(f"semantic slot coverage mismatch: {sorted(by_slot)}")

    final: list[dict[str, Any]] = []
    for index, slot in enumerate(SLOT_IDS):
        raw = by_slot[slot]
        title = _clean_text(raw.get("title"))
        description = _clean_text(raw.get("description"))
        item = {
            "key": f"{packet.key}_slot_{index + 1}",
            "packet_key": packet.key,
            "scene_type": packet.scene_type,
            "family": packet.family,
            "title": title,
            "description": description,
            "choices": choice_rows(packet, index),
            "tags": ["grounded", "semantic_skeleton", packet.profile][:4],
            "semantic_key": f"{packet.key}_focus_{index + 1}",
            "grounding_ids": list(packet.fact_ids),
            "entities_mentioned": [],
            "new_fact_claims": [],
        }
        full_text = lab._all_text(item)
        item["entities_mentioned"] = [e for e in packet.entities if lab._mentions_entity(full_text, e)]
        final.append(item)
    return {"items": final}


def _matches_group(text: str, group: list[str]) -> bool:
    low = text.casefold()
    return any(str(token).casefold() in low for token in group)


def semantic_errors(lab, packet, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cfg = packet_cfg(packet)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    expected_tags = ["grounded", "semantic_skeleton", packet.profile][:4]

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        here = f"items[{i}]"
        title = _clean_text(item.get("title"))
        desc = _clean_text(item.get("description"))
        text = title + " " + desc

        if item.get("key") != f"{packet.key}_slot_{i + 1}":
            errors.append(f"{here}: host semantic key mismatch")
        if item.get("semantic_key") != f"{packet.key}_focus_{i + 1}":
            errors.append(f"{here}: host semantic_key mismatch")
        if item.get("tags") != expected_tags:
            errors.append(f"{here}: host tags mismatch")
        expected_choices = choice_rows(packet, i)
        if item.get("choices") != expected_choices:
            errors.append(f"{here}: host-owned choice agency mismatch")
        if packet.profile == "world" and item.get("choices") != []:
            errors.append(f"{here}: world context must not synthesize player choices")
        if packet.profile != "world" and not expected_choices:
            errors.append(f"{here}: non-world packet has no host choices")

        expected_entities = [e for e in packet.entities if lab._mentions_entity(lab._all_text(item), e)]
        if item.get("entities_mentioned") != expected_entities:
            errors.append(f"{here}: host entity declaration mismatch")

        if not title or len(title) > 80 or len(title.split()) > 8:
            errors.append(f"{here}: title length/style invalid")
        if not desc or len(desc) < 24 or len(desc) > 300:
            errors.append(f"{here}: description length invalid")
        if len(re.findall(r"[.!?]", desc)) > 2:
            errors.append(f"{here}: description must stay one short sentence")

        for name, pattern in CONFIG["global"]["broken_patterns"]:
            if re.search(pattern, text):
                errors.append(f"{here}: W12.3 language regression: {name}")
        for name, pattern in cfg.get("forbidden", []):
            if re.search(pattern, text):
                errors.append(f"{here}: W12.3 semantic regression: {name}")
        for gi, group in enumerate(cfg.get("anchors", []), 1):
            if not _matches_group(desc, group):
                errors.append(f"{here}: missing semantic anchor group {gi}: {'/'.join(group)}")

    # Stronger variation check than W12.2: surface wording must actually differ.
    descs = [(str(x.get("key", "")), _clean_text(x.get("description"))) for x in items if isinstance(x, dict)]
    titles = [_clean_text(x.get("title")) for x in items if isinstance(x, dict)]
    if len(set(t.casefold() for t in titles)) != len(titles):
        errors.append("duplicate W12.3 titles inside packet")
    for a in range(len(descs)):
        for b in range(a + 1, len(descs)):
            ratio = SequenceMatcher(None, descs[a][1].casefold(), descs[b][1].casefold()).ratio()
            if ratio >= 0.93:
                errors.append(f"W12.3 semantic-surface near duplicate {descs[a][0]} / {descs[b][0]} ratio={ratio:.3f}")
    return errors
