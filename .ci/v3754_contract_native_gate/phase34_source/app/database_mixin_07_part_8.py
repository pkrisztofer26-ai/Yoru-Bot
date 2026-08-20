from __future__ import annotations
from app.database_support import *

class DatabaseMixin7Part8:

    async def _initialize_part_8(self, db) -> None:
        await self._ensure_character_foundation_schema(db)
        await self._ensure_career_v2_schema(db)
        await self._ensure_vehicle_foundation_schema(db)
        await self._ensure_housing_foundation_schema(db)
        await self._ensure_training_foundation_schema(db)
        await self._ensure_police_foundation_schema(db)
        await self._ensure_world_foundation_schema(db)
        await self._ensure_memory_opportunity_schema(db)
        await self._ensure_contract_economy_schema(db)
        await self._ensure_heist_rp_schema(db)
        await self._migrate_v355_balance_defaults(db)
        await db.execute('PRAGMA optimize')
        await db.commit()
