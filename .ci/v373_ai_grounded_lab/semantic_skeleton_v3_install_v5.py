from __future__ import annotations

from semantic_skeleton_v3_rules import *
from semantic_skeleton_v3_surface_v5 import *
from semantic_skeleton_v3_surface_v5 import _surface_fields_only, _extract_failed_generation
import itertools
import json
import os
import re
import time

def install_semantic_layer(lab) -> None:
    base_validate = lab.validate_payload
    base_request = lab.request_groq
    base_run_packet = lab.run_packet
    lab.CONTRACT_VERSION = CONTRACT_VERSION
    lab.output_schema = surface_output_schema
    lab.system_prompt = system_prompt_v3
    lab.user_prompt = user_prompt_v3
    lab._w123_surface_attempts = {}
    lab._w123_surface_events = {}

    def request_v3(**kwargs):
        packet = kwargs["packet"]
        try:
            surface, usage, latency, http_attempts, rate = base_request(**kwargs)
        except RuntimeError as exc:
            partial = _extract_failed_generation(exc)
            if partial is None:
                raise
            snapshot = _surface_fields_only(partial)
            if snapshot:
                lab._w123_surface_attempts.setdefault(packet.key, []).append(snapshot)
            payload, repair = repair_surface_with_golden(lab, packet, partial)
            if payload is None:
                raise
            event = {
                **repair,
                "trigger": "provider_json_schema_failed_generation",
                "provider_usage_unknown": True,
            }
            lab._w123_surface_events.setdefault(packet.key, []).append(event)
            # HTTP 400 usage/rate headers are not exposed by the frozen request
            # wrapper. Preserve the request as diagnostic evidence rather than
            # inventing token accounting.
            return payload, {}, 0.0, 1, {}

        snapshot = _surface_fields_only(surface)
        if snapshot:
            lab._w123_surface_attempts.setdefault(packet.key, []).append(snapshot)
        try:
            payload = canonicalize_surface_payload(lab, packet, surface)
            return payload, usage, latency, http_attempts, rate
        except Exception:
            payload, repair = repair_surface_with_golden(lab, packet, surface)
            if payload is None:
                raise
            lab._w123_surface_events.setdefault(packet.key, []).append({
                **repair,
                "trigger": "surface_structure_repair",
                "provider_usage_unknown": False,
            })
            return payload, usage, latency, http_attempts, rate

    def validate_v3(packet, payload):
        base = list(base_validate(packet, payload))
        if packet.profile == "world":
            base = [e for e in base if "choices count must be 1..2" not in e]
        return base + semantic_errors(lab, packet, payload)

    def run_packet_v3(args, packet, api_key, prior_keys, **kwargs):
        lab._w123_surface_attempts.pop(packet.key, None)
        lab._w123_surface_events.pop(packet.key, None)

        # v5 never spends a second provider request on wording. If the first
        # surface is not good enough, deterministic golden-slot repair handles
        # it or the packet fails with full evidence.
        kwargs["content_retries"] = 0
        result = base_run_packet(args, packet, api_key, prior_keys, **kwargs)

        surfaces = lab._w123_surface_attempts.get(packet.key) or []
        events = lab._w123_surface_events.get(packet.key) or []

        if result.get("status") != "PASS" and surfaces:
            payload, repair = repair_surface_with_golden(lab, packet, surfaces[-1])
            if payload is not None:
                result["status"] = "PASS"
                result["payload"] = payload
                result["host_surface_repair"] = {
                    **repair,
                    "trigger": "post_validation_repair",
                }
                if result.get("attempts"):
                    result["attempts"][-1]["post_validation_repair"] = "PASS"
                    result["attempts"][-1]["pre_repair_validation_errors"] = list(
                        result["attempts"][-1].get("validation_errors") or []
                    )
                result["repaired_from_failed_provider_surface"] = True

        if events:
            result["provider_surface_events"] = events
        if result.get("host_surface_repair") or events or result.get("status") != "PASS":
            result["provider_surfaces"] = surfaces

        repair_rows = list(events)
        if result.get("host_surface_repair"):
            repair_rows.append(result["host_surface_repair"])
        fallback_slots = set()
        for row in repair_rows:
            fallback_slots.update(row.get("golden_fallback_slots") or [])
        result["surface_quality"] = {
            "provider_attempt_surfaces": len(surfaces),
            "golden_fallback_slots": sorted(fallback_slots),
            "golden_fallback_count": len(fallback_slots),
            "native_slot_count": len(SLOT_IDS) - len(fallback_slots),
            "provider_second_content_request_used": False,
        }
        return result

    lab.request_groq = request_v3
    lab.validate_payload = validate_v3
    lab.run_packet = run_packet_v3
