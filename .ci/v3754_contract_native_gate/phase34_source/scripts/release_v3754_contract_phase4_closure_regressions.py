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


if text("VERSION").strip() != "3.75.4":
    raise AssertionError("W14.5 checkpoint must be 3.75.4")

cfg = text("app/contract_config.py")
service = text("app/services/contracts.py")
character = text("app/cogs/character.py")
database = text("app/database.py")
backend = text("app/db_backend.py")
board = text("app/cogs/character_views/contracts.py")
main = text("app/main.py")

# Crash-gap recovery must settle verified-complete work before expiry.
for token in (
    "ContractRecoveryReport", "recover_ready_contracts", "recover_restart_state", "maintain_contracts",
    "reconcile_reward_budgets", "telemetry_summary", "prune_telemetry",
):
    need(service, token, "W14.5 closure service")
need(service, "NOT EXISTS (", "verified-complete recovery predicate")
need(service, "MAX(o.updated_at)", "pre-deadline verification proof")
need(service, "status<>'completed'", "expiry only incomplete objective guard")
need(character, "await contracts.recover_restart_state(guild.id)", "startup restart recovery")
need(character, "await contracts.maintain_contracts(guild.id)", "periodic contract maintenance")

# Reward-budget recovery remains deterministic and never decreases spent history.
for token in (
    "expected_reserved", "expected_spent", "target_reserved = expected_reserved",
    "target_spent = max(current_spent, expected_spent)", "reserved_amount=excluded.reserved_amount",
):
    need(service, token, "reward budget reconciliation")
for forbidden in ("ai_budget", "ai_reward", "llm_budget", "model_budget"):
    forbid((cfg + service).lower(), forbidden, "AI reward-budget authority")

# Stable event claims remain globally unique and replay-aware.
need(database, "contract_event_claims", "stable event-claim schema")
need(service, "A concurrent/retried domain delivery", "concurrent claim replay recovery")
need(service, "replay=True", "domain replay semantic")

# Telemetry is queryable but bounded; it never becomes an enforcement score.
for token in ("CONTRACT_TELEMETRY_RETENTION_DAYS", "CONTRACT_TELEMETRY_MAX_ROWS_PER_GUILD"):
    need(cfg, token, "telemetry bounds")
for token in ("DELETE FROM contract_telemetry", "GROUP BY event_type"):
    need(service, token, "bounded aggregate telemetry")
for forbidden in ("risk_score", "auto_ban", "auto_suspend", "auto_punish", "deny_settlement"):
    forbid(service.lower(), forbidden, "automatic abuse punishment")

# Native backend stays InnoDB + conservative cross-connection write serialization.
need(database, "ENGINE=InnoDB", "native InnoDB contract schema")
need(backend, "SELECT GET_LOCK", "legacy cross-connection write lock")
need(backend, "SELECT RELEASE_LOCK", "legacy cross-connection write lock release")

# No feature-sprawl during closure.
for forbidden in (
    "ContractV2Service", "ServiceEconomyService", "ContractRecoveryService",
    'app_commands.Group(name="megbizasok"', '@app_commands.command(name="megbizasok"',
):
    forbid(service + board + character + main, forbidden, "parallel/new player contract surface")

print("W14.5 CONTRACT NATIVE/RESTART/EXPIRY HARDENING REGRESSION PASS")
