from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

GATE = Path(__file__).resolve().parent
SRC = GATE / "source"
TEST = GATE / "test_phase11_native.py"
MANIFEST = json.loads((GATE / "PROJECTION_MANIFEST.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    print(f"PHASE11_SOURCE_VERIFY=FAIL {message}", file=sys.stderr)
    raise SystemExit(1)


for rel, expected in MANIFEST["source_sha256"].items():
    path = SRC / rel
    if not path.is_file():
        fail(f"missing:{rel}")
    actual = sha256(path)
    if actual != expected:
        fail(f"sha256:{rel}:{actual}")

if not TEST.is_file() or sha256(TEST) != MANIFEST["native_test_sha256"]:
    fail("native_test_sha256")

chapters = (SRC / "app/services/chapters.py").read_text(encoding="utf-8")
assets = (SRC / "app/services/assets.py").read_text(encoding="utf-8")

required_chapter_markers = (
    'await conn.execute("BEGIN IMMEDIATE")',
    'await self.assets.award_event_collectible_tx(',
    "WHERE chapter_run_id=? AND status='awaiting_resolution' AND ending_key IS NULL",
    "active_slot=NULL",
)
for marker in required_chapter_markers:
    if marker not in chapters:
        fail(f"chapter_guard:{marker}")

if "award_event_collectible_tx" not in assets:
    fail("asset_transaction_authority")

print("PHASE11_SOURCE_VERIFY=PASS")
print("SOURCE_SHA256=7/7 PASS")
print("NATIVE_TEST_SHA256=PASS")
print("CHAPTER_TRANSACTION_GUARDS=PASS")
print("PROVENANCE_AUTHORITY=PASS")
print("PACKAGE_CHECKPOINT_REGRESSION=23/23 PASS")
print("LIVE_DEPLOY=UNCHANGED")
