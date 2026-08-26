from __future__ import annotations

import hashlib
import json
from pathlib import Path

GATE = Path(__file__).resolve().parent
SRC = GATE / "frozen"
BASE = GATE.parent / "v3831_ai_director_review" / "frozen"
manifest = json.loads((GATE / "MANIFEST.json").read_text(encoding="utf-8"))

assert manifest["version"] == "3.83.7"
assert manifest["work_item"] == "W22.5"
assert manifest["contract"] == "tier3-game-master-surface-v1"
assert manifest["player_facing_ai"] is False
assert manifest["gameplay_authority"] == "NONE"
assert manifest["runtime_wiring"] == "NONE"
assert manifest["live_deploy"] is False

mismatches = []
for rel, expected in manifest["source_sha256"].items():
    path = SRC / rel
    assert path.is_file(), rel
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"SOURCE_SHA256_ACTUAL {rel} {actual}")
    if actual != expected:
        mismatches.append((rel, actual, expected))

base_provider = BASE / "app/providers/ai_director_groq.py"
assert base_provider.is_file()
base_actual = hashlib.sha256(base_provider.read_bytes()).hexdigest()
print(f"INHERITED_GROQ_TRANSPORT_SHA256_ACTUAL {base_actual}")
assert base_actual == manifest["inherited_groq_transport_sha256"]

core = (SRC / "app/ai_director_game_master.py").read_text(encoding="utf-8")
service = (SRC / "app/services/ai_director_game_master.py").read_text(encoding="utf-8")
provider = (SRC / "app/providers/ai_director_game_master_groq.py").read_text(encoding="utf-8")
review = (SRC / "scripts/ai_director_tier3_game_master_review.py").read_text(encoding="utf-8")
layer = "\n".join((core, service, provider, review))

for family in ("big_job", "npc_story", "consequence_recall", "chapter", "world_story", "legendary_event"):
    assert family in core, family
for forbidden_import in (
    "services.economy", "services.heist", "services.chapters", "services.world", "services.memory",
    "services.assets", "services.contracts", "services.police",
):
    assert forbidden_import not in layer, forbidden_import
for forbidden_sql in ("UPDATE users", "INSERT INTO", "DELETE FROM", "UPDATE rp_", "UPDATE heist_"):
    assert forbidden_sql not in layer, forbidden_sql
assert 'GAME_MASTER_RUNTIME_ENABLED_DEFAULT = False' in core
assert 'source="deterministic_scenario_v2_fallback"' in core
assert 'if {str(key) for key in raw.keys()} != {"title", "description"}' in core
assert '"temperature": 0.1' in provider
assert '"strict": True' in provider
assert "HOST_FACTS" in provider and "Nem dönthetsz" in provider
assert '"version": "3.83.7"' in review and '"work_item": "W22.5"' in review
assert '"player_facing_ai": False' in review
assert '"gameplay_authority": "NONE"' in review
assert 'await asyncio.sleep(2.0)' in review

if mismatches:
    raise AssertionError(f"SOURCE_SHA_MISMATCHES={mismatches}")
print("W22_5_SOURCE_VERIFY=PASS")
print("SOURCE_SHA256=5/5 PASS")
print("INHERITED_GROQ_TRANSPORT_SHA256=PASS")
print("TIER3_FAMILIES=6/6 PASS")
print("AUTHORITY_BOUNDARY=PASS")
print("PLAYER_FACING_AI=OFF")
print("RUNTIME_WIRING=NONE")
print("LIVE_DEPLOY=UNCHANGED")
