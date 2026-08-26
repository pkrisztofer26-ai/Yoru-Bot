from __future__ import annotations

import hashlib
import json
from pathlib import Path

GATE = Path(__file__).resolve().parent
SRC = GATE / "source"
BASE = GATE.parent / "v3831_ai_director_review" / "frozen"
manifest = json.loads((GATE / "MANIFEST.json").read_text(encoding="utf-8"))

assert manifest["version"] == "3.83.4"
assert manifest["work_item"] == "W22.4"
assert manifest["contract"] == "tier2-context-surface-v1"
assert manifest["player_facing_scope"] == "TEST_GUILD_ONLY_DEFAULT_OFF"
assert manifest["gameplay_authority"] == "NONE"
assert manifest["live_deploy"] is False

for rel, expected in manifest["source_sha256"].items():
    path = SRC / rel
    assert path.is_file(), rel
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == expected, (rel, actual, expected)

base_provider = BASE / "app/providers/ai_director_groq.py"
assert base_provider.is_file()
assert hashlib.sha256(base_provider.read_bytes()).hexdigest() == manifest["inherited_w22_2_provider_sha256"]
base_provider_text = base_provider.read_text(encoding="utf-8")

core = (SRC / "app/ai_director_context.py").read_text(encoding="utf-8")
service = (SRC / "app/services/ai_director_context.py").read_text(encoding="utf-8")
provider = (SRC / "app/providers/ai_director_context_groq.py").read_text(encoding="utf-8")
review = (SRC / "scripts/ai_director_tier2_context_review.py").read_text(encoding="utf-8")
layer = "\n".join((core, service, provider, review))

for forbidden_import in (
    "services.economy", "services.business", "services.housing", "services.jobs",
    "services.cases", "services.vehicles", "services.police", "services.contracts", "services.assets",
):
    assert forbidden_import not in layer, forbidden_import

for required in (
    "career", "business", "travel", "housing", "npc", "tips", "case",
    "deterministic_context_fallback", "asyncio.wait_for", "TEST_GUILD_ONLY_DEFAULT_OFF",
):
    assert required in layer, required

assert "additionalProperties" in base_provider_text
assert "json_schema" in provider
assert '"temperature": 0.15' in provider
assert "max_completion_tokens" in provider
assert "GROQ_API_KEY" in review

print("W22_4_SOURCE_VERIFY=PASS")
print("NEW_SOURCE_SHA256=5/5 PASS")
print("INHERITED_W22_2_PROVIDER_SHA256=PASS")
print("TIER2_DOMAINS=7/7 PASS")
print("AUTHORITY_BOUNDARY=PASS")
print("PLAYER_FACING_SCOPE=TEST_GUILD_ONLY_DEFAULT_OFF")
print("GAMEPLAY_AUTHORITY=NONE")
print("LIVE_DEPLOY=UNCHANGED")
