from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "app" / "cogs"
# Discord's hard top-level application command limit is 100. Yoru keeps 10 slots
# in reserve so a feature cannot silently push production over the limit.
PROJECT_TOP_LEVEL_BUDGET = 90
DISCORD_GROUP_CHILD_LIMIT = 25


def _is_app_command_decorator(dec: ast.expr) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "command"
        and isinstance(target.value, ast.Name)
        and target.value.id == "app_commands"
    )


def _is_group_cog(node: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Attribute) and base.attr == "GroupCog")
        or (isinstance(base, ast.Name) and base.id == "GroupCog")
        for base in node.bases
    )


def scan() -> tuple[int, dict[str, int]]:
    top_level = 0
    groups: dict[str, int] = {}
    for path in sorted(COGS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            child_commands = 0
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any(_is_app_command_decorator(dec) for dec in item.decorator_list):
                        child_commands += 1
            if _is_group_cog(node) and child_commands:
                top_level += 1
                groups[f"{path.name}:{node.name}"] = child_commands
            else:
                top_level += child_commands

    # app/main.py currently has the standalone /ping command registered through bot.tree.command.
    main_tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(main_tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute) or dec.func.attr != "command":
                continue
            owner = dec.func.value
            if isinstance(owner, ast.Attribute) and owner.attr == "tree":
                top_level += 1
    return top_level, groups


class SlashLimitTests(unittest.TestCase):
    def test_top_level_budget(self) -> None:
        top_level, _ = scan()
        self.assertLessEqual(
            top_level,
            PROJECT_TOP_LEVEL_BUDGET,
            f"Yoru top-level slash command budget exceeded: {top_level}/{PROJECT_TOP_LEVEL_BUDGET}. Use GroupCog/subcommands.",
        )

    def test_group_child_limits(self) -> None:
        _, groups = scan()
        for name, count in groups.items():
            self.assertLessEqual(count, DISCORD_GROUP_CHILD_LIMIT, f"Slash group full: {name} -> {count}/25")


if __name__ == "__main__":
    unittest.main()
