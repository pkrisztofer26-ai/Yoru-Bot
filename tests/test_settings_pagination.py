from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "app" / "cogs" / "settings.py"


class SettingsPaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SETTINGS.read_text(encoding="utf-8")

    def test_native_channel_and_role_select_removed_from_settings(self) -> None:
        # Native entity selects can show an incomplete list on larger guilds.
        # Settings uses explicit 23-item pages + previous/next instead.
        self.assertNotIn("discord.ui.ChannelSelect", self.source)
        self.assertNotIn("discord.ui.RoleSelect", self.source)

    def test_page_sizes_leave_room_for_navigation(self) -> None:
        channel_match = re.search(r"CHANNEL_SELECT_PAGE_SIZE\s*=\s*(\d+)", self.source)
        role_match = re.search(r"ROLE_SELECT_PAGE_SIZE\s*=\s*(\d+)", self.source)
        self.assertIsNotNone(channel_match)
        self.assertIsNotNone(role_match)
        self.assertLessEqual(int(channel_match.group(1)), 23)
        self.assertLessEqual(int(role_match.group(1)), 23)

    def test_all_channel_pickers_use_paged_selector(self) -> None:
        expected = [
            "ExemptionChannelSelect",
            "ExemptionCategorySelect",
            "LogChannelSelect",
            "SetupLogChannelSelect",
            "SetupPartnerSelect",
            "SetupTicketCategorySelect",
            "WelcomeChannelSelect",
            "GoodbyeChannelSelect",
            "RolePanelChannelSelect",
            "VerificationChannelSelect",
            "CommunitySuggestionChannelSelect",
            "CommunityStarboardChannelSelect",
        ]
        for class_name in expected:
            with self.subTest(class_name=class_name):
                self.assertIn(f"class {class_name}(PagedGuildChannelSelect):", self.source)

    def test_all_role_pickers_use_paged_selector(self) -> None:
        expected = [
            "ExemptionRoleSelect",
            "SetupStaffRoleSelect",
            "AutoroleHumanSelect",
            "AutoroleBotSelect",
            "RolePanelRoleSelect",
            "VerificationGiveRoleSelect",
            "VerificationRemoveRoleSelect",
        ]
        for class_name in expected:
            with self.subTest(class_name=class_name):
                self.assertIn(f"class {class_name}(PagedGuildRoleSelect):", self.source)

    def test_pagination_has_both_directions(self) -> None:
        self.assertIn('value=CHANNEL_NAV_PREV', self.source)
        self.assertIn('value=CHANNEL_NAV_NEXT', self.source)
        self.assertIn('value=ROLE_NAV_PREV', self.source)
        self.assertIn('value=ROLE_NAV_NEXT', self.source)


if __name__ == "__main__":
    unittest.main()
