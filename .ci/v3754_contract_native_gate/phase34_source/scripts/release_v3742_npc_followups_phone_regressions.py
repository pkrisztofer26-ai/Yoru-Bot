from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def need(source: str, token: str, label: str) -> None:
    if token not in source:
        raise AssertionError(f"Missing {label}: {token}")

def forbid(source: str, token: str, label: str) -> None:
    if token in source:
        raise AssertionError(f"Forbidden {label}: {token}")

memory = text("app/services/memory.py")
adapters = text("app/services/memory_adapters.py")
npc = text("app/npc_config.py")
followups = text("app/services/npc_followups.py")
opportunities = text("app/services/opportunities.py")
world = text("app/services/world.py")
world_view = text("app/cogs/character_views/world.py")
notifications = text("app/cogs/notifications.py")
profile = text("app/cogs/character_views/profile.py")
main = text("app/main.py")

need(memory, "async def consume_favor", "atomic favor consumption")
need(memory, "favor_owed_to_player=favor_owed_to_player-1", "favor decrement")
need(memory, "idempotency boundary", "favor idempotency documentation")
need(adapters, "bind_followups", "derived notification binding")
need(npc, "with_name", "canonical Hungarian NPC inflection")
need(followups, "class NPCFollowupService", "NPC followup service")
need(followups, "required_favor_to_player=1", "favor-gated candidate")
need(followups, 'required_rival_states=("tension",)', "tension candidate contract")
need(followups, 'required_rival_states=("rival",)', "rival candidate contract")
need(followups, "repeat_cooldown_hours=24", "anti-repeat cooldown")
need(opportunities, "async def record_event", "opportunity outcome history")
need(opportunities, "required_favor_to_player", "resolver favor requirement")
need(opportunities, "required_rival_states", "resolver rival requirement")
need(opportunities, "repeat_cooldown_hours", "resolver anti-repeat")
need(world, "bind_npc_followups", "world followup wiring")
need(world, "record_opportunity_outcome", "world outcome adapter")
need(world_view, 'action_key.startswith("favor:")', "favor player flow")
need(world_view, 'action_key.startswith("relationship:tension:")', "tension player flow")
need(world_view, 'action_key.startswith("relationship:rival:")', "rival player flow")
need(notifications, 'action_type in {"relationship", "opportunity"}', "Telefon CTA routing")
need(profile, 'label="Telefon"', "Life panel Telefon button")
need(main, "NPCFollowupService", "runtime followup service")
need(main, "bind_npc_followups", "runtime world binding")

for source, label in [(followups, "NPC followup service"), (world_view, "relationship UI")]:
    forbid(source, "trust_score", f"raw trust leak in {label}")
    forbid(source, "crime_rep", f"raw crime rep leak in {label}")

for forbidden in ("add_wallet", "remove_wallet", "add_item", "remove_item", "award_xp"):
    forbid(followups, forbidden, "relationship layer settlement authority")

print("W13.3 NPC FOLLOWUPS / FAVOR-RIVAL / TELEFON REGRESSION PASS")
