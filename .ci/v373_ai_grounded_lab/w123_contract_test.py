from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import sys

HERE = Path(__file__).resolve().parent
TARGET = HERE / "semantic_skeleton_v3.py"

spec = importlib.util.spec_from_file_location("w123_semantic_contract_target", TARGET)
if not spec or not spec.loader:
    raise SystemExit("cannot import semantic_skeleton_v3.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

lab = mod.V2.load_lab()
mod.V2.install_provider_hotfix(lab)
mod.install_semantic_layer(lab)

checks = []
def ok(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)
    print(f"PASS {name}")

ok("config_version", mod.CONFIG["version"] == mod.CONTRACT_VERSION)
ok("matrix_24_packets_120_items", len(lab.PACKETS) == 24 and sum(p.count for p in lab.PACKETS) == 120)
ok("all_packets_configured", set(mod.CONFIG["packets"]) == {p.key for p in lab.PACKETS})

for packet in lab.PACKETS:
    schema = mod.surface_output_schema(packet)
    props = schema["properties"]["items"]["items"]["properties"]
    ok(f"surface_schema_{packet.key}", set(props) == {"slot", "title", "description"})

# Full host canonicalization must produce payloads accepted by the frozen structural/authority validator
# and the W12.3 semantic validator when fed conservative safe probe descriptions.
templates = [
    "{a} együtt jelöli ki a jelenet lényegét, minden más részlet nélkül.",
    "A rövid jelenet fókusza {a}, és ezen kívül nem állít mást.",
    "Csak {a} kerül szóba; a szöveg nem bővíti tovább a jelenetet.",
    "A leírás {a} kapcsolatát tartja meg, új részlet hozzáadása nélkül.",
    "{a} marad az egyetlen tartalmi fókusz, ezért a jelenet rövid és zárt.",
]
for packet in lab.PACKETS:
    anchors = " ".join(group[0] for group in mod.packet_cfg(packet)["anchors"])
    surface = {"items": [
        {"slot": slot, "title": f"Próbacím {chr(65+i)}", "description": templates[i].format(a=anchors)}
        for i, slot in enumerate(mod.SLOT_IDS)
    ]}
    canonical = mod.canonicalize_surface_payload(lab, packet, surface)
    errs = lab.validate_payload(packet, canonical)
    ok(f"host_payload_{packet.key}", not errs)
    if packet.profile == "world":
        ok(f"world_no_choice_{packet.key}", all(x["choices"] == [] for x in canonical["items"]))
    else:
        ok(f"host_choice_count_{packet.key}", all(1 <= len(x["choices"]) <= 2 for x in canonical["items"]))

reg = mod.regression_report(lab)
ok("w122_regression_120_loaded", reg["source_items"] == 120)
ok("w122_regression_24_loaded", reg["source_packets"] == 24)
ok("w122_blockers_all_rejected", reg["blocker_packets_rejected"] == reg["source_blocker_packets"] == 10)
ok("w122_legacy_rejection_floor", reg["legacy_packets_rejected"] >= 20)
ok("w122_regression_gate", reg["acceptance"] == "PASS")

# Concrete QA regressions.
canteen = next(p for p in lab.PACKETS if p.key == "work_miskolc_canteen")
base = " ".join(g[0] for g in mod.packet_cfg(canteen)["anchors"])
surface = {"items": [{"slot": s, "title": f"Menza próba {chr(65+i)}", "description": f"{base} zöldséget választ a helyzetben {chr(97+i)}."} for i,s in enumerate(mod.SLOT_IDS)]}
errs = lab.validate_payload(canteen, mod.canonicalize_surface_payload(lab, canteen, surface))
ok("reject_canteen_ingredient_invention", any("ingredient_invention" in e for e in errs))

envelope = next(p for p in lab.PACKETS if p.key == "crime_unknown_envelope")
base = " ".join(g[0] for g in mod.packet_cfg(envelope)["anchors"])
surface = {"items": [{"slot": s, "title": f"Boríték próba {chr(65+i)}", "description": f"{base} és azt mondja, hogy vedd át helyette {chr(97+i)}."} for i,s in enumerate(mod.SLOT_IDS)]}
errs = lab.validate_payload(envelope, mod.canonicalize_surface_payload(lab, envelope, surface))
ok("reject_envelope_direction_inversion", any("direction_inversion" in e for e in errs))

world = next(p for p in lab.PACKETS if p.key == "world_eger_heat")
base = " ".join(g[0] for g in mod.packet_cfg(world)["anchors"])
surface = {"items": [{"slot": s, "title": f"Egri próba {chr(65+i)}", "description": f"{base} mellett a tömegközlekedés is érintett {chr(97+i)}."} for i,s in enumerate(mod.SLOT_IDS)]}
errs = lab.validate_payload(world, mod.canonicalize_surface_payload(lab, world, surface))
ok("reject_world_transport_invention", any("world_detail_invention" in e for e in errs))

panic = next(p for p in lab.PACKETS if p.key == "store_heist_teammate_panic")
base = " ".join(g[0] for g in mod.packet_cfg(panic)["anchors"])
surface = {"items": [{"slot": s, "title": f"Csapatpróba {chr(65+i)}", "description": f"{base}, majd légzőgyakorlatot kezd {chr(97+i)}."} for i,s in enumerate(mod.SLOT_IDS)]}
errs = lab.validate_payload(panic, mod.canonicalize_surface_payload(lab, panic, surface))
ok("reject_panic_method_invention", any("panic_method_invention" in e for e in errs))

source = TARGET.read_text(encoding="utf-8")
ok("dev_only_no_app_import", "from app" not in source and "import app" not in source)
ok("production_ai_never_authorized", "production_ai_authorized\": False" in source or '"production_ai_authorized": False' in source)

print(f"W12_3_CONTRACT_TESTS_PASS {len(checks)}/{len(checks)}")
