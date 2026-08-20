from __future__ import annotations
from .jobs_projection_support_career_a import CAREER_SCENARIOS_A
from .jobs_projection_support_career_b import CAREER_SCENARIOS_B
from .jobs_projection_support_career_c import CAREER_SCENARIOS_C

CAREER_SCENARIOS = {**CAREER_SCENARIOS_A, **CAREER_SCENARIOS_B, **CAREER_SCENARIOS_C}
CAREER_SCENARIOS['warehouse'] = ()
CAREER_SCENARIOS['courier'] = ()
CAREER_SCENARIOS['taxi'] = ()
