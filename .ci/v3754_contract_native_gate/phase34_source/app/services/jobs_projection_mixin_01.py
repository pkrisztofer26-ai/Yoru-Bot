from __future__ import annotations
from .jobs_projection_support import *

class JobsServiceProjectionMixin01:

    def __init__(self, db, economy, statistics, characters: CharacterService | None=None, training: TrainingService | None=None, world=None, vehicles: VehicleService | None=None, housing: HousingService | None=None, scenarios: ScenarioEngine | None=None, memory_adapters: MemoryAdapterService | None=None) -> None:
        self.db = db
        self.economy = economy
        self.stats = statistics
        self.characters = characters
        self.training = training
        self.world = world
        self.vehicles = vehicles
        self.housing = housing
        self.scenarios = scenarios
        self.memory_adapters = memory_adapters
        self.settings = ServerSettingsService(db)
        self.gameplay = GameplaySettingsService(db)
        if self.scenarios is not None:
            self._register_career_scenarios()

    @staticmethod
    def _career_family(job: str) -> str:
        return f'career_{job}'

    def _register_career_scenarios(self) -> None:
        if self.scenarios is None:
            return
        for job, pool in CAREER_SCENARIOS.items():
            family = self._career_family(job)
            for scenario in pool:
                if self.scenarios.registry.maybe_get(family, scenario.key) is not None:
                    continue
                self.scenarios.registry.register(definition_from_legacy(scenario, family=family, domain='career', tags=('career', f'job_{job}'), metadata={'job': job, 'pilot_active': True}))
        for job, pool in TRANSPORT_SCENARIOS.items():
            family = f'transport_{job}'
            for scenario in pool:
                if self.scenarios.registry.maybe_get(family, scenario.key) is not None:
                    continue
                self.scenarios.registry.register(definition_from_legacy(scenario, family=family, domain='career', tags=('career', 'transport', f'job_{job}'), metadata={'job': job, 'catalog_only': True}))
        for scenario in BORSOD_SCENARIOS:
            family = 'crime_borsod'
            if self.scenarios.registry.maybe_get(family, scenario.key) is not None:
                continue
            self.scenarios.registry.register(definition_from_legacy(scenario, family=family, domain='crime', tags=('crime', 'borsod'), metadata={'job': 'borsod', 'catalog_only': True}))

    async def is_enabled(self, guild_id: int) -> bool:
        return await self.settings.get_bool(guild_id, cfg.JOBS_ENABLED_KEY, True)

    async def job_enabled(self, guild_id: int, job: str) -> bool:
        if job not in cfg.JOB_BY_KEY:
            return False
        return await self.settings.get_bool(guild_id, f'{cfg.JOB_ENABLED_PREFIX}{job}', True)

    async def current_city_key(self, guild_id: int, user_id: int) -> str | None:
        if self.characters is None:
            return None
        character = await self.characters.require(guild_id, user_id)
        return character.current_city_key

    async def employment(self, guild_id: int, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db.path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute('SELECT guild_id,user_id,career_key,city_key,hired_at,updated_at FROM career_employment WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def _career_requirement_reason(self, guild_id: int, user_id: int, career_key: str) -> str | None:
        definition = cfg.career(career_key)
        if not await self.job_enabled(guild_id, definition.key):
            return 'Ez az állás ezen a szerveren jelenleg nem fogad műszakot.'
        city_key = await self.current_city_key(guild_id, user_id)
        if city_key is None:
            return 'A karaktered jelenlegi városa nem állapítható meg.'
        if city_key not in definition.cities:
            return 'Ebben a városban ez az állás jelenleg nem elérhető.'
        if definition.qualification_key and self.training is not None:
            if not await self.training.has_qualification(guild_id, user_id, definition.qualification_key):
                return f"Szükséges: {definition.qualification_name or 'megfelelő képesítés'}."
        if definition.min_housing_tier and self.housing is not None:
            state = await self.housing.get(guild_id, user_id)
            try:
                current_index = housing_cfg.PROGRESSION_ORDER.index(str(state.tier_key))
                required_index = housing_cfg.PROGRESSION_ORDER.index(str(definition.min_housing_tier))
            except ValueError:
                current_index, required_index = (0, 1)
            if current_index < required_index:
                return f'Ehhez az álláshoz legalább {housing_cfg.tier_name(definition.min_housing_tier)} szükséges.'
        if definition.vehicle_role and self.vehicles is not None:
            usable = await self.vehicles.job_vehicles(guild_id, user_id, city_key, definition.vehicle_role)
            if not usable:
                if definition.vehicle_role == 'taxi':
                    return 'Szükséges egy vezethető, helyben lévő saját személyautó.'
                return 'Szükséges egy vezethető, helyben lévő saját jármű.'
        return None

    async def hire(self, guild_id: int, user_id: int, career_key: str) -> dict:
        definition = cfg.career(career_key)
        if not await self.is_enabled(guild_id):
            raise ValueError('A munkarendszer ezen a szerveren ki van kapcsolva.')
        reason = await self._career_requirement_reason(guild_id, user_id, definition.key)
        if reason:
            raise ValueError(reason)
        city_key = await self.current_city_key(guild_id, user_id)
        if city_key is None:
            raise ValueError('A karaktered jelenlegi városa nem állapítható meg.')
        now = _now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            current = await (await conn.execute('SELECT career_key,city_key FROM career_employment WHERE guild_id=? AND user_id=?', (guild_id, user_id))).fetchone()
            if current is not None:
                await conn.rollback()
                current_def = cfg.CAREER_BY_KEY.get(str(current[0]))
                label = current_def.name if current_def else str(current[0])
                raise ValueError(f'Már van aktív állásod: {label}. Előbb mondj fel, ha váltani szeretnél.')
            await conn.execute('INSERT INTO career_employment(guild_id,user_id,career_key,city_key,hired_at,updated_at) VALUES(?,?,?,?,?,?)', (guild_id, user_id, definition.key, city_key, now, now))
            await conn.commit()
        history_event_id: int | None = None
        if self.characters is not None:
            try:
                history_event_id = await self.characters.add_history(guild_id, user_id, event_key='career_hired', title=f'Munkába álltál: {definition.name}', description=f'{definition.employer} alkalmazottjaként kezdtél dolgozni.', metadata={'career': definition.key, 'city': city_key})
            except Exception:
                log.exception('Career history write failed guild=%s user=%s career=%s', guild_id, user_id, definition.key)
        await self.stats.increment(guild_id, user_id, 'career.hires')
        if self.memory_adapters is not None:
            try:
                await self.memory_adapters.career_hired(guild_id, user_id, career_key=definition.key, city_key=city_key, hired_at=now, source_history_event_id=history_event_id)
            except Exception:
                log.exception('Career hire memory failed guild=%s user=%s career=%s', guild_id, user_id, definition.key)
        result = await self.employment(guild_id, user_id)
        if result is None:
            raise RuntimeError('Az állás mentése sikertelen volt.')
        return result

    async def quit_employment(self, guild_id: int, user_id: int) -> dict:
        active = await self.active_session(guild_id, user_id)
        if active is not None:
            raise ValueError('Aktív műszak közben nem mondhatsz fel. Előbb fejezd be vagy hagyd félbe a műszakot.')
        now = _now()
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            row = await (await conn.execute('SELECT career_key,city_key,hired_at FROM career_employment WHERE guild_id=? AND user_id=?', (guild_id, user_id))).fetchone()
            if row is None:
                await conn.rollback()
                raise ValueError('Jelenleg nincs aktív állásod.')
            active_now = await (await conn.execute("SELECT 1 FROM job_sessions WHERE guild_id=? AND user_id=? AND status='active' LIMIT 1", (guild_id, user_id))).fetchone()
            if active_now is not None:
                await conn.rollback()
                raise ValueError('Aktív műszak közben nem mondhatsz fel. Előbb fejezd be vagy hagyd félbe a műszakot.')
            await conn.execute('INSERT INTO career_history(guild_id,user_id,career_key,city_key,hired_at,ended_at,reason) VALUES(?,?,?,?,?,?,?)', (guild_id, user_id, str(row[0]), str(row[1]), str(row[2]), now, 'quit'))
            await conn.execute('DELETE FROM career_employment WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            await conn.commit()
        definition = cfg.CAREER_BY_KEY.get(str(row[0]))
        history_event_id: int | None = None
        if self.characters is not None:
            try:
                history_event_id = await self.characters.add_history(guild_id, user_id, event_key='career_quit', title=f'Felmondtál: {(definition.name if definition else row[0])}', description='Lezártad az aktuális munkaviszonyodat.', metadata={'career': str(row[0]), 'city': str(row[1])})
            except Exception:
                log.exception('Career quit history write failed guild=%s user=%s', guild_id, user_id)
        await self.stats.increment(guild_id, user_id, 'career.quits')
        if self.memory_adapters is not None:
            try:
                await self.memory_adapters.career_quit(guild_id, user_id, career_key=str(row[0]), city_key=str(row[1]), hired_at=str(row[2]), ended_at=now, source_history_event_id=history_event_id)
            except Exception:
                log.exception('Career quit memory failed guild=%s user=%s career=%s', guild_id, user_id, row[0])
        return {'career_key': str(row[0]), 'city_key': str(row[1]), 'hired_at': str(row[2]), 'ended_at': now}
