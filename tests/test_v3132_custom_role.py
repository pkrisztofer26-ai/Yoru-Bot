from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import aiosqlite

from app.database import Database
from app.services.social_economy import SocialEconomyService
from app import social_config as cfg

ROOT = Path(__file__).resolve().parents[1]


class CustomRoleBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db", 1_000_000)
        await self.db.initialize()
        self.social = SocialEconomyService(self.db)
        await self.social.initialize()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_permanent_custom_role_needs_no_role_id(self) -> None:
        rid = await self.social.create_server_shop_item(
            1, name="Custom Role", description="", emoji="🎨", price=50_000,
            reward_type="custom_role", reward_ref="", duration_minutes=0,
        )
        item = await self.social.get_server_shop_item(1, rid)
        self.assertEqual(item["reward_type"], "custom_role")
        self.assertEqual(item["reward_ref"], "buyer_custom_role")
        self.assertEqual(int(item["duration_minutes"]), 0)

    async def test_temporary_custom_role_needs_no_role_id(self) -> None:
        rid = await self.social.create_server_shop_item(
            1, name="Temp Custom", description="", emoji="🎨", price=50_000,
            reward_type="temporary_custom_role", reward_ref="", duration_minutes=1440,
        )
        item = await self.social.get_server_shop_item(1, rid)
        self.assertEqual(item["reward_ref"], "buyer_custom_role")
        self.assertEqual(int(item["duration_minutes"]), 1440)

    async def test_temporary_custom_role_requires_duration(self) -> None:
        with self.assertRaises(ValueError):
            await self.social.create_server_shop_item(
                1, name="Temp Custom", description="", emoji="🎨", price=50_000,
                reward_type="temporary_custom_role", reward_ref="", duration_minutes=0,
            )

    async def test_custom_role_purchase_is_not_manual_claim(self) -> None:
        rid = await self.social.create_server_shop_item(
            1, name="Custom Role", description="", emoji="🎨", price=50_000,
            reward_type="custom_role", reward_ref="",
        )
        purchase = await self.social.begin_server_shop_purchase(1, 22, rid)
        self.assertIsNone(purchase["claim_id"])
        self.assertEqual(purchase["reward_type"], "custom_role")

    async def test_delete_on_expire_flag_roundtrips(self) -> None:
        await self.social.add_temporary_role_grant(1, 22, 333, 444, 1, delete_on_expire=True)
        async with aiosqlite.connect(self.db.path) as conn:
            await conn.execute("UPDATE temporary_role_grants SET expires_at='2000-01-01T00:00:00+00:00'")
            await conn.commit()
        rows = await self.social.expired_temporary_roles()
        self.assertEqual(rows[0][:4], (1, 22, 333, 444))
        self.assertTrue(rows[0][4])


class CustomRoleSourceTests(unittest.TestCase):
    def test_reward_types_are_enabled(self) -> None:
        self.assertIn("custom_role", cfg.SERVER_SHOP_REWARD_TYPES)
        self.assertIn("temporary_custom_role", cfg.SERVER_SHOP_REWARD_TYPES)

    def test_interactive_purchase_creates_role(self) -> None:
        src = (ROOT / "app/cogs/social_economy.py").read_text(encoding="utf-8")
        for token in (
            "class CustomRolePurchaseModal",
            "_validate_custom_role_name",
            "_parse_custom_role_color",
            "guild.create_role",
            "temporary_custom_role",
            "delete_on_expire=True",
        ):
            self.assertIn(token, src)

    def test_settings_custom_role_reward_id_is_optional(self) -> None:
        src = (ROOT / "app/cogs/social_economy.py").read_text(encoding="utf-8")
        self.assertIn('required=False, placeholder="Custom role-nál hagyd üresen"', src)
        self.assertIn('return "buyer_custom_role"', src)

    def test_old_database_gets_expiry_flag_migration(self) -> None:
        service = (ROOT / "app/services/social_economy.py").read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE temporary_role_grants ADD COLUMN delete_on_expire", service)

    def test_version_and_changelog(self) -> None:
        self.assertGreaterEqual(tuple(map(int, (ROOT / "VERSION").read_text().strip().split("."))), (3, 13, 2))
        self.assertTrue((ROOT / "CHANGELOG_3.13.2.txt").exists())


if __name__ == "__main__":
    unittest.main()
