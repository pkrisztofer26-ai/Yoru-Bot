from __future__ import annotations
from app.database_support import *

class DatabaseMixin6:
        async def _ensure_heist_rp_schema(self, db: aiosqlite.Connection) -> None:
            """Install additive RP Nagy Meló state that legacy Heist tables lacked."""
            await aiosqlite.execute_backend_ddl(db, sqlite_sql='\n                CREATE TABLE IF NOT EXISTS heist_vehicle_choices (\n                    guild_id INTEGER NOT NULL,\n                    lobby_id INTEGER NOT NULL,\n                    user_id INTEGER NOT NULL,\n                    vehicle_id INTEGER NOT NULL,\n                    updated_at TEXT NOT NULL,\n                    PRIMARY KEY (guild_id, lobby_id, user_id)\n                )\n            ', mysql_sql='\n                CREATE TABLE IF NOT EXISTS heist_vehicle_choices (\n                    guild_id BIGINT UNSIGNED NOT NULL,\n                    lobby_id BIGINT UNSIGNED NOT NULL,\n                    user_id BIGINT UNSIGNED NOT NULL,\n                    vehicle_id BIGINT UNSIGNED NOT NULL,\n                    updated_at VARCHAR(64) NOT NULL,\n                    PRIMARY KEY (guild_id, lobby_id, user_id),\n                    KEY idx_heist_vehicle_user (guild_id, user_id, updated_at)\n                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci\n            ')
            if not aiosqlite.using_mysql():
                await db.execute('CREATE INDEX IF NOT EXISTS idx_heist_vehicle_user ON heist_vehicle_choices(guild_id,user_id,updated_at)')

        async def _validate_mysql_cutover(self, db: aiosqlite.Connection) -> None:
            """Refuse to run against an empty or partially migrated MySQL DB."""
            if not aiosqlite.using_mysql():
                return
            try:
                cursor = await db.execute("SELECT meta_key,meta_value FROM `_yoru_migration_meta` WHERE meta_key IN ('schema_version','status')")
                rows = await cursor.fetchall()
            except Exception as exc:
                raise RuntimeError('A MySQL adatbázis nincs kész a Yoru indítására. Állítsd le a botot, készíts MySQL backupot, majd futtasd a MySQL schema/verifier ellenőrzést.') from exc
            meta = {str(row[0]): str(row[1]) for row in rows}
            if meta.get('schema_version') != 'db1' or meta.get('status') != 'verified':
                raise RuntimeError('A MySQL migráció nincs hitelesítve (DB-1 marker hiányos). A production SQLite fallback megszűnt; javítsd vagy állítsd vissza a MySQL adatbázist backupból.')

        async def _migrate_v355_balance_defaults(self, db: aiosqlite.Connection) -> None:
            """Apply the v3.55 baseline once without overwriting real custom tuning.

            Guild settings are authoritative at runtime. Older releases may have
            persisted the then-current factory defaults into ``guild_state``; in
            that case changing only the Python fallback would leave a guild on the
            old 6k–25k economy. We therefore update only values that are *exactly*
            equal to a known v3.54 factory default, once per guild. Any custom
            value remains untouched.
            """
            marker = 'economy_balance_baseline_v355'
            cursor = await db.execute('SELECT DISTINCT guild_id FROM users UNION SELECT DISTINCT guild_id FROM guild_state')
            guild_ids = [int(row[0]) for row in await cursor.fetchall()]
            replacements = (('economy_starting_balance', '25000', '75000'), ('economy_cooldown_work_seconds', '300', '480'), ('economy_reward_work_min', '6000', '50000'), ('economy_reward_work_max', '25000', '120000'), ('economy_reward_crime_reward_min', '20000', '180000'), ('economy_reward_crime_reward_max', '95000', '480000'), ('economy_reward_crime_fine_min', '45000', '140000'), ('economy_reward_crime_fine_max', '140000', '380000'), ('economy_reward_slut_reward_min', '18000', '90000'), ('economy_reward_slut_reward_max', '85000', '260000'), ('economy_reward_slut_fine_min', '35000', '80000'), ('economy_reward_slut_fine_max', '100000', '220000'), ('economy_crime_jail_chance', '0.45', '0.35'), ('economy_crime_jail_max_minutes', '15', '12'), ('economy_slut_success_chance', '0.56', '0.6'), ('economy_rob_fail_fine_min', '15000', '60000'), ('economy_rob_fail_fine_max', '80000', '250000'), ('economy_rob_min_attempt_wallet', '25000', '100000'), ('economy_rob_min_victim_wallet', '50000', '250000'), ('jobs_cooldown_seconds', '7200', '1800'), ('jobs_abandon_cooldown_seconds', '900', '600'), ('business_license_price', '15000000', '5000000'))
            for guild_id in guild_ids:
                cur = await db.execute('SELECT `value` FROM guild_state WHERE guild_id=? AND `key`=?', (guild_id, marker))
                if await cur.fetchone() is not None:
                    continue
                for key, old_value, new_value in replacements:
                    await db.execute('UPDATE guild_state SET `value`=? WHERE guild_id=? AND `key`=? AND `value`=?', (new_value, guild_id, key, old_value))
                await db.execute('INSERT OR IGNORE INTO guild_state (guild_id,`key`,`value`) VALUES (?,?,?)', (guild_id, marker, '1'))

