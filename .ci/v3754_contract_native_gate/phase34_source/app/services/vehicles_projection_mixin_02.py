from __future__ import annotations
from .vehicles_projection_support import *

class VehicleServiceProjectionMixin02:

    async def _purchase_common(self, guild_id: int, user_id: int, *, model_key: str, condition_key: str, city_key: str, price: int, source: str, offer: MarketOffer | None=None, hidden_issue_key: str | None=None) -> VehiclePurchaseResult:
        now_s = _iso()
        vehicle_id = 0
        base_price = int(price)
        discount_saved = 0
        favor_effect_key: str | None = None
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            try:
                char_cur = await db.execute("SELECT current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'", (guild_id, user_id))
                char_row = await char_cur.fetchone()
                if char_row is None:
                    raise ValueError('Még nincs aktív karaktered.')
                current_city = str(char_row[0])
                if current_city != str(city_key):
                    raise ValueError('Ezt a járművet csak abban a városban tudod átvenni, ahol jelenleg tartózkodsz.')
                if offer is not None:
                    offer_cur = await db.execute('SELECT status,expires_at FROM vehicle_market_offers WHERE guild_id=? AND offer_id=?', (guild_id, offer.offer_id))
                    live = await offer_cur.fetchone()
                    if live is None or str(live[0]) != 'active' or str(live[1]) <= now_s:
                        raise ValueError('Ez a hirdetés már nem aktív. Nyisd meg újra a használtautó-piacot.')
                favor_fact = None
                if source == 'dealership' and self.memory is not None:
                    effect = npc_favor_config.effect('misi_dealership_discount')
                    favor_fact = await self.memory.active_favor_effect_tx(db, guild_id, user_id, effect_key=effect.key, subject_key=effect.npc_key)
                    if favor_fact is not None:
                        discount_saved = effect.savings(base_price)
                        price = max(0, base_price - discount_saved)
                        favor_effect_key = effect.key
                balance_cur = await db.execute('SELECT wallet,bank FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                balance_row = await balance_cur.fetchone()
                if balance_row is None:
                    raise RuntimeError('A Yoru egyenleged nem található.')
                wallet, bank = (int(balance_row[0]), int(balance_row[1]))
                wallet_available, bank_available = (max(0, wallet), max(0, bank))
                if wallet_available + bank_available < int(price):
                    raise ValueError('Nincs elég pénzed a tárcádban és a bankodban összesen ehhez a járműhöz.')
                wallet_used = min(wallet_available, int(price))
                bank_used = int(price) - wallet_used
                new_wallet = wallet - wallet_used
                new_bank = bank - bank_used
                await db.execute('UPDATE users SET wallet=?,bank=?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?', (new_wallet, new_bank, int(price), guild_id, user_id))
                await db.execute('INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)', (guild_id, user_id, -int(price), f'vehicle_purchase:{source}:{model_key}', now_s))
                value = cfg.estimated_value(model_key, condition_key)
                inserted = await db.execute("INSERT INTO character_vehicles(guild_id,user_id,model_key,condition_key,city_key,purchase_price,estimated_value,status,acquired_at,updated_at,sold_at)\n                       VALUES(?,?,?,?,?,?,?,'owned',?,?,NULL)", (guild_id, user_id, model_key, condition_key, current_city, int(price), value, now_s, now_s))
                vehicle_id = int(getattr(inserted, 'lastrowid', 0) or 0)
                if vehicle_id <= 0:
                    last_cur = await db.execute('SELECT last_insert_rowid()')
                    last_row = await last_cur.fetchone()
                    vehicle_id = int(last_row[0]) if last_row else 0
                await self._ensure_state(db, vehicle_id, guild_id, user_id, issue_key=hidden_issue_key)
                if offer is not None:
                    update_cur = await db.execute("UPDATE vehicle_market_offers SET status='sold',buyer_user_id=?,purchased_at=?\n                           WHERE guild_id=? AND offer_id=? AND status='active'", (user_id, now_s, guild_id, offer.offer_id))
                    if int(getattr(update_cur, 'rowcount', 0)) != 1:
                        raise ValueError('Ezt a járművet közben már megvették. A pénzed nem került levonásra.')
                owned_cur = await db.execute("SELECT COUNT(*) FROM character_vehicles WHERE guild_id=? AND user_id=? AND status='owned'", (guild_id, user_id))
                owned_count = int((await owned_cur.fetchone())[0])
                if owned_count == 1:
                    await db.execute('UPDATE vehicle_state SET is_primary=1,updated_at=? WHERE vehicle_id=?', (now_s, vehicle_id))
                history_cur = await db.execute("SELECT 1 FROM character_history WHERE guild_id=? AND user_id=? AND event_key='first_vehicle' LIMIT 1", (guild_id, user_id))
                if await history_cur.fetchone() is None:
                    model = cfg.model(model_key)
                    await db.execute("INSERT INTO character_history(guild_id,user_id,event_key,title,description,metadata_json,created_at)\n                           VALUES (?,?,'first_vehicle',?,?,?,?)", (guild_id, user_id, 'Első saját jármű', f'Megvetted az első saját járművedet: {model.name}, {character_cfg.city_name(current_city)} városában.', json.dumps({'vehicle_id': vehicle_id, 'model': model_key, 'city': current_city}, ensure_ascii=False, separators=(',', ':')), now_s))
                if favor_fact is not None:
                    consumed = await self.memory.consume_active_favor_effect_tx(db, memory_id=favor_fact.memory_id)
                    if not consumed:
                        raise RuntimeError('A járműkedvezmény közben már nem volt elérhető; a vásárlás nem kerülhetett félállapotba.')
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        vehicle = await self.get_vehicle(guild_id, user_id, vehicle_id)
        if vehicle is None:
            raise RuntimeError('A jármű megvásárlása sikerült, de a tulajdont nem sikerült visszaolvasni.')
        if self.memory_adapters is not None:
            try:
                await self.memory_adapters.vehicle_purchased(guild_id, user_id, vehicle_id=vehicle.vehicle_id, model_key=vehicle.model_key, source=source, paid=int(price), base_price=base_price, discount_saved=discount_saved, favor_effect_key=favor_effect_key, occurred_at=now_s)
            except Exception:
                self.log.exception('Vehicle purchase memory adapter failed guild=%s user=%s vehicle=%s', guild_id, user_id, vehicle.vehicle_id)
        return VehiclePurchaseResult(vehicle, offer, int(price), wallet_used, bank_used, new_wallet, new_bank, source, base_price=base_price, discount_saved=discount_saved, favor_effect_key=favor_effect_key)

    @_serialized_vehicle_action
    async def buy_dealership(self, guild_id: int, user_id: int, model_key: str) -> VehiclePurchaseResult:
        character = await self.characters.require(guild_id, user_id)
        if model_key not in cfg.VEHICLE_MODELS:
            raise ValueError('Ez a modell jelenleg nem rendelhető a kereskedésből.')
        return await self._purchase_common(guild_id, user_id, model_key=model_key, condition_key=cfg.DEALERSHIP_CONDITION_KEY, city_key=character.current_city_key, price=cfg.dealership_price(model_key), source='dealership', hidden_issue_key=None)

    async def repair_quote(self, guild_id: int, user_id: int, vehicle_id: int) -> int:
        vehicle = await self.get_vehicle(guild_id, user_id, vehicle_id)
        if vehicle is None:
            raise ValueError('Ez a jármű már nincs a tulajdonodban.')
        issue_for_quote = vehicle.issue_key if vehicle.issue_revealed else None
        base = cfg.repair_price(vehicle.model_key, vehicle.condition_key, issue_for_quote)
        if base > 0 and self.memory is not None:
            effect = npc_favor_config.effect('jani_repair_discount')
            voucher = await self.memory.active_favor_effect(guild_id, user_id, effect_key=effect.key, subject_key=effect.npc_key)
            if voucher is not None:
                return max(0, base - effect.savings(base))
        return base
