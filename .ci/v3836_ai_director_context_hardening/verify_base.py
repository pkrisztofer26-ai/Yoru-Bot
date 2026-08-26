from __future__ import annotations
import hashlib, json
from pathlib import Path

GATE = Path(__file__).resolve().parent
BASE = GATE.parent / "v3834_ai_director_context" / "source"
manifest = json.loads((GATE / "MANIFEST.json").read_text(encoding="utf-8"))
assert manifest["version"] == "3.83.6"
assert manifest["work_item"] == "W22.4.2"
assert manifest["contract"] == "tier2-context-surface-v3"
assert manifest["player_facing_scope"] == "TEST_GUILD_ONLY_DEFAULT_OFF"
assert manifest["gameplay_authority"] == "NONE"
assert manifest["live_deploy"] is False
for rel, expected in manifest["base_source_sha256"].items():
    path = BASE / rel
    assert path.is_file(), rel
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, rel
patch = GATE / "w2242.patch"
assert patch.is_file()
assert hashlib.sha256(patch.read_bytes()).hexdigest() == manifest["patch_sha256"]
text = patch.read_text(encoding="utf-8")
for marker in ("tier2-context-surface-v3", "_FORBIDDEN_HUNGARIAN_SURFACE_RE", "otthonvárosban helyezkedik el", "ügyben áll", "érkezett"):
    assert marker in text, marker
print("W22_4_2_BASE_VERIFY=PASS")
print("BASE_SOURCE_SHA256=5/5 PASS")
print("HARDENING_PATCH_SHA256=PASS")
print("HUMAN_QA_REGRESSIONS=3/3 ENCODED")
print("PLAYER_FACING_SCOPE=TEST_GUILD_ONLY_DEFAULT_OFF")
print("GAMEPLAY_AUTHORITY=NONE")
print("LIVE_DEPLOY=UNCHANGED")
