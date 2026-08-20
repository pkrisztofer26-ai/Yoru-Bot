from __future__ import annotations
from app.database_support import *

class DatabaseMixin5Part4:

    async def _ensure_contract_economy_schema_part_4(self, db: aiosqlite.Connection) -> None:
        await aiosqlite.execute_backend_ddl(db, sqlite_sql='\n                CREATE TABLE IF NOT EXISTS business_delivery_history (\n                    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    guild_id INTEGER NOT NULL,\n                    property_id INTEGER NOT NULL,\n                    provider_user_id INTEGER NOT NULL,\n                    item_id TEXT NOT NULL,\n                    quantity INTEGER NOT NULL,\n                    source_ref TEXT NOT NULL,\n                    created_at TEXT NOT NULL,\n                    UNIQUE(guild_id,source_ref)\n                )\n            ', mysql_sql='\n                CREATE TABLE IF NOT EXISTS business_delivery_history (\n                    delivery_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,\n                    guild_id BIGINT UNSIGNED NOT NULL,\n                    property_id BIGINT UNSIGNED NOT NULL,\n                    provider_user_id BIGINT UNSIGNED NOT NULL,\n                    item_id VARCHAR(64) NOT NULL,\n                    quantity DECIMAL(65,0) NOT NULL,\n                    source_ref VARCHAR(190) NOT NULL,\n                    created_at VARCHAR(64) NOT NULL,\n                    PRIMARY KEY (delivery_id),\n                    UNIQUE KEY uq_business_delivery_source (guild_id,source_ref),\n                    KEY idx_business_delivery_property (guild_id,property_id,delivery_id)\n                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci\n            ')
        if not aiosqlite.using_mysql():
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contracts_active ON contracts(guild_id,status,expires_at)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contracts_assignee ON contracts(guild_id,assignee_id,status,contract_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contracts_creator ON contracts(guild_id,creator_id,status,contract_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contract_objectives_active ON contract_objectives(guild_id,contract_id,status,objective_type,target_ref)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contract_events_contract ON contract_events(guild_id,contract_id,event_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contract_history_contract ON contract_history(guild_id,contract_id,history_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contract_event_claim_contract ON contract_event_claims(guild_id,contract_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_item_transfer_users ON item_transfer_history(guild_id,sender_id,receiver_id,transfer_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contract_telemetry_type ON contract_telemetry(guild_id,event_type,created_at)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_contract_telemetry_contract ON contract_telemetry(guild_id,contract_id,telemetry_id)')
