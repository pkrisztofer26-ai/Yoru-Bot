from __future__ import annotations

SCENARIO_V2_ENABLED_KEY = "scenario_v2"

# Selection guards are deliberately conservative in the foundation release.
RECENT_KEY_GUARD = 5
RECENT_TOPIC_GUARD = 3

# Scenario run state survives process restarts for long enough that the player
# can reopen the job panel and continue an interrupted generic Career shift.
DEFAULT_RUN_TTL_SECONDS = 30 * 60
