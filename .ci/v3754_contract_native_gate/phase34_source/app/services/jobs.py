# STATIC_CONTRACT: career_hired
# STATIC_CONTRACT: self.memory_adapters.career_hired
# STATIC_CONTRACT: career_quit
# STATIC_CONTRACT: self.memory_adapters.career_quit
from __future__ import annotations
from .jobs_projection_support import *
from .jobs_projection_mixin_01 import JobsServiceProjectionMixin01
from .jobs_projection_mixin_02 import JobsServiceProjectionMixin02

class JobsService(JobsServiceProjectionMixin01, JobsServiceProjectionMixin02):
    pass
