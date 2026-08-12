from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import aiosqlite

ROOT = Path(__file__).resolve().parents[1]

from app.database import Database
from app.services.social_economy import SocialEconomyService


class CustomRoleBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db", 100_000)
        await self.db.initialize()
        self.social = SocialEconomyService(self.db)
        await self.social.initialize()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_custom_role_does_not_require_role_id(self) -> None:
        rid = await self.social.create_server_shop_item(
            1,
            name="Custom Role",
            description="buyer picks it",
            emoji="🎨",
            price=1_000,
            reward_type="custom_role",
            reward_ref="",
        )
        item = await self.social.get_server_shop_item(1, rid)
        self.assertIsNotNone(item)
        self.assertEqual(item["reward_type"], "custom_role")
        self.assertEqual(item["reward_ref"], "buyer_custom_role")
        self.assertEqual(int(item["duration_minutes"]), 0)

    async def test_temporary_custom_role_requires_duration_and_no_role_id(self) -> None:
        with self.assertRaises(ValueError):
            await self.social.create_server_shop_item(
                1,
                name="Temp Custom Role",
                description="",
                emoji="🎨",
                price=1_000,
                reward_type="temporary_custom_role",
                reward_ref="",
                duration_minutes=0,
            )
        rid = await self.social.create_server_shop_item(
            1,
            name="Temp Custom Role",
            description="",
            emoji="🎨",
            price=1_000,
            reward_type="temporary_custom_role",
            reward_ref="",
            duration_minutes=1440,
        )
        item = await self.social.get_server_shop_item(1, rid)
        self.assertEqual(item["reward_ref"], "buyer_custom_role")
        self.assertEqual(int(item["duration_minutes"]), 1440)

    async def test_temp_custom_role_grant_marks_delete_on_expire(self) -> None:
        await self.social.add_temporary_role_grant(1, 2, 3, 4, 60, delete_on_expire=True)
        async with aiosqlite.connect(self.db.path) as conn:
            cur = await conn.execute(
                "SELECT delete_on_expire FROM temporary_role_grants WHERE guild_id=1 AND user_id=2 AND role_id=3 AND source_purchase_id=4"
            )
            row = await cur.fetchone()
        self.assertEqual(int(row[0]), 1)


class CustomRoleSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.social = (ROOT / "app/cogs/social_economy.py").read_text(encoding="utf-8")
        cls.config = (ROOT / "app/social_config.py").read_text(encoding="utf-8")

    def test_custom_role_is_interactive_purchase(self) -> None:
        for token in (
            "class CustomRolePurchaseModal",
            'label="Role neve"',
            'label="Role színe (HEX, opcionális)"',
            'guild.create_role(',
            'delete_on_expire=True',
            'await role.delete(reason="Yoru temporary custom role lejárt")',
        ):
            self.assertIn(token, self.social)

    def test_new_reward_types_are_supported(self) -> None:
        self.assertIn('"custom_role"', self.config)
        self.assertIn('"temporary_custom_role"', self.config)
        self.assertIn('value="custom_role"', self.social)
        self.assertIn('value="temporary_custom_role"', self.social)

    def test_version_is_3132(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("."))), (3, 13, 2))


if __name__ == "__main__":
    unittest.main()
