from __future__ import annotations

from app.database_mixin_01 import DatabaseMixin01
from app.database_mixin_02 import DatabaseMixin02
from app.database_mixin_03 import DatabaseMixin03
from app.database_mixin_04 import DatabaseMixin04
from app.database_mixin_05 import DatabaseMixin05
from app.database_mixin_06 import DatabaseMixin06
from app.database_mixin_07 import DatabaseMixin07
from app.database_mixin_08 import DatabaseMixin08
from app.database_mixin_09 import DatabaseMixin09
from app.database_mixin_10 import DatabaseMixin10


class Database(
    DatabaseMixin01,
    DatabaseMixin02,
    DatabaseMixin03,
    DatabaseMixin04,
    DatabaseMixin05,
    DatabaseMixin06,
    DatabaseMixin07,
    DatabaseMixin08,
    DatabaseMixin09,
    DatabaseMixin10,
):
    pass
