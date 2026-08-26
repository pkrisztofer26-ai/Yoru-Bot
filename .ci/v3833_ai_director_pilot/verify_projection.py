from __future__ import annotations

import hashlib
import json
from pathlib import Path

GATE = Path(__file__).resolve().parent
FROZEN = GATE / "frozen"
manifest = json.loads((GATE / "MANIFEST.json").read_text(encoding="utf-8"))
projection = json.loads((GATE / "ENTRYPOINT_PROJECTION.json").read_text(encoding="utf-8"))

assert manifest["version"] == "3.83.3"
assert manifest["pilot_default"] is False
assert manifest["test_guild_only"] is True
assert manifest["live_provider_in_gameplay"] is False
assert manifest["generic_ai_runtime_enabled"] is False
assert manifest["live_deploy"] is False

for rel, expected in manifest["core_source_sha256"].items():
    path = FROZEN / rel
    assert path.is_file(), rel
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected, (rel, actual, expected)

pilot = (FROZEN / "app/ai_director_pilot.py").read_text(encoding="utf-8")
config = (FROZEN / "app/config.py").read_text(encoding="utf-8")

assert 'W22_2_1_HUMAN_QA = "15/15 GO"' in pilot
assert 'source="human_reviewed_cache"' in pilot
assert 'enabled: bool = False' in pilot
assert 'self.test_guild_id is not None' in pilot
assert 'int(guild_id) == int(self.test_guild_id)' in pilot
for forbidden in (
    "GroqAIDirectorProvider", "GROQ_API_KEY", "AIDirectorCacheRepository",
    "services.economy", "services.assets", "services.contracts", "services.heist",
):
    assert forbidden not in pilot, forbidden

assert 'env_bool("YORU_AI_DIRECTOR_PILOT_ENABLED", False)' in config
assert 'ai_director_pilot_enabled and guild_id is None' in config
assert 'explicit TEST_GUILD_ID' in config

assert projection["local_full_tree_checkpoint"] == "79/79 PASS"
assert len(projection["call_sites"]) == 4
assert projection["runtime_boundary"]["generic_ai_provider"] is None
assert projection["runtime_boundary"]["generic_ai_runtime_enabled"] is False
assert projection["runtime_boundary"]["live_provider_in_gameplay"] is False
assert projection["runtime_boundary"]["pilot_scope"] == "explicit TEST_GUILD_ID only"
assert set(projection["forbidden_pilot_inputs"]) >= {
    "reward", "amount", "success", "scenario", "outcome", "place", "cooldown", "inventory"
}

print("W22_3_SOURCE_VERIFY=PASS")
print("CORE_SOURCE_SHA256=2/2 PASS")
print("PILOT_DEFAULT=OFF")
print("PILOT_SCOPE=TEST_GUILD_ONLY")
print("PILOT_SOURCE=HUMAN_REVIEWED_STATIC_BUNDLE")
print("LIVE_PROVIDER_IN_GAMEPLAY=ABSENT")
print("AI_GAMEPLAY_AUTHORITY=NONE")
print("FULL_TREE_LOCAL_CHECKPOINT=79/79 PASS")
print("LIVE_DEPLOY=UNCHANGED")
