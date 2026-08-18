from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from pathlib import Path

from mysql.connector.aio import connect as mysql_async_connect

HERE = Path(__file__).resolve().parent
SCHEMA_B64 = HERE / "w10_contract_schema.b64"
SCHEMA_SHA256 = "d845d5636fd8d05d07a14242dba3e8b374b2697ee184be7c8166c4c128997763"


def mysql_kwargs() -> dict:
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.environ["MYSQL_DATABASE"],
        "autocommit": False,
        "charset": "utf8mb4",
        "connection_timeout": 10,
        "use_pure": True,
        "ssl_disabled": True,
    }


async def bootstrap_contract_schema() -> None:
    raw = base64.b64decode(SCHEMA_B64.read_text(encoding="ascii"))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != SCHEMA_SHA256:
        raise RuntimeError(f"W10 DB-1 contract schema SHA mismatch: {actual}")
    sql = raw.decode("utf-8")
    statements = [item.strip() for item in sql.split(";") if item.strip()]

    conn = await mysql_async_connect(**mysql_kwargs())
    try:
        cur = await conn.cursor()
        try:
            for statement in statements:
                await cur.execute(statement)
            # Market contracts use the real Database methods, but production
            # normally seeds this catalogue during startup. Seed only the one
            # catalogue row required by this isolated transaction fixture.
            await cur.execute(
                """INSERT INTO shop_items
                   (item_id,name,description,price,emoji,active,rarity,category)
                   VALUES ('silver','Ezüst','W10 transaction fixture',0,'🥈',1,'common','market')
                   ON DUPLICATE KEY UPDATE active=1"""
            )
            await conn.commit()
        finally:
            await cur.close()
    finally:
        await conn.close()


def install_initialize_bypass(module) -> None:
    original_extract = module.extract_and_verify_source

    def extract_then_patch():
        work = original_extract()
        from app.database import Database

        async def _w10_schema_already_prepared(self) -> None:
            return None

        Database.initialize = _w10_schema_already_prepared
        return work

    module.extract_and_verify_source = extract_then_patch


def main() -> int:
    # W10 is a transaction-contract gate, not the complete migration-schema
    # gate. The fixture is an exact subset generated from the frozen DB-1
    # cutover schema, including the unique/FK/index constraints relevant to
    # the tested money paths. Actual v3.72 Database/db_backend code is used for
    # every transaction below.
    asyncio.run(bootstrap_contract_schema())
    import w10_transaction_contracts

    install_initialize_bypass(w10_transaction_contracts)
    return w10_transaction_contracts.main()


if __name__ == "__main__":
    raise SystemExit(main())
