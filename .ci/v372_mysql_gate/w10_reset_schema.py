from __future__ import annotations

import asyncio
import os

from mysql.connector.aio import connect as mysql_async_connect


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


async def reset_schema() -> None:
    conn = await mysql_async_connect(**mysql_kwargs())
    try:
        cur = await conn.cursor()
        try:
            await cur.execute("SET FOREIGN_KEY_CHECKS=0")
            await cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
            rows = await cur.fetchall()
            for row in rows:
                table_name = str(row[0]).replace("`", "``")
                await cur.execute(f"DROP TABLE IF EXISTS `{table_name}`")
            await cur.execute("SET FOREIGN_KEY_CHECKS=1")
            await conn.commit()
        finally:
            await cur.close()
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(reset_schema())
