from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def need(haystack: str, token: str, label: str) -> None:
    if token not in haystack:
        raise AssertionError(f"Missing {label}: {token}")


def main() -> None:
    version = text("VERSION").strip()
    try:
        version_line = tuple(int(part) for part in version.split(".")[:2])
    except ValueError:
        version_line = (0, 0)
    if version_line < (3, 74):
        raise AssertionError(f"VERSION must be on the v3.74+ regression line, got {version}")

    npc = text("app/npc_config.py")
    adapters = text("app/services/memory_adapters.py")
    opportunities = text("app/services/opportunities.py")
    notif_contract = text("app/services/notification_contracts.py")
    notif_cfg = text("app/notification_config.py")
    notif_service = text("app/services/notifications.py")
    jobs = text("app/services/jobs.py")
    training = text("app/services/training.py")
    world = text("app/services/world.py")
    world_view = text("app/cogs/character_views/world.py")
    main_text = text("app/main.py")

    for key in ("kata_job_agent", "misi_car_dealer", "jani_mechanic", "lilla_dispatcher"):
        need(npc, f'"{key}"', f"canonical NPC {key}")
    for role_key in ("business_contact", "black_market_broker", "legal_contact"):
        need(npc, f'"{role_key}"', f"baseline NPC role {role_key}")

    for preset in ("player_helped", "npc_helped", "agreement_kept", "agreement_broken", "betrayal", "rival_escalated", "rival_resolved"):
        need(adapters, f'"{preset}"', f"NPC consequence preset {preset}")
    need(adapters, "record_consequence", "canonical consequence writer")
    need(adapters, "career_hired", "career hire adapter")
    need(adapters, "career_quit", "career quit adapter")
    need(adapters, "training_completed", "training complete adapter")

    for token in ("subject_type", "subject_key", "required_memory_keys", "required_trust_bands", "required_relationship_flags"):
        need(opportunities, token, f"relationship opportunity contract {token}")
    need(opportunities, "memory.relationship(normalized_subject_type, normalized_subject_key)", "relationship-aware eligibility")
    need(opportunities, "memory.has(item)", "memory-aware eligibility")

    need(notif_cfg, '"relationship": ("🤝", "Kapcsolatok")', "relationship notification category")
    need(notif_cfg, '"opportunity": ("📌", "Lehetőségek")', "opportunity notification category")
    need(notif_contract, "self.notifications.notify(", "existing NotificationService delegation")
    if "NotificationRepository" in notif_contract:
        raise AssertionError("Notification contract must not create/use a second notification repository")
    need(notif_service, '"relationship": "life_panel"', "relationship action URL binding")
    need(notif_service, '"opportunity": "life_panel"', "opportunity action URL binding")

    need(jobs, "self.memory_adapters.career_hired", "career hire post-settlement memory hook")
    need(jobs, "self.memory_adapters.career_quit", "career quit post-settlement memory hook")
    need(training, "self.memory_adapters.training_completed", "training completion post-settlement memory hook")
    need(main_text, "self.memory_adapters = MemoryAdapterService(self.memory)", "shared memory adapter runtime")
    need(main_text, "GameplayNotificationContract(self.notifications)", "shared notification contract runtime")

    need(world, "source_family: str | None = None", "opportunity selection family preservation")
    need(world_view, "source_family=source_family", "view selection family handoff")

    combined = "\n".join((npc, adapters, opportunities, notif_contract))
    if "@app_commands" in combined or "@commands.command" in combined:
        raise AssertionError("W13.2 core must not add a new player command")
    if "trust_score" in world_view or "favor_owed_to_player" in world_view or "required_trust_bands" in world_view:
        raise AssertionError("Raw relationship internals leaked to Opportunity UI")

    print("W13.2 MEMORY_NPC_NOTIFICATION_GATE: PASS")
    print(f"version={version}")
    print("npc_registry=baseline 4 reviewed identities + expandable canonical roster")
    print("memory_adapters=career+training+npc semantic consequences")
    print("opportunity_relationship_contract=explicit only")
    print("notification_backend=existing NotificationService")
    print("player_commands_added=0")


if __name__ == "__main__":
    main()
