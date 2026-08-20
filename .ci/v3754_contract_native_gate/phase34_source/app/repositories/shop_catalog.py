from __future__ import annotations

"""Read-only persistence boundary for the canonical Yoru item catalog.

The player-facing shop rules remain in :mod:`app.shop_config` and
:mod:`app.services.shop`.  This repository owns only read access to the
``shop_items`` projection used by inventory/social/community integrations.
"""

from app import db_backend


class ShopCatalogRepository:
    """Narrow read-only access to active ``shop_items`` rows."""

    def __init__(self, path: str) -> None:
        self.path = path

    async def list_items(self) -> list[tuple[str, str, str, int, str]]:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT item_id,name,description,price,emoji FROM shop_items "
                "WHERE active=1 ORDER BY price ASC"
            )
            rows = await cursor.fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), int(r[3]), str(r[4])) for r in rows]

    async def list_items_detailed(self) -> list[tuple[str, str, str, int, str, str, str]]:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT item_id,name,description,price,emoji,rarity,category FROM shop_items "
                "WHERE active=1 ORDER BY category,price ASC"
            )
            rows = await cursor.fetchall()
        return [
            (str(r[0]), str(r[1]), str(r[2]), int(r[3]), str(r[4]), str(r[5]), str(r[6]))
            for r in rows
        ]

    async def get_item(self, item_id: str) -> tuple[str, str, int, str, str] | None:
        async with db_backend.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT name,emoji,price,rarity,category FROM shop_items WHERE item_id=? AND active=1",
                (str(item_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4])
