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
    raise AssertionError("W14.1 regression remains valid only on the v3.75.x line")

cfg = text("app/contract_config.py")
service = text("app/services/contracts.py")
database = text("app/database.py")
main = text("app/main.py")
reset = text("app/launch_reset_config.py")
business = text("app/services/business.py")
social = text("app/services/social_economy.py")
faction = text("app/services/faction.py")

# Whole-application overlap audit is explicit and legacy authorities remain present.
for token in ("business_offers", "pvp_duels", "player_market_listings", "crew_wars"):
    need(cfg, token, f"overlap audit {token}")
need(business, "async def create_offer", "existing business-offer authority")
need(social, "async def buy_listing", "existing marketplace authority")
need(social, "async def settle_duel", "existing PvP authority")
need(faction, "async def create_war", "existing crew-war objective authority")

# Canonical foundation, no parallel V2 service naming.
need(service, "class ContractService", "canonical contract service")
for forbidden in ("ContractV2Service", "EscrowV2", "ContractEconomyV2"):
    forbid(service, forbidden, "parallel replacement service")
    forbid(main, forbidden, "parallel replacement wiring")

# Player-funded escrow and atomic lifecycle.
for token in (
    "async def create_player_contract",
    "async def accept_contract",
    "async def settle_ready_contract",
    "async def cancel_open_contract",
    "async def expire_due",
    "contract_escrow:",
    "contract_settlement:",
    "contract_refund_cancelled:",
    "contract_refund_expired:",
    "BEGIN IMMEDIATE",
    "escrow_wallet_amount",
    "escrow_bank_amount",
):
    need(service, token, "contract atomic lifecycle")

# State-backed objective vocabulary and explicit domain-event wrappers.
for token in (
    '"item_delivery"', '"city_delivery"', '"business_delivery"',
    '"vehicle_service"', '"contribution"', '"system_participation"',
):
    need(cfg, token, "objective vocabulary")
for method in (
    "record_item_delivery", "record_city_delivery", "record_business_delivery",
    "record_vehicle_service", "record_contribution", "record_system_participation",
):
    need(service, f"async def {method}", f"state-backed event wrapper {method}")

# No manual completion or arbitrary payout escape hatch.
for forbidden in (
    "manual_complete", "approve_objective", "force_complete", "manual_payout", "force_settle"
):
    forbid(service, forbidden, "manual authority escape hatch")

# Backend-aware schema + launch reset ownership.
for token in (
    "async def reserve_wallet_and_bank_tx",
    "async def refund_wallet_and_bank_tx",
    "async def credit_wallet_tx",
):
    need(database, token, "shared transaction-scoped economy primitive")
for token in (
    "self.db.reserve_wallet_and_bank_tx",
    "self.db.refund_wallet_and_bank_tx",
    "self.db.credit_wallet_tx",
):
    need(service, token, "contract use of shared economy primitive")

for token in (
    "CREATE TABLE IF NOT EXISTS contracts",
    "CREATE TABLE IF NOT EXISTS contract_objectives",
    "CREATE TABLE IF NOT EXISTS contract_events",
    "DECIMAL(65,0)",
    "_ensure_contract_economy_schema",
):
    need(database, token, "contract schema")
for token in ('"contract_events"', '"contract_objectives"', '"contracts"'):
    need(reset, token, "launch reset contract ownership")
need(reset, '"contracts": ("reward_amount", "escrow_wallet_amount", "escrow_bank_amount")', "contract money audit")
need(main, "self.contracts = ContractService(self.database)", "runtime contract service wiring")

print("W14.1 UNIFIED CONTRACT ECONOMY FOUNDATION REGRESSION PASS")
