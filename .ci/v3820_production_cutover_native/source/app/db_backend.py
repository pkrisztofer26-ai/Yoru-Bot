from __future__ import annotations

"""CI-only MariaDB adapter for the W21.1 production cutover proof.

This is NOT production source. It intentionally exposes only the small
aiosqlite-shaped surface used by ChapterService and the native gate.
"""

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
            host=os.environ["MYSQL_HOST"],
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.environ["MYSQL_USER"],
            password=os.environ["MYSQL_PASSWORD"],
            database=os.environ["MYSQL_DATABASE"],
            autocommit=False,
            connection_timeout=int(os.getenv("MYSQL_CONNECT_TIMEOUT_SECONDS", "10")),
            ssl_disabled=os.getenv("MYSQL_SSL_DISABLED", "true").lower() in {"1", "true", "yes", "on"},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
        self._conn = None
        return False

    @staticmethod
    def _sql(sql: str) -> str:
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            return "START TRANSACTION"
        return sql.replace("?", "%s")

    async def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Cursor:
        assert self._conn is not None
        cursor = await asyncio.to_thread(self._conn.cursor)
        try:
            await asyncio.to_thread(cursor.execute, self._sql(sql), tuple(params))
        except Exception:
            await asyncio.to_thread(cursor.close)
            raise
        return Cursor(cursor)

    async def commit(self) -> None:
        assert self._conn is not None
        await asyncio.to_thread(self._conn.commit)

    async def rollback(self) -> None:
        assert self._conn is not None
        await asyncio.to_thread(self._conn.rollback)


def connect(_path: str) -> Connection:
    return Connection()
