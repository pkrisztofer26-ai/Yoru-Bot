from __future__ import annotations

"""Static release gate for v3.74.0 W13.1 Memory + Opportunity Core Foundation."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

errors: list[str] = []

def need(text: str, token: str, label: str) -> None:
    if token not in text:
        errors.append(f"missing {label}: {token}")

version = read("VERSION").strip()
try:
    version_line = tuple(int(part) for part in version.split(".")[:2])
except ValueError:
    version_line = (0, 0)
if version_line < (3, 74):
    errors.append(f"VERSION expected v3.74+ regression line, got {version}")

memory = read("app/services/memory.py")
opp = read("app/services/opportunities.py")
world = read("app/services/world.py")
db = read("app/database.py")
reset = read("app/launch_reset_config.py")
main = read("app/main.py")
view = read("app/cogs/character_views/world.py")

for table in ("character_memory_state", "character_relationship_state", "player_opportunity_history"):
    need(db, f"CREATE TABLE IF NOT EXISTS {table}", f"schema {table}")
    need(reset, f'"{table}"', f"reset classification {table}")

need(db, "await self._ensure_memory_opportunity_schema(db)", "schema init call")
need(memory, "class ConsequenceMemoryService", "memory service")
need(memory, "async def record_consequence", "idempotent consequence API")
need(memory, "trust_band", "hidden semantic relationship band")
need(opp, "class OpportunityResolver", "resolver")
need(opp, "async def resolve", "resolver entry")
need(opp, "async def record_selection", "selection history")
need(world, "self.opportunity_resolver.resolve", "world resolver delegation")
need(world, "async def record_opportunity_selection", "world selection delegation")
need(main, "self.memory = ConsequenceMemoryService", "runtime memory binding")
need(main, "RPWorldService(self.database, self.memory)", "world memory binding")
need(view, "opportunity_key=opportunity_key", "UI selection tracking")

# The old player-facing opportunity route must remain the integration point.
if "async def opportunities(" not in world:
    errors.append("RPWorldService.opportunities() was removed instead of migrated")

# The structured state must not become a second player command/UI subsystem.
for path, text in (("memory.py", memory), ("opportunities.py", opp)):
    if "@app_commands" in text or "@commands.command" in text:
        errors.append(f"parallel player command detected in {path}")

# Raw hidden relationship numbers must not leak into the player-facing opportunity view.
if re.search(r"trust_score|favor_owed_(?:to|by)_player", view):
    errors.append("raw relationship state leaked into player-facing opportunity view")

# Player choice history only: resolving/displaying should not write a 'shown' event.
if '"shown"' in opp or "event_type=\"shown\"" in opp:
    errors.append("resolver records panel views; pacing history must track real player choices")

if errors:
    print("W13.1 MEMORY_OPPORTUNITY_GATE: FAIL")
    for error in errors:
        print(" -", error)
    raise SystemExit(1)

print("W13.1 MEMORY_OPPORTUNITY_GATE: PASS")
print(f"version={version}")
print("memory_state=character_memory_state")
print("relationship_state=character_relationship_state")
print("opportunity_history=selected-actions-only")
print("resolver=RPWorldService orchestration")
print("player_commands_added=0")
