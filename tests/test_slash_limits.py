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


def _manual_group_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for item in node.body:
        if not isinstance(item, (ast.Assign, ast.AnnAssign)):
            continue
        value = item.value
        if not isinstance(value, ast.Call):
            continue
        fn = value.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "Group" and isinstance(fn.value, ast.Name) and fn.value.id == "app_commands"):
            continue
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name): names.add(target.id)
        elif isinstance(item.target, ast.Name):
            names.add(item.target.id)
    return names


def _is_manual_group_command(dec: ast.expr, group_names: set[str]) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if not (isinstance(target, ast.Attribute) and target.attr == "command"):
        return None
    owner = target.value
    if isinstance(owner, ast.Name) and owner.id in group_names:
        return owner.id
    return None


def scan() -> tuple[int, dict[str, int]]:
    top_level = 0
    groups: dict[str, int] = {}
    for path in sorted(COGS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            manual_groups = _manual_group_names(node)
            manual_counts = {name: 0 for name in manual_groups}
            child_commands = 0
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(_is_app_command_decorator(dec) for dec in item.decorator_list):
                    child_commands += 1
                for dec in item.decorator_list:
                    group_name = _is_manual_group_command(dec, manual_groups)
                    if group_name is not None:
                        manual_counts[group_name] += 1
            if _is_group_cog(node) and child_commands:
                top_level += 1
                groups[f"{path.name}:{node.name}"] = child_commands
            else:
                top_level += child_commands
            for group_name, count in manual_counts.items():
                # A manually declared app_commands.Group itself is one top-level command.
                top_level += 1
                groups[f"{path.name}:{node.name}.{group_name}"] = count

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

    def test_application_command_option_limits(self) -> None:
        for path in sorted(COGS.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not any(_is_app_command_decorator(dec) for dec in node.decorator_list):
                    continue
                positional = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args] if arg.arg not in {"self", "interaction"}]
                keyword_only = [arg.arg for arg in node.args.kwonlyargs]
                count = len(positional) + len(keyword_only)
                self.assertLessEqual(count, 25, f"Slash command option limit exceeded: {path.name}:{node.name} -> {count}/25")


if __name__ == "__main__":
    unittest.main()
