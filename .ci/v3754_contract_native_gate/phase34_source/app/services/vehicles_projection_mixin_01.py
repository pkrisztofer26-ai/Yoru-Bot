from __future__ import annotations
from .vehicles_projection_support import *

class VehicleServiceProjectionMixin01:

    def __init__(self, database: Database, characters: CharacterService, memory: ConsequenceMemoryService | None=None, memory_adapters: MemoryAdapterService | None=None) -> None:
        self.database = database
        self.characters = characters
        self.memory = memory
        self.memory_adapters = memory_adapters
        self.contracts = None
        self.log = logging.getLogger('vaultbot.vehicles')
        self._rng = random.SystemRandom()
        self._action_locks: KeyedLockPool[tuple[int, int]] = KeyedLockPool()

    def bind_contracts(self, contracts) -> None:
        self.contracts = contracts

    @staticmethod
    def _vehicle_from_row(row: Any) -> Vehicle:
        return Vehicle(vehicle_id=int(row[0]), guild_id=int(row[1]), user_id=int(row[2]), model_key=str(row[3]), condition_key=str(row[4]), city_key=str(row[5]), purchase_price=int(row[6]), estimated_value=int(row[7]), status=str(row[8]), acquired_at=str(row[9]), updated_at=str(row[10]), sold_at=str(row[11]) if row[11] is not None else None, is_primary=bool(int(row[12] or 0)) if len(row) > 12 else False, issue_key=str(row[13]) if len(row) > 13 and row[13] is not None else None, issue_revealed=bool(int(row[14] or 0)) if len(row) > 14 else False, last_service_at=str(row[15]) if len(row) > 15 and row[15] is not None else None)

    async def _ensure_state(self, db: aiosqlite.Connection, vehicle_id: int, guild_id: int, user_id: int, *, issue_key: str | None=None) -> None:
        now = _iso()
        await db.execute('INSERT INTO vehicle_state(vehicle_id,guild_id,user_id,is_primary,issue_key,issue_revealed,last_service_at,updated_at)\n               VALUES(?,?,?,0,?,0,NULL,?)\n               ON CONFLICT(vehicle_id) DO NOTHING', (int(vehicle_id), guild_id, user_id, issue_key, now))

    async def vehicles(self, guild_id: int, user_id: int) -> list[Vehicle]:
        await self.characters.require(guild_id, user_id)
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(self._VEHICLE_SELECT + " WHERE cv.guild_id=? AND cv.user_id=? AND cv.status='owned' ORDER BY COALESCE(vs.is_primary,0) DESC,cv.acquired_at,cv.vehicle_id", (guild_id, user_id))
            rows = await cursor.fetchall()
        items = [self._vehicle_from_row(row) for row in rows]
        if len(items) == 1 and (not items[0].is_primary):
            items[0] = await self.set_primary(guild_id, user_id, items[0].vehicle_id)
        return items

    async def get_vehicle(self, guild_id: int, user_id: int, vehicle_id: int) -> Vehicle | None:
        async with aiosqlite.connect(self.database.path) as db:
            cursor = await db.execute(self._VEHICLE_SELECT + " WHERE cv.guild_id=? AND cv.user_id=? AND cv.vehicle_id=? AND cv.status='owned'", (guild_id, user_id, int(vehicle_id)))
            row = await cursor.fetchone()
        return self._vehicle_from_row(row) if row is not None else None

    @_serialized_vehicle_action
    async def set_primary(self, guild_id: int, user_id: int, vehicle_id: int) -> Vehicle:
        vehicle = await self.get_vehicle(guild_id, user_id, vehicle_id)
        if vehicle is None:
            raise ValueError('Ez a jármű már nincs a tulajdonodban.')
        now = _iso()
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            try:
                await self._ensure_state(db, vehicle.vehicle_id, guild_id, user_id)
                await db.execute('UPDATE vehicle_state SET is_primary=0,updated_at=? WHERE guild_id=? AND user_id=?', (now, guild_id, user_id))
                await db.execute('UPDATE vehicle_state SET is_primary=1,updated_at=? WHERE vehicle_id=? AND guild_id=? AND user_id=?', (now, vehicle.vehicle_id, guild_id, user_id))
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        refreshed = await self.get_vehicle(guild_id, user_id, vehicle.vehicle_id)
        assert refreshed is not None
        return refreshed
