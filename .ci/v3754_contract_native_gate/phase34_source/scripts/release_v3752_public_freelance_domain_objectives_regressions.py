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
    raise AssertionError("W14.3 regression gate requires the 3.75.x line")

cfg = text("app/contract_config.py")
service = text("app/services/contracts.py")
database = text("app/database.py")
opportunities = text("app/services/opportunities.py")
vehicles = text("app/services/vehicles.py")
crew = text("app/services/crew.py")
business = text("app/services/business.py")
heist = text("app/services/heist.py")
main = text("app/main.py")
board = text("app/cogs/character_views/contracts.py")
character = text("app/cogs/character.py")
reset = text("app/launch_reset_config.py")

# Deterministic source config; reward is config-owned, not model/UI owned.
for token in (
    "ContractSourceDefinition", "lilla_public_courier", "jani_public_service",
    "lilla_private_courier", "budget_daily_limit", "reward_amount",
    "required_trust_bands", "SYSTEM_SOURCE_TYPES",
):
    need(cfg, token, "deterministic public/private source config")

# Reward budget + source metadata are persistent and auditable.
for token in (
    "contract_reward_budgets", "contract_source_state", "reserved_amount", "spent_amount",
    "business_delivery_history",
):
    need(database, token, "W14.3 audit schema")
for token in ('"contract_reward_budgets"', '"contract_source_state"', '"business_delivery_history"'):
    need(reset, token, "launch-reset W14.3 ownership")

# Same ContractService; no parallel contract engine.
for token in (
    "create_system_contract", "ensure_freelance_sources", "bind_opportunity_resolver",
    "reward-budget reservation", "contract_reward_budgets", "record_matching_domain_event",
):
    need(service, token, "canonical ContractService W14.3 behavior")
for forbidden in ("ContractV2Service", "NPCContractService", "FreelanceContractService"):
    forbid(service + cfg, forbidden, "parallel contract service")

# Private ladder eligibility reuses OpportunityResolver/Memory semantics.
need(opportunities, "def requirements_match", "shared memory requirements helper")
need(opportunities, "async def requirements_eligible", "shared async eligibility gate")
need(service, "self.opportunity_resolver.requirements_eligible", "private contract resolver gate")
for forbidden in ("trust_score >=", "trust_score >", "raw_trust"):
    forbid(service + board + character, forbidden, "raw relationship-score contract gate/UI")

# Remaining domain objective types are backed by owning-domain stable events.
need(vehicles, 'event_key=f"vehicle_repair_tx:', "vehicle repair transaction event")
need(vehicles, 'event_type="vehicle_service_completed"', "vehicle service objective hook")
need(database, "deposit_to_crew_audited", "crew deposit stable transaction primitive")
need(crew, 'event_key=f"crew_deposit_tx:', "crew contribution event")
need(crew, 'event_type="contribution_recorded"', "contribution objective hook")
need(business, "deliver_contract_supply", "business-owned delivery action")
need(business, "business_delivery_history", "business delivery audit source")
need(business, 'event_type="business_delivery_completed"', "business delivery objective hook")
need(heist, 'event_key=f"heist_run:', "heist stable participation event")
need(heist, 'event_type="system_participation"', "system participation objective hook")

# Runtime wiring stays cross-domain and existing source-of-truth services remain authority.
for token in (
    "self.contracts.bind_opportunity_resolver(self.world.opportunity_resolver)",
    "self.crew.bind_contracts(self.contracts)", "self.businesses.bind_contracts(self.contracts)",
    "self.heists.bind_contracts(self.contracts)", "self.vehicles.bind_contracts(self.contracts)",
):
    need(main, token, "W14.3 runtime binding")

# Player surface expands the existing board/Telefon/Lehetőségeim; no new command root.
need(board, "Unified Contract Economy", "unified board wording")
need(board, "source_label", "source-safe board label")
need(character, "list_open_contracts", "existing board payload")
need(character, 'source_family="contract"', "existing Lehetőségeim integration")
for forbidden in ('app_commands.Group(name="megbizasok"', '@app_commands.command(name="megbizasok"'):
    forbid(board + character, forbidden, "new contract slash root")

# Safety: no manual payout/completion and no AI financial/state authority.
for forbidden in (
    "manual_complete", "force_complete", "manual_payout", "force_settle",
    "ai_reward", "ai_payout", "model_reward", "llm_payout",
):
    forbid(service + cfg + board, forbidden, "manual/AI settlement authority")

print("W14.3 PUBLIC/NPC FREELANCE / DOMAIN OBJECTIVES / PRIVATE LADDER REGRESSION PASS")
