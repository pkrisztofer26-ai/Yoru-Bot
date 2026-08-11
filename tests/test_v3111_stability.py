from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V3111StabilityTests(unittest.TestCase):
    def test_multi_economy_channels_and_categories_backend(self) -> None:
        text = (ROOT / "app" / "services" / "economy_events_settings.py").read_text(encoding="utf-8")
        self.assertIn('ECONOMY_CHANNELS_KEY = "economy_allowed_channel_ids"', text)
        self.assertIn('ECONOMY_CATEGORIES_KEY = "economy_allowed_category_ids"', text)
        self.assertIn("get_economy_channel_ids", text)
        self.assertIn("get_economy_category_ids", text)
        self.assertIn("clear_economy_locations", text)
        self.assertIn("category_id", text)
        self.assertIn('legacy = await self.state.get_int(guild_id, "economy_channel_id")', text)

    def test_multi_location_settings_ui_uses_paginated_selectors(self) -> None:
        text = (ROOT / "app" / "cogs" / "economy_events_settings.py").read_text(encoding="utf-8")
        self.assertIn("class EconomyLocationsView", text)
        self.assertIn('selection_key="economy_channels_toggle"', text)
        self.assertIn('selection_key="economy_categories_toggle"', text)
        self.assertIn("discord.ChannelType.category", text)
        self.assertIn('label="Helyek"', text)

    def test_quest_assignments_are_created_before_first_relevant_stat_change(self) -> None:
        text = (ROOT / "app" / "services" / "statistics.py").read_text(encoding="utf-8")
        self.assertIn("_ensure_quest_assignments_before_stat_change", text)
        add_pos = text.index("await self._ensure_quest_assignments_before_stat_change")
        mutate_pos = text.index("return await self.db.add_user_stat", add_pos)
        self.assertLess(add_pos, mutate_pos)
        self.assertIn("get_quest_assignments", text)
        self.assertIn("create_quest_assignment", text)
        self.assertIn('random.Random(f"yoru:{guild_id}:{user_id}:{period}:{key}")', text)

    def test_chicken_is_consumed_on_loss_and_shop_text_updated(self) -> None:
        service = (ROOT / "app" / "services" / "extras.py").read_text(encoding="utf-8")
        database = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        self.assertIn('consume_item(guild_id, user_id, "chicken", 1)', service)
        self.assertIn('"chicken.deaths"', service)
        self.assertIn("Vereségnél a Chicken meghal és elvész", database)
        self.assertNotIn("Nem fogy el játék közben", database)

    def test_fun_user_commands_only_keep_ship(self) -> None:
        path = ROOT / "app" / "cogs" / "fun.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        slash_names: list[str] = []
        prefix_names: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                if dec.func.attr == "command" and isinstance(dec.func.value, ast.Name):
                    if dec.func.value.id == "app_commands":
                        name = next((kw.value.value for kw in dec.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)), node.name)
                        slash_names.append(str(name))
                    elif dec.func.value.id == "commands":
                        name = next((kw.value.value for kw in dec.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)), node.name)
                        prefix_names.append(str(name))
        self.assertEqual(slash_names, ["ship"])
        self.assertEqual(prefix_names, ["ship"])

    def test_ship_still_uses_both_profile_pictures_after_redesign(self) -> None:
        text = (ROOT / "app" / "cogs" / "fun.py").read_text(encoding="utf-8")
        self.assertIn("first.display_avatar", text)
        self.assertIn("second.display_avatar", text)
        self.assertIn("_stable_percent", text)
        self.assertIn("_ship_score", text)
        self.assertIn("_ship_card_file", text)

    def test_roadmap_is_packaged(self) -> None:
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("Frakció 2.0", roadmap)
        self.assertIn("Biznisz Empire", roadmap)
        self.assertIn("Hungary", roadmap)
        self.assertIn("Heist / Nagy Meló", roadmap)


if __name__ == "__main__":
    unittest.main()
