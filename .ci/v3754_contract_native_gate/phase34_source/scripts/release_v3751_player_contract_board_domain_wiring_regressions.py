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


if not text("VERSION").strip().startswith("3.75."):
    raise AssertionError("W14.2 regression remains valid only on the v3.75.x line")

service = text("app/services/contracts.py")
database = text("app/database.py")
extras = text("app/services/extras.py")
vehicles = text("app/services/vehicles.py")
profile = text("app/cogs/character_views/profile.py")
board = text("app/cogs/character_views/contracts.py")
world_view = text("app/cogs/character_views/world.py")
character = text("app/cogs/character.py")
notifications = text("app/cogs/notifications.py")
notification_contracts = text("app/services/notification_contracts.py")
notification_cfg = text("app/notification_config.py")
main = text("app/main.py")
reset = text("app/launch_reset_config.py")

# Canonical board reuses ContractService; no parallel contract backend/service.
need(service, "class ContractService", "canonical ContractService")
for forbidden in ("ContractBoardService", "ContractV2Service", "PlayerContractService"):
    forbid(service, forbidden, "parallel contract backend")
    forbid(board, forbidden, "parallel board backend")

# Player-facing board is routed through existing Life/Telefon/Opportunity surfaces.
for token in (
    'label="Megbízások"', "class ContractBoardView", "class ContractDetailView",
    "ItemContractModal", "CityContractModal",
):
    need(profile + board, token, "player contract board surface")
need(notifications, 'action_type == "contract"', "Telefon contract deep-link")
need(notifications, 'label="Megbízások"', "Telefon contract board button")
need(world_view, 'action_key.startswith("contract:")', "Lehetőségeim contract action")
need(character, 'source_family="contract"', "Lehetőségeim private active contract candidate")
for forbidden in ('app_commands.Group(name="megbizasok"', '@app_commands.command(name="megbizasok"'):
    forbid(profile + board + world_view + character + notifications, forbidden, "new top-level contract slash root")

# Domain-owned verification: stable travel id and idempotent item-transfer id.
for token in (
    "contract_event_claims", "item_transfer_history", "contract_history",
    "transfer_item_audited", "_transfer_item_tx",
):
    need(database, token, "stable domain/audit schema")
need(vehicles, "record_matching_city_delivery", "travel -> contract verification")
need(vehicles, "travel_id = int(travel_cur.lastrowid)", "stable travel history id")
need(extras, "deliver_contract_item", "inventory-domain contract delivery")
need(extras, "transfer_item_audited", "idempotent inventory transfer")
need(extras, "item_transfer:", "stable inventory event ref")
need(service, "record_matching_domain_event", "single-contract domain event resolver")

# Escrow/lifecycle remain state-backed and no manual authority escape hatch.
for token in (
    "create_player_contract", "accept_contract", "cancel_open_contract", "settle_if_ready",
    "contract_escrow:", "contract_settlement:", "expire_due",
):
    need(service, token, "W14.2 lifecycle")
for forbidden in ("manual_complete", "force_complete", "manual_payout", "force_settle"):
    forbid(service + board, forbidden, "manual completion/payout escape hatch")

# Contract notifications stay on existing NotificationService backend.
need(notification_contracts, "async def contract_update", "semantic contract notification intent")
need(notification_contracts, 'category="contract"', "contract notification category")
need(notification_cfg, '"contract": ("📦", "Megbízások")', "contract Telefon category")
need(main, "self.contracts.bind_notifications(self.notification_contracts)", "notification binding")
need(main, "self.extras.bind_contracts(self.contracts)", "item-domain binding")
need(main, "self.vehicles.bind_contracts(self.contracts)", "travel-domain binding")

# Launch reset explicitly owns every new persistent W14.2 table.
for token in ('"contract_event_claims"', '"contract_history"', '"item_transfer_history"'):
    need(reset, token, "launch-reset W14.2 ownership")

# Anti-spam / reciprocal telemetry is explicit, while NPC-funded reward API remains absent.
for token in (
    "PLAYER_MAX_ACTIVE_CREATED", "PLAYER_MAX_ACTIVE_ASSIGNED", "PLAYER_MAX_CREATES_24H",
    "contract.reciprocal_pair",
):
    need(text("app/contract_config.py") + service, token, "contract anti-abuse/telemetry")
for forbidden in ("create_npc_contract", "npc_reward_budget", "npc_funded_contract"):
    forbid(service, forbidden, "NPC-funded reward path before reward-budget authority")

print("W14.2 PLAYER CONTRACT BOARD / DOMAIN VERIFICATION / DELIVERY SURFACES REGRESSION PASS")
