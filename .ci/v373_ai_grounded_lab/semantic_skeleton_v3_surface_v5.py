from __future__ import annotations

from semantic_skeleton_v3_rules import *
import itertools
import json
import os
import re
import time


def _surface_fields_only(surface: dict | None) -> dict | None:
    """Keep only provider-owned fields; host-added namespace is diagnostic noise."""
    if not isinstance(surface, dict) or not isinstance(surface.get("items"), list):
        return None
    rows = []
    for raw in surface["items"]:
        if not isinstance(raw, dict):
            continue
        slot = str(raw.get("slot") or "").strip()
        title = str(raw.get("title") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not slot or not title or not description:
            continue
        rows.append({"slot": slot, "title": title, "description": description})
    return {"items": rows}


def _extract_failed_generation(exc: Exception) -> dict | None:
    """Recover Groq json_validate_failed content when the provider produced partial JSON."""
    text = str(exc)
    marker = "Groq HTTP "
    if marker not in text:
        return None
    brace = text.find("{")
    if brace < 0:
        return None
    try:
        detail = json.loads(text[brace:])
        failed = ((detail.get("error") or {}).get("failed_generation"))
        if isinstance(failed, str) and failed.strip():
            parsed = json.loads(failed)
            return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
    return None


def repair_surface_with_golden(lab, packet, surface: dict | None) -> tuple[dict | None, dict]:
    """Atomic deterministic packet fallback.

    A five-variant packet is one content unit. Mixing provider and curated
    wording produced uneven tone in early canaries, so v5 keeps the provider
    packet only when the whole packet validates. If any slot is missing or
    fails current validation, the entire packet is replaced by the curated
    golden surface with zero extra provider calls.
    """
    provider = _surface_fields_only(surface) or {"items": []}
    provider_by_slot = {}
    duplicate_slots = set()
    for row in provider["items"]:
        slot = str(row.get("slot") or "")
        if slot not in SLOT_IDS:
            continue
        if slot in provider_by_slot:
            duplicate_slots.add(slot)
            continue
        provider_by_slot[slot] = row

    complete = (
        set(provider_by_slot) == set(SLOT_IDS)
        and not duplicate_slots
    )
    provider_errors = []
    if complete:
        native_surface = {
            "items": [
                {
                    "slot": slot,
                    "title": str(provider_by_slot[slot]["title"]).strip(),
                    "description": str(provider_by_slot[slot]["description"]).strip(),
                }
                for slot in SLOT_IDS
            ]
        }
        try:
            native_payload = canonicalize_surface_payload(lab, packet, native_surface)
            provider_errors = lab.validate_payload(packet, native_payload)
        except Exception as exc:
            native_payload = None
            provider_errors = [f"canonicalization:{type(exc).__name__}:{exc}"]
        if native_payload is not None and not provider_errors:
            return native_payload, {
                "status": "PASS",
                "strategy": "native_packet",
                "provider_slots_seen": sorted(provider_by_slot),
                "golden_fallback_slots": [],
                "golden_fallback_count": 0,
                "native_slot_count": len(SLOT_IDS),
                "provider_calls_for_repair": 0,
                "provider_validation_errors": [],
            }

    golden = golden_surface(packet)
    try:
        payload = canonicalize_surface_payload(lab, packet, golden)
        golden_errors = lab.validate_payload(packet, payload)
    except Exception as exc:
        payload = None
        golden_errors = [f"golden_canonicalization:{type(exc).__name__}:{exc}"]

    if payload is not None and not golden_errors:
        return payload, {
            "status": "PASS",
            "strategy": "atomic_golden_packet_fallback",
            "provider_slots_seen": sorted(provider_by_slot),
            "golden_fallback_slots": list(SLOT_IDS),
            "golden_fallback_count": len(SLOT_IDS),
            "native_slot_count": 0,
            "provider_calls_for_repair": 0,
            "provider_validation_errors": provider_errors[:20],
            "missing_provider_slots": [slot for slot in SLOT_IDS if slot not in provider_by_slot],
            "duplicate_provider_slots": sorted(duplicate_slots),
        }

    return None, {
        "status": "FAIL",
        "strategy": "atomic_golden_packet_fallback",
        "provider_slots_seen": sorted(provider_by_slot),
        "golden_fallback_slots": list(SLOT_IDS),
        "golden_fallback_count": len(SLOT_IDS),
        "native_slot_count": 0,
        "provider_calls_for_repair": 0,
        "provider_validation_errors": provider_errors[:20],
        "golden_validation_errors": golden_errors[:20],
    }


