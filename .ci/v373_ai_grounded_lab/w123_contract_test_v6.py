from __future__ import annotations

import semantic_skeleton_v3 as mod

lab = mod.V2.load_lab()
mod.V2.install_provider_hotfix(lab)
mod.install_semantic_layer(lab)

assert mod.CONTRACT_VERSION == "w12.3-semantic-skeleton-v8"
assert mod.CONFIG["version"] == mod.CONTRACT_VERSION
assert len(lab.PACKETS) == 24
count = 0
for packet in lab.PACKETS:
    payload = mod.canonicalize_surface_payload(lab, packet, mod.golden_surface(packet))
    errors = lab.validate_payload(packet, payload)
    assert not errors, (packet.key, errors)
    count += len(payload["items"])
assert count == 120
assert mod.regression_report(lab)["blocker_packets_accepted"] == 0
print("W12_3_V8_COMPAT_REGRESSIONS_PASS golden=120/120 blockers=0")
