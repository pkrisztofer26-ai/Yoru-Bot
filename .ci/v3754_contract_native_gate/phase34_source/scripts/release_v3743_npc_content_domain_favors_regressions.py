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

version = text("VERSION").strip()
try:
    version_line = tuple(int(part) for part in version.split(".")[:2])
except ValueError:
    version_line = (0, 0)
if version_line < (3, 74):
    raise AssertionError(f"VERSION must be on the v3.74+ regression line, got {version}")

npc = text("app/npc_config.py")
favor_cfg = text("app/npc_favor_config.py")
memory = text("app/services/memory.py")
followups = text("app/services/npc_followups.py")
adapters = text("app/services/memory_adapters.py")
vehicles = text("app/services/vehicles.py")
business = text("app/services/business.py")
economy = text("app/services/economy.py")
heist = text("app/services/heist.py")
notifications = text("app/cogs/notifications.py")
character = text("app/cogs/character.py")
world_view = text("app/cogs/character_views/world.py")
vehicle_view = text("app/cogs/character_views/vehicles.py")
business_cog = text("app/cogs/business.py")
main = text("app/main.py")

for key in (
    "bence_business_contact", "zoli_black_market_broker", "dora_legal_contact",
    "reka_property_agent", "akos_training_mentor", "eszter_merchant",
    "marci_city_contact", "tamas_organization_contact",
):
    need(npc, key, f"expanded NPC {key}")

need(favor_cfg, "class FavorEffectDefinition", "domain-owned favor contract")
need(favor_cfg, "jani_repair_discount", "Jani repair effect")
need(favor_cfg, "misi_dealership_discount", "Misi dealership effect")
need(favor_cfg, "bence_business_license_discount", "Bence business effect")
for forbidden in ("add_wallet(", "remove_wallet(", "add_item(", "award_xp("):
    forbid(favor_cfg, forbidden, "favor config settlement authority")
    forbid(followups, forbidden, "relationship settlement authority")

need(memory, "async def active_favor_effect_tx", "transactional favor voucher lookup")
need(memory, "async def consume_active_favor_effect_tx", "transactional favor voucher consumption")
need(followups, "effect_for_npc", "favor -> domain effect mapping")
need(followups, "relationship_summaries", "semantic relationship summary")
need(adapters, "async def business_license_purchased", "business memory adapter")
need(adapters, "async def vehicle_purchased", "vehicle purchase memory adapter")
need(adapters, "async def vehicle_repaired", "vehicle repair memory adapter")
need(adapters, "async def crime_resolved", "crime memory adapter")
need(adapters, "async def heist_resolved", "heist memory adapter")

need(vehicles, "active_favor_effect_tx", "vehicle favor voucher lookup")
need(vehicles, "consume_active_favor_effect_tx", "vehicle favor voucher settlement")
need(vehicles, "discount_saved", "vehicle discount result")
need(business, "buy_license_result", "business license result contract")
need(business, "active_favor_effect_tx", "business favor voucher lookup")
need(business, "consume_active_favor_effect_tx", "business favor voucher settlement")
need(economy, "crime_resolved", "crime outcome wiring")
need(heist, "heist_resolved", "heist outcome wiring")

need(notifications, 'label="Kapcsolatok"', "Telefon relationships button")
need(notifications, "focus_subject_key", "relationship deep-link")
need(character, "focus_key", "opportunity exact focus")
need(character, "focus_subject_key", "NPC subject focus")
need(world_view, "result.effect_label", "favor effect player copy")
need(vehicle_view, "Kapcsolati kedvezmény", "vehicle favor discount UI")
need(business_cog, "Bence közbenjárása", "business favor discount UI")

need(main, "VehicleService(self.database, self.characters, self.memory, self.memory_adapters)", "vehicle memory wiring")
need(main, "self.economy.bind_memory_adapters(self.memory_adapters)", "crime memory wiring")
need(main, "self.heists.bind_memory_adapters(self.memory_adapters)", "heist memory wiring")

for source, label in ((notifications, "Telefon UI"), (world_view, "relationship UI")):
    forbid(source, "trust_score", f"raw trust leak {label}")
    forbid(source, "favor_owed_to_player", f"raw favor leak {label}")

print("W13.4 NPC CONTENT / DOMAIN FAVOR EFFECTS / RELATIONSHIP OUTCOMES REGRESSION PASS")
