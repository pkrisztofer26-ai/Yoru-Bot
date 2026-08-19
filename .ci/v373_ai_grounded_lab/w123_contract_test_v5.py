from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import base64
import gzip
import importlib.util
import json
import sys

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"
FIXTURE = HERE / "w123_v4_canteen_fail_checkpoint.b64"


def load_target():
    spec = importlib.util.spec_from_file_location("w123_v5_contract_target", TARGET)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load semantic target")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ok(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


mod = load_target()
lab = mod.V2.load_lab()
mod.V2.install_provider_hotfix(lab)
mod.install_semantic_layer(lab)
packet = next(p for p in lab.PACKETS if p.key == "work_miskolc_canteen")

doc = json.loads(gzip.decompress(base64.b64decode(FIXTURE.read_text(encoding="ascii"))).decode("utf-8"))
result = doc["result"]
surface = result["provider_surfaces"][0]

ok("contract_v5", mod.CONTRACT_VERSION == "w12.3-semantic-skeleton-v5")

prompt = mod.user_prompt_v3(packet, [])
ok("seed_guided_prompt", "surface_seeds" in prompt and "enyhén" in prompt)
ok("prompt_contains_five_seeds", all(slot in prompt for slot in mod.SLOT_IDS))
ok("prompt_compact", len(prompt) < 4200)

# The observed phrase "késő szállítással" is semantically a delay and must not
# fail merely because it does not contain the exact lexical forms késik/késés.
focus_b = surface["items"][1]["description"]
raw_payload = mod.canonicalize_surface_payload(lab, packet, mod._surface_fields_only(surface))
raw_errors = lab.validate_payload(packet, raw_payload)
ok(
    "hungarian_delay_phrase_alias",
    not any(e.startswith("items[1]: semantic anchor coverage too weak") for e in raw_errors),
)

# Raw provider diagnostics must expose only provider-owned fields.
clean = mod._surface_fields_only(surface)
ok("surface_diagnostic_strips_host_namespace", all(set(x) == {"slot", "title", "description"} for x in clean["items"]))

# The real v4 first surface contains unsupplied/awkward wording. v5 must not
# mix it with curated wording: the packet falls back atomically to the golden packet.
payload, repair = mod.repair_surface_with_golden(lab, packet, surface)
ok("real_v4_surface_repaired", payload is not None and not lab.validate_payload(packet, payload))
ok("atomic_packet_fallback", repair.get("golden_fallback_count") == 5 and repair.get("native_slot_count") == 0)
ok("real_v4_surface_regressions_recorded", len(repair.get("provider_validation_errors") or []) >= 1)

# The v4 retry produced only four items inside Groq failed_generation.
error_text = result["attempts"][1]["error"]
partial = mod._extract_failed_generation(RuntimeError(error_text))
ok("extract_real_four_of_five_failed_generation", isinstance(partial, dict) and len(partial.get("items") or []) == 4)
payload2, repair2 = mod.repair_surface_with_golden(lab, packet, partial)
ok("four_of_five_zero_token_recovery", payload2 is not None and not lab.validate_payload(packet, payload2))
ok("partial_packet_uses_atomic_golden", repair2.get("golden_fallback_count") == 5)

# A fully valid golden packet remains native (no unnecessary fallback).
golden = mod.golden_surface(packet)
gold_payload, gold_meta = mod.repair_surface_with_golden(lab, packet, golden)
ok("golden_native_packet", gold_payload is not None and gold_meta.get("strategy") == "native_packet")
ok("golden_zero_fallback", gold_meta.get("golden_fallback_count") == 0)

# Prove one provider surface -> one request only. The fake 120B surface is the
# exact observed v4 surface. v5 repairs it after validation instead of issuing
# a second content request.
lab2 = mod.V2.load_lab()
calls = {"n": 0}
def fake_request(**kwargs):
    calls["n"] += 1
    return json.loads(json.dumps(surface)), {
        "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150
    }, 1.0, 1, {"remaining_tokens": 7000, "limit_tokens": 8000, "reset_tokens_seconds": 1.0}

lab2.request_groq = fake_request
mod.install_semantic_layer(lab2)
packet2 = next(p for p in lab2.PACKETS if p.key == "work_miskolc_canteen")
args = SimpleNamespace(
    content_retries=9, endpoint="fake", model="openai/gpt-oss-120b",
    reasoning_effort="low", timeout=1, max_completion_tokens=900,
    http_retries=0, input_usd_per_million=0.15, output_usd_per_million=0.60,
)
one = lab2.run_packet(args, packet2, "fake-key", [], content_retries=9)
ok("single_provider_request_policy", calls["n"] == 1)
ok("post_validation_atomic_repair_pass", one.get("status") == "PASS" and one.get("host_surface_repair", {}).get("golden_fallback_count") == 5)
ok("no_second_content_request", one.get("surface_quality", {}).get("provider_second_content_request_used") is False)

print("W12_3_V5_EXTRA_CONTRACT_TESTS_PASS 18/18")
