from __future__ import annotations
from .vehicles_projection_support import *

class VehicleServiceProjectionMixin03:

    @_serialized_vehicle_action
    async def repair_vehicle(self, guild_id: int, user_id: int, vehicle_id: int) -> VehicleRepairResult:
        await self.characters.require(guild_id, user_id)
        now_s = _iso()
        old_condition = ''
        next_condition = ''
        price = 0
        base_price = 0
        discount_saved = 0
        favor_effect_key: str | None = None
        issue_for_repair: str | None = None
        new_wallet = 0
        new_bank = 0
        repair_transaction_id = 0
        async with aiosqlite.connect(self.database.path) as db:
            await db.execute('BEGIN IMMEDIATE')
            try:
                char_cur = await db.execute("SELECT current_city_key FROM characters WHERE guild_id=? AND user_id=? AND status='active'", (guild_id, user_id))
                char_row = await char_cur.fetchone()
                if char_row is None:
                    raise ValueError('Még nincs aktív karaktered.')
                current_city = str(char_row[0])
                current_cur = await db.execute('SELECT cv.model_key,cv.condition_key,cv.city_key,cv.status,vs.issue_key,COALESCE(vs.issue_revealed,0)\n                       FROM character_vehicles cv\n                       LEFT JOIN vehicle_state vs ON vs.vehicle_id=cv.vehicle_id\n                       WHERE cv.vehicle_id=? AND cv.guild_id=? AND cv.user_id=?', (vehicle_id, guild_id, user_id))
                current_row = await current_cur.fetchone()
                if current_row is None or str(current_row[3]) != 'owned':
                    raise ValueError('Ez a jármű már nincs a tulajdonodban.')
                model_key = str(current_row[0])
                old_condition = str(current_row[1])
                if str(current_row[2]) != current_city:
                    raise ValueError('A jármű nincs veled ebben a városban, így most nem tudod szervizbe vinni.')
                issue_key = str(current_row[4]) if current_row[4] is not None else None
                issue_revealed = bool(int(current_row[5] or 0))
                issue_for_repair = issue_key if issue_revealed else None
                base_price = cfg.repair_price(model_key, old_condition, issue_for_repair)
                if base_price <= 0:
                    raise ValueError('A jármű jelenleg nem igényel javítást.')
                price = base_price
                favor_fact = None
                if self.memory is not None:
                    effect = npc_favor_config.effect('jani_repair_discount')
                    favor_fact = await self.memory.active_favor_effect_tx(db, guild_id, user_id, effect_key=effect.key, subject_key=effect.npc_key)
                    if favor_fact is not None:
                        discount_saved = effect.savings(base_price)
                        price = max(0, base_price - discount_saved)
                        favor_effect_key = effect.key
                next_condition = cfg.next_better_condition(old_condition) or old_condition
                balance_cur = await db.execute('SELECT wallet,bank FROM users WHERE guild_id=? AND user_id=?', (guild_id, user_id))
                balance_row = await balance_cur.fetchone()
                if balance_row is None:
                    raise RuntimeError('A Yoru egyenleged nem található.')
                wallet, bank = (int(balance_row[0]), int(balance_row[1]))
                if max(0, wallet) + max(0, bank) < price:
                    raise ValueError('Nincs elég pénzed a javításhoz.')
                wallet_used = min(max(0, wallet), price)
                bank_used = price - wallet_used
                new_wallet = wallet - wallet_used
                new_bank = bank - bank_used
                await db.execute('UPDATE users SET wallet=?,bank=?,money_lost=money_lost+? WHERE guild_id=? AND user_id=?', (new_wallet, new_bank, price, guild_id, user_id))
                tx_cur = await db.execute('INSERT INTO transactions(guild_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)', (guild_id, user_id, -price, f'vehicle_repair:{vehicle_id}', now_s))
                repair_transaction_id = int(tx_cur.lastrowid or 0)
                new_value = cfg.estimated_value(model_key, next_condition)
                await db.execute('UPDATE character_vehicles SET condition_key=?,estimated_value=?,updated_at=? WHERE vehicle_id=? AND guild_id=? AND user_id=?', (next_condition, new_value, now_s, vehicle_id, guild_id, user_id))
                await self._ensure_state(db, vehicle_id, guild_id, user_id)
                if issue_for_repair:
                    await db.execute('UPDATE vehicle_state SET issue_key=NULL,issue_revealed=0,last_service_at=?,updated_at=? WHERE vehicle_id=?', (now_s, now_s, vehicle_id))
                else:
                    await db.execute('UPDATE vehicle_state SET last_service_at=?,updated_at=? WHERE vehicle_id=?', (now_s, now_s, vehicle_id))
                if favor_fact is not None:
                    consumed = await self.memory.consume_active_favor_effect_tx(db, memory_id=favor_fact.memory_id)
                    if not consumed:
                        raise RuntimeError('A szervizkedvezmény közben már nem volt elérhető; a javítás nem kerülhetett félállapotba.')
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        refreshed = await self.get_vehicle(guild_id, user_id, vehicle_id)
        assert refreshed is not None
        if self.memory_adapters is not None:
            try:
                await self.memory_adapters.vehicle_repaired(guild_id, user_id, vehicle_id=vehicle_id, model_key=refreshed.model_key, old_condition_key=old_condition, new_condition_key=next_condition, paid=price, base_price=base_price, discount_saved=discount_saved, favor_effect_key=favor_effect_key, occurred_at=now_s)
            except Exception:
                self.log.exception('Vehicle repair memory adapter failed guild=%s user=%s vehicle=%s', guild_id, user_id, vehicle_id)
        if self.contracts is not None and repair_transaction_id > 0:
            try:
                await self.contracts.record_matching_domain_event(guild_id, user_id, event_key=f'vehicle_repair_tx:{repair_transaction_id}', event_type='vehicle_service_completed', target_ref='service:repair', payload={'transaction_id': repair_transaction_id, 'vehicle_id': int(vehicle_id), 'paid': int(price)})
            except Exception:
                self.log.exception('Vehicle repair contract hook failed guild=%s user=%s vehicle=%s', guild_id, user_id, vehicle_id)
        return VehicleRepairResult(refreshed, price, old_condition, next_condition, bool(issue_for_repair), new_wallet, new_bank, base_price=base_price, discount_saved=discount_saved, favor_effect_key=favor_effect_key)
