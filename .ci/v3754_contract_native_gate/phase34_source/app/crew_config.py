from __future__ import annotations

from app import economy_config as eco

CREW_CREATE_COST = eco.CREW_CREATE_COST
CREW_INVITE_HOURS = 24
CREW_CREATE_COST_KEY = "crew_create_cost"
CREW_INVITE_HOURS_KEY = "crew_invite_hours"
CREW_MAX_LEVEL = 5
CREW_UPGRADE_COSTS = dict(eco.CREW_UPGRADE_COSTS)
CREW_MEMBER_CAPS: dict[int, int] = {1: 5, 2: 8, 3: 12, 4: 18, 5: 25}


def member_cap(level: int) -> int:
    return CREW_MEMBER_CAPS.get(max(1, min(CREW_MAX_LEVEL, int(level))), CREW_MEMBER_CAPS[1])


def upgrade_cost(level: int) -> int | None:
    return CREW_UPGRADE_COSTS.get(int(level))
