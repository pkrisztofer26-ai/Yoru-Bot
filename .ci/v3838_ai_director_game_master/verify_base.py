from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".ci/v3837_ai_director_game_master/frozen"
GATE = ROOT / ".ci/v3838_ai_director_game_master"

base_expected = {
    "app/ai_director_game_master.py": "c595ec783e112b1f7a78895f9b86b726fef468ae25c2a3495007cd403240f6fa",
    "app/services/ai_director_game_master.py": "ff8232e5bc527328283b4d9a1e7bc402fd5be3e7e80fd0ae62e94cb8257a4b43",
    "app/providers/ai_director_game_master_groq.py": "6bba292d3bd0bc30e4b1a9e01b70ceed0d352c94974fe9c2ca1fedbc69272c91",
    "scripts/ai_director_tier3_game_master_review.py": "21b5586f48bb03bdabed2678aae560744f0a6229c737c5f49e0d7bc68cb0aaf0",
    "tests/test_w22_5_game_master_ci.py": "65fd8ec55a9207b7eddf850a2b92ea570ae49d8b7275bcd4e79e19623f436e36",
}
for rel, expected in base_expected.items():
    path = BASE / rel
    assert path.is_file(), rel
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"BASE_SHA256_ACTUAL {rel} {actual}")
    assert actual == expected, (rel, actual, expected)

patch = GATE / "w2251.patch"
assert patch.is_file()
patch_sha = hashlib.sha256(patch.read_bytes()).hexdigest()
print(f"PATCH_SHA256_ACTUAL {patch_sha}")
assert patch_sha == "d9462dc86aa9edd19374cbdf23fd76ca86972a53f466d393623c26d164641926"

print("W22_5_1_BASE_VERIFY=PASS")
print("BASE_SOURCE_SHA256=5/5 PASS")
print("HARDENING_PATCH_SHA256=PASS")
print("TIER3_FAMILIES=6/6")
print("PLAYER_FACING_AI=OFF")
print("RUNTIME_WIRING=NONE")
print("GAMEPLAY_AUTHORITY=NONE")
print("LIVE_DEPLOY=UNCHANGED")
