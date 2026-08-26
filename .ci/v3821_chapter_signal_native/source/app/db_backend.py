from __future__ import annotations

"""CI-only aiosqlite-shaped adapter for the W21.2 MariaDB proof."""

import asyncio
import os
from typing import Any
import mysql.connector


class Cursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    @property
    def lastrowid(self) -> int | None:
        value = self._cursor.lastrowid
        return None if value is None else int(value)

    async def fetchone(self):
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self):
        return await asyncio.to_thread(self._cursor.fetchall)


class Connection:
    def __init__(self) -> None:
        self._conn = None

    async def __aenter__(self):
        self._conn = await asyncio.to_thread(
            mysql.connector.connect,
            host=os.environ["MYSQL_HOST"], port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
            database=os.environ["MYSQL_DATABASE"], autocommit=False,
            ssl_disabled=os.getenv("MYSQL_SSL_DISABLED", "true").lower() in {"1", "true", "yes"},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
        return False

    @staticmethod
    def _sql(sql: str) -> str:
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            return "START TRANSACTION"
        return sql.replace("?", "%s")

    async def execute(self, sql: str, params=()) -> Cursor:
        cursor = await asyncio.to_thread(self._conn.cursor)
        await asyncio.to_thread(cursor.execute, self._sql(sql), tuple(params))
        return Cursor(cursor)

    async def commit(self) -> None:
        await asyncio.to_thread(self._conn.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._conn.rollback)


def connect(_path: str) -> Connection:
    return Connection()
