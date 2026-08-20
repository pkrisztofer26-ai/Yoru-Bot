from __future__ import annotations
from app.database_support import *

class DatabaseMixin7:

    async def initialize(self) -> None:
        if not aiosqlite.using_mysql():
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await self._initialize_part_1(db)
            await self._initialize_part_2(db)
            await self._initialize_part_3(db)
            await self._initialize_part_4(db)
            await self._initialize_part_5(db)
            await self._initialize_part_6(db)
            await self._initialize_part_7(db)
            await self._initialize_part_8(db)
