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
    raise AssertionError("W14.4 regression gate requires the v3.75.x Phase 4 line")

cfg = text("app/contract_config.py")
service = text("app/services/contracts.py")
database = text("app/database.py")
reset = text("app/launch_reset_config.py")
board = text("app/cogs/character_views/contracts.py")
character = text("app/cogs/character.py")
business_cog = text("app/cogs/business.py")
business_service = text("app/services/business.py")
main = text("app/main.py")

# Modifiers are a config-owned deterministic allowlist, never arbitrary metadata.
for token in (
    "ContractModifierDefinition", "MODIFIER_BY_KEY", "modifier_effect", "modifier_labels",
    "priority_window", "bulk_support", "reward_multiplier_bp", "deadline_multiplier_bp",
    "required_multiplier_bp",
):
    need(cfg, token, "deterministic modifier contract")
for forbidden in ("eval(", "exec(", "ai_modifier", "llm_modifier", "model_modifier"):
    forbid(cfg + service, forbidden, "dynamic/AI modifier authority")

# Source pool expansion remains canonical config and same ContractService.
for token in (
    "marci_public_courier", "marci_private_courier", "jani_private_service",
    "bence_private_business_support", "contract_reward_budgets",
):
    need(cfg + service, token, "W14.4 source expansion")
for forbidden in ("ContractV2Service", "ServiceEconomyService", "PlayerServiceEconomyService"):
    forbid(cfg + service + business_service, forbidden, "parallel service/contract backend")

# Service economy is discovery/orchestration over existing domain actions.
for token in ("SERVICE_OBJECTIVE_TYPES", "SERVICE_LABEL_BY_OBJECTIVE"):
    need(cfg, token, "service discovery config")
need(service, "async def list_service_contracts", "shared service discovery")
for token in ('label="Szolgáltatások"', 'label="Ellátmány átadása"', 'label="Szervezet"', 'label="Nagy Meló"'):
    need(board, token, "natural existing-surface CTA")
need(business_cog, "BusinessSupplyContractModal", "business procurement player-service UI")
need(business_cog, 'source_ref=f"business_supply:', "business supply source trace")
need(business_service, "deliver_contract_supply", "BusinessService owning-domain completion")

# Telemetry is persistent, audit-only and launch-reset owned.
for token in (
    "contract_telemetry", "idx_contract_telemetry_type", "idx_contract_telemetry_contract",
):
    need(database, token, "contract telemetry schema")
need(reset, '"contract_telemetry"', "contract telemetry reset ownership")
for token in (
    "CONTRACT_HIGH_VALUE_THRESHOLD", "CONTRACT_RAPID_COMPLETION_SECONDS",
    "CONTRACT_REPEATED_PAIR_DAYS", "CONTRACT_REPEATED_PAIR_THRESHOLD",
):
    need(cfg, token, "anti-abuse telemetry thresholds")
for token in (
    'event_type="rapid_completion"', 'event_type="repeated_pair"', 'event_type="high_value"',
    'event_type="reward_budget"', 'event_type="reciprocal_pair"',
):
    need(service, token, "audit telemetry event")
for forbidden in (
    "auto_ban", "auto_punish", "auto_suspend", "automatic_ban", "contract_ban",
):
    forbid(service.lower(), forbidden, "automatic anti-abuse punishment")

# No new slash command tree; discovery stays in existing Life/Phone/business surfaces.
for forbidden in (
    'app_commands.Group(name="megbizasok"', '@app_commands.command(name="megbizasok"',
    'app_commands.Group(name="szolgaltatasok"', '@app_commands.command(name="szolgaltatasok"',
):
    forbid(board + character + business_cog, forbidden, "new W14.4 slash root")

# Runtime still wires the one ContractService into canonical domains.
for token in (
    "self.businesses.bind_contracts(self.contracts)", "self.vehicles.bind_contracts(self.contracts)",
    "self.crew.bind_contracts(self.contracts)", "self.heists.bind_contracts(self.contracts)",
):
    need(main, token, "canonical domain binding")

# No manual/AI settlement authority was introduced.
for forbidden in (
    "manual_complete", "force_complete", "manual_payout", "force_settle",
    "ai_reward", "ai_payout", "model_reward", "llm_payout",
):
    forbid(service + cfg + board + business_cog, forbidden, "manual/AI authority")

print("W14.4 CONTRACT MODIFIERS / PLAYER SERVICES / ANTI-ABUSE REGRESSION PASS")
