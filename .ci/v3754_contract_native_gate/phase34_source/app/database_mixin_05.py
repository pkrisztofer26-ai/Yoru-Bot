from __future__ import annotations
from app.database_support import *

class DatabaseMixin5:

    async def _ensure_contract_economy_schema(self, db: aiosqlite.Connection) -> None:
        """Install Phase 4 Unified Contract Economy foundation state.

            Existing business/PvP/marketplace/crew primitives are deliberately not
            migrated here. These tables are the source-of-truth only for new
            canonical contract rows.
            """
        await self._ensure_contract_economy_schema_part_1(db)
        await self._ensure_contract_economy_schema_part_2(db)
        await self._ensure_contract_economy_schema_part_3(db)
        await self._ensure_contract_economy_schema_part_4(db)
