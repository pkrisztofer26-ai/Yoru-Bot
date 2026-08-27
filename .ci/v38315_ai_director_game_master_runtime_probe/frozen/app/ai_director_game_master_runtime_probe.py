from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.ai_director_game_master import (
    big_job_packet,
    chapter_packet,
    consequence_recall_packet,
    legendary_event_packet,
    npc_story_packet,
    world_story_packet,
)
from app.ai_director_game_master_integration import add_game_master_field

VERSION = "3.83.15"
WORK_ITEM = "W22.7.1"
CONTRACT = "tier3-game-master-surface-v6"
EXPECTED_FAMILIES = frozenset({
    "big_job",
    "npc_story",
    "consequence_recall",
    "chapter",
    "world_story",
    "legendary_event",
})


def runtime_probe_packets():
    """Deterministic, non-authoritative packets used only by the live test-guild probe."""
    return (
        big_job_packet(
            target_name="Belvárosi trezor",
            phase_label="Lezárt ügy",
            approach_label="Csendes út",
            route_label="Eredeti útvonal",
            host_resolution="Siker",
            consequence_note="A csapat az eredeti útvonalon maradt.",
        ),
        npc_story_packet(
            npc_name="Mira",
            npc_role="informátor",
            relationship_band="Jó kapcsolat",
            recalled_event="Korábban információt adott.",
            current_story_state="Jó kapcsolat",
        ),
        consequence_recall_packet(
            subject_label="Korábbi ügy",
            memory_category="Élettörténet",
            remembered_event="A korábbi ügy lezárult.",
            current_relevance="A feljegyzés megmaradt az élettörténetben.",
        ),
        chapter_packet(
            chapter_title="Törésvonalak",
            stage_title="Utórezgések",
            world_story_title="Csendes közeledés",
            community_note="A közösségi projekt lezárult.",
            host_ending=None,
        ),
        world_story_packet(
            national_title="Feszült országos helyzet",
            story_title="Csendes közeledés",
            beat_title="Új kapcsolatok",
            city_label="Budapest",
            world_note="A történetszál új ponthoz ért.",
        ),
        legendary_event_packet(
            event_name="Éjféli Konvoj",
            access_context="Legendary meghívásból megnyílt ügy",
            phase_label="Lezárt művelet",
            host_resolution="Siker",
            legacy_note="A Legendary művelet lezárt ügyként szerepel.",
        ),
    )


@dataclass(frozen=True, slots=True)
class RuntimeProbeReport:
    status: str
    checks: dict[str, bool]
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "work_item": WORK_ITEM,
            "mode": "real_discord_test_guild_runtime_probe",
            "contract": CONTRACT,
            "status": self.status,
            "gameplay_authority": "NONE",
            "observation_persistence": "NONE",
            "production_rollout": "NO",
            "storyteller_pacing": "LOCKED",
            "checks": dict(self.checks),
            "metrics": dict(self.metrics),
        }


def evaluate_runtime_probe(metrics: dict[str, Any], *, policy_active: bool, host_panels_intact: bool) -> RuntimeProbeReport:
    family_requests = dict(metrics.get("family_requests") or {})
    checks = {
        "test_guild_policy_active": bool(policy_active),
        "all_six_families_observed": EXPECTED_FAMILIES.issubset(family_requests.keys()),
        "twelve_requests_observed": int(metrics.get("requests_total", 0)) == 12,
        "six_live_provider_attempts": int(metrics.get("provider_attempts", 0)) == 6,
        "six_live_ai_surfaces": int(metrics.get("ai_surfaces", 0)) == 6,
        "six_cache_hits": int(metrics.get("cache_hits", 0)) == 6,
        "twelve_fields_added": int(metrics.get("fields_added", 0)) == 12,
        "no_packet_rejections": int(metrics.get("packet_rejections", 0)) == 0,
        "no_provider_unavailable": int(metrics.get("provider_unavailable", 0)) == 0,
        "no_provider_failures": int(metrics.get("provider_failures", 0)) == 0,
        "no_provider_timeouts": int(metrics.get("provider_timeouts", 0)) == 0,
        "no_validation_failures": int(metrics.get("output_validation_failures", 0)) == 0,
        "no_deterministic_fallbacks": int(metrics.get("deterministic_fallbacks", 0)) == 0,
        "no_integration_failures": int(metrics.get("integration_failures", 0)) == 0,
        "host_panels_intact": bool(host_panels_intact),
    }
    return RuntimeProbeReport(
        status="GO" if all(checks.values()) else "HOLD",
        checks=checks,
        metrics=metrics,
    )


async def run_live_runtime_probe(
    bot: Any,
    guild_id: int,
    *,
    embed_factory: Callable[[str, int], Any],
) -> tuple[RuntimeProbeReport, list[Any]]:
    """Run one bounded live-network probe against the already-enabled test-guild pilot.

    The caller owns Discord transmission. This helper touches no persistence layer
    and never mutates gameplay state. It clears only the in-memory Tier-3 cache and
    observation counters so provider/cache counts are deterministic for the probe.
    """
    pilot = getattr(bot, "ai_director_game_master", None)
    policy_active = bool(pilot is not None and pilot.active_for_guild(guild_id))
    if not policy_active:
        metrics = pilot.observation_snapshot().as_dict() if pilot is not None else {}
        return evaluate_runtime_probe(metrics, policy_active=False, host_panels_intact=True), []

    pilot.reset_observation(clear_cache=True)
    first_pass_embeds: list[Any] = []
    host_panels_intact = True

    for pass_index in (1, 2):
        for packet in runtime_probe_packets():
            embed = embed_factory(packet.family, pass_index)
            before_fields = len(getattr(embed, "fields", ()))
            added = await add_game_master_field(bot, embed, guild_id, packet)
            after_fields = len(getattr(embed, "fields", ()))
            host_panels_intact = host_panels_intact and before_fields >= 1 and after_fields >= before_fields
            if not added:
                host_panels_intact = False
            if pass_index == 1:
                first_pass_embeds.append(embed)

    metrics = pilot.observation_snapshot().as_dict()
    return evaluate_runtime_probe(
        metrics,
        policy_active=policy_active,
        host_panels_intact=host_panels_intact,
    ), first_pass_embeds
