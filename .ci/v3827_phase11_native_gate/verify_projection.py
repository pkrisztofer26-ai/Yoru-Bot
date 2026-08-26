from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

GATE = Path(__file__).resolve().parent
SRC = GATE / "source"
MANIFEST = json.loads((GATE / "PROJECTION_MANIFEST.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> None:
    print(f"PHASE11_SOURCE_VERIFY=FAIL {msg}", file=sys.stderr)
    raise SystemExit(1)


if (SRC / "VERSION").read_text(encoding="utf-8").strip() != "3.82.7":
    fail("VERSION")

for rel, expected in MANIFEST["key_files"].items():
    path = SRC / rel
    if not path.is_file():
        fail(f"missing:{rel}")
    if sha256(path) != expected:
        fail(f"sha256:{rel}")

chapters = (SRC / "app/services/chapters.py").read_text(encoding="utf-8")
database = (SRC / "app/database.py").read_text(encoding="utf-8")
world_ui = (SRC / "app/cogs/character_views/world.py").read_text(encoding="utf-8")

for forbidden in ("chapter_scores", "chapter_choices", "chapter_rewards"):
    if forbidden in database.lower():
        fail(f"forbidden_table:{forbidden}")

if len(re.findall(r"CREATE TABLE IF NOT EXISTS\s+rp_world_chapters", database, flags=re.I)) != 2:
    fail("chapter_table_ddl_count")

if "await conn.execute(\"BEGIN IMMEDIATE\")" not in chapters:
    fail("chapter_transaction_lock")
if "await self.assets.award_event_collectible_tx(" not in chapters:
    fail("provenance_authority_binding")
if "WHERE chapter_run_id=? AND status='awaiting_resolution' AND ending_key IS NULL" not in chapters:
    fail("replay_safe_resolution_guard")
if "UNIQUE KEY uq_rp_world_chapter_active (guild_id, active_slot)" not in database:
    fail("active_slot_uniqueness")
if "ENGINE=InnoDB" not in database:
    fail("innodb_schema")

# Player-facing W21.8 UI may show localized stage/ending history but must not expose raw algorithm data.
for token in ("selection_rule", "source_counts", "committed_history_weight_v1"):
    if token in world_ui:
        fail(f"ui_internal_leak:{token}")

print("PHASE11_SOURCE_VERIFY=PASS")
print("FEATURE_BOUNDARY_AUDIT=W21.1-W21.8 PASS")
print("CHAPTER_AUTHORITY_STATIC=PASS")
print("CHAPTER_HISTORY_TABLE_COUNT=1")
print("FORBIDDEN_CHAPTER_TABLES=ABSENT")
print("PROVENANCE_AUTHORITY=ASSET_PROVENANCE")
print("LIVE_DEPLOY_MUTATION=NONE")
