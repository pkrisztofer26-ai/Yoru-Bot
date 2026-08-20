from __future__ import annotations
from .world_projection_support import *

class RPWorldServiceProjectionMixin01:

    async def opportunities(self, guild_id: int, user_id: int, *, character, housing, qualifications, vehicles, police, active_training=None, business_count: int=0, has_business_license: bool=False, business_license_price: int=0, business_world_note: str | None=None, organization_member: bool=False, organization_name: str | None=None, organization_status: str | None=None, street_cooldowns: dict[str, datetime | None] | None=None, employment_key: str | None=None) -> tuple[WorldSnapshot, list[Opportunity]]:
        snapshot = await self.ensure_current(guild_id)
        current_city = str(character.current_city_key)
        local = snapshot.city_situation(current_city)
        national = snapshot.national
        qualification_keys = {str(item.qualification_key) for item in qualifications}
        has_b = 'driving_b' in qualification_keys
        owned_vehicles = list(vehicles)
        wallet, bank = await self.database.get_balance(guild_id, user_id)
        liquid = max(0, int(wallet)) + max(0, int(bank))
        offers: list[Opportunity] = []
        street_cooldowns = street_cooldowns or {}
        if national.black_market_available:
            offers.append(Opportunity('world_black_market', '🌑', 'Ritkább áruk kerültek zárt körbe', 'A jelenlegi országos helyzet miatt megnyílt egy rövid ideig elérhető zárt piac. A kínálat készlethez kötött.', 'blackmarket', 88))
        if street_cooldowns.get('search') is None:
            search_desc = 'A környéken lomtalanítás és nagyobb mozgás van; érdemes átnézni néhány félreeső helyet.' if local.opportunity_jobs else 'Van pár hely a környéken, ahol néha pénz vagy használható holmi marad hátra.'
            offers.append(Opportunity('street_search', '🔎', 'Nézz körül a környéken', search_desc, 'street:search', 67))
        if str(housing.tier_key) in {'street', 'shelter'} and street_cooldowns.get('beg') is None:
            offers.append(Opportunity('street_beg', '🙏', 'Próbálj meg kisegítést kérni', 'Nem nagy pénz, de a jelenlegi helyzetedben megpróbálhatsz segítséget kérni a forgalmasabb részeken.', 'street:beg', 63))
        crackdown = national.illegal_attention_bonus > 0 or local.illegal_attention_bonus > 0
        if int(police.points) < 50 and (not crackdown) and (street_cooldowns.get('slut') is None):
            offers.append(Opportunity('street_oddjob', '🌙', 'Kétes esti munka akadt', 'Valaki gyors készpénzt ígér egy diszkrét esti munkáért. A részletek nem kerültek ki nyilvánosan.', 'street:oddjob', 54))
        if str(housing.tier_key) == 'street':
            offers.append(Opportunity('shelter', '🏠', 'Első cél: kerülj le az utcáról', f'{character_config.city_name(character.home_city_key)} területén már elérhető a szálló. A Lakhatás panelen pontosan látod a beköltözési és heti költséget.', 'housing', 100))
        elif str(housing.tier_key) == 'shelter':
            offers.append(Opportunity('rental', '🔑', 'Nézd meg az albérletet', 'A következő lakhatási lépcső az albérlet. A panel előre megmutatja az egyszeri beköltözési és az aktív heti díjat.', 'housing', 82))
        elif str(housing.tier_key) == 'rental':
            offers.append(Opportunity('owned_home', '🏠', 'Saját lakás lehet a következő nagy cél', 'Ha hosszabb távra rendezkednél be, a Lakhatás panelen már megveheted a városod saját lakását. Ez az ingatlan költözéskor is a tulajdonodban marad.', 'housing', 66))
        elif str(housing.tier_key) == 'owned':
            offers.append(Opportunity('premium_home', '🏡', 'Prémium ingatlanra válthatsz', 'A saját lakásodat prémium ingatlanná fejlesztheted. Több tárolóhelyet, garázst és ritkább személyes lehetőségeket nyit meg.', 'housing', 48))
        if active_training is not None:
            offers.append(Opportunity('training_active', '🎓', 'Folytasd a megkezdett képzést', 'Van folyamatban lévő képzésed. A folytatásért nem von le újra jelentkezési díjat.', 'training', 96))
        elif not has_b:
            offers.append(Opportunity('driving_b', '🪪', 'B kategóriás jogosítvány', 'A jogosítvány megnyitja a saját autós utazást és a taxis műszakot. A jelentkezési díjat a Képzések panel előre kiírja.', 'training', 72))
        if not owned_vehicles and liquid >= 2500000:
            offers.append(Opportunity('first_car', '🚗', 'Már érdemes körülnézned a járműpiacon', 'A jelenlegi vagyonoddal már elérhető lehet néhány olcsóbb használt jármű. A vételár egyszeri, automatikus járműdíj nincs.', 'vehicles', 58))
        if int(business_count) > 0:
            desc = business_world_note or 'A vállalkozásaid termelése fut tovább a háttérben; érdemes ránézni a felgyűlt bevételre és az aktuális helyzetre.'
            offers.append(Opportunity('business_existing', '🏢', 'Nézz rá a vállalkozásaidra', desc, 'business', 64))
        elif has_business_license:
            offers.append(Opportunity('business_market', '🏢', 'Megvan a vállalkozói engedélyed', 'Már beléphetsz az üzleti ingatlanpiacra. Új szabad ingatlant a jelenlegi városodban vehetsz; másik város kínálatához előbb oda kell utaznod.', 'business', 61))
        elif liquid >= max(1, int(business_license_price)) and (str(character.background_key) == 'business_family' or liquid >= 15000000):
            offers.append(Opportunity('business_entry', '💼', 'Megnyílt előtted a vállalkozói út', 'A jelenlegi vagyonoddal már reális lehet vállalkozásba kezdeni. A Vállalkozások panelen az engedély egyszeri árát előre látod.', 'business', 60))
        if organization_member:
            org_desc = f"A **{organization_name or 'Szervezeted'}** jelenleg {str(organization_status or 'aktív közösség').lower()}. Nézd meg a közös ügyeket, a városi jelenlétet és a Szervezet aktuális helyzetét."
            offers.append(Opportunity('organization_active', '🌙', 'Van közös ügy a Szervezeted körül', org_desc, 'organization', 57))
        boosted: list[str] = []
        for key in (*national.opportunity_jobs, *local.opportunity_jobs):
            if key not in boosted:
                boosted.append(key)
        active_job = str(employment_key or '')
        if active_job in jobs_config.LEGAL_JOB_KEYS:
            definition = jobs_config.JOB_BY_KEY[active_job]
            if active_job in boosted:
                labels = {'warehouse': ('📦', 'Raktári megbízások szaporodtak meg', 'A mostani helyzet miatt a munkahelyeden több feladat gyűlt össze.'), 'courier': ('🛵', 'Sürgős futárigény jelent meg', 'A városban több kézbesítés torlódott fel; a következő műszak mozgalmasabb lehet.'), 'taxi': ('🚕', 'Megugrott a taxiigény', 'A jelenlegi forgalmi helyzet miatt több utas keres fuvart.')}
                emoji, title, desc = labels.get(active_job, (definition.emoji, f'Mozgalmasabb lett a {definition.name.lower()} műszak', 'A jelenlegi világhelyzet a munkahelyeden is érezteti a hatását.'))
                offers.append(Opportunity(f'world_job_{active_job}', emoji, title, desc, f'job:{active_job}', 90))
            if not any((item.action_key == f'job:{active_job}' for item in offers)):
                offers.append(Opportunity('current_employment', definition.emoji, f'Műszak: {definition.name}', f'A jelenlegi munkahelyeden, {character_config.city_name(current_city)} területén rendes műszakot vállalhatsz.', f'job:{active_job}', 50))
        else:
            offers.append(Opportunity('career_search', '💼', 'Állást kereshetsz', 'Nincs aktív munkahelyed. Nézd meg, milyen belépő és szakmai állások érhetők el a jelenlegi városodban.', 'career', 52))
        local_heists = [target for target in heist_config.HEIST_TARGETS if target.city_key == current_city]
        if local_heists and int(police.points) < 70 and (liquid >= 10000000 or int(business_count) > 0):
            target = local_heists[0]
            offers.append(Opportunity('heist_local', '🎯', 'Komoly közös ügy körvonalazódik', f'{target.name} körül megjelent egy olyan lehetőség, amelyhez már csapatot kell összerakni és előre megállapodni a részesedésről.', 'heist', 45))
        if int(police.points) < 50 and (not crackdown):
            offers.append(Opportunity('street_opportunity', '🌑', 'Kétes utcai lehetőség', 'A környéken valaki gyors pénzért keres embert egy kétes ügyhöz. Részleteket csak személyesen mondanak.', 'crime:borsod', 38))
        elif crackdown:
            offers.append(Opportunity('police_pressure', '🚓', 'Most feltűnőbb az utcai mozgás', 'A jelenlegi rendőrségi helyzet miatt az illegális ügyek feltűnőbbek a környéken. Több járőr és ellenőrzés látszik az utcákon.', None, 42))
        if len(offers) < 5:
            for other_city in character_config.STARTING_CITY_KEYS:
                if other_city == current_city:
                    continue
                situation = snapshot.city_situation(other_city)
                if situation.opportunity_jobs:
                    offers.append(Opportunity(f'travel_{other_city}', '🧭', f'Mozgás van {character_config.city_name(other_city)} környékén', f'{situation.title}. Ha érdekel, az Utazás panelen előre látod az egyszeri útiköltséget.', 'travel', 28))
                    break
        if self.npc_followups is not None:
            try:
                offers.extend(await self.npc_followups.candidates(guild_id, user_id))
            except Exception:
                pass
        offers = await self.opportunity_resolver.resolve(guild_id, user_id, snapshot=snapshot, character=character, candidates=offers, limit=5)
        return (snapshot, offers)

    async def record_opportunity_selection(self, guild_id: int, user_id: int, *, opportunity_key: str, action_key: str | None, source_family: str | None=None) -> int:
        """Record a real player selection for pacing; opening the panel is not a choice."""
        snapshot = await self.ensure_current(guild_id)
        family = str(source_family or '').strip() or self.opportunity_resolver.source_family(Opportunity(str(opportunity_key), '', '', '', action_key, 0))
        return await self.opportunity_resolver.record_selection(guild_id, user_id, opportunity_key=opportunity_key, action_key=action_key, cycle_id=snapshot.cycle_id, source_family=family)

    async def record_opportunity_outcome(self, guild_id: int, user_id: int, *, opportunity_key: str, action_key: str | None, event_type: str, source_family: str | None=None) -> int:
        """Record a settled opportunity outcome without owning the settlement itself."""
        snapshot = await self.ensure_current(guild_id)
        family = str(source_family or '').strip() or self.opportunity_resolver.source_family(Opportunity(str(opportunity_key), '', '', '', action_key, 0))
        return await self.opportunity_resolver.record_event(guild_id, user_id, opportunity_key=opportunity_key, action_key=action_key, cycle_id=snapshot.cycle_id, source_family=family, event_type=event_type)
