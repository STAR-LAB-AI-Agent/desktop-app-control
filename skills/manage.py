"""统一查看、校验和配置项目内的技能。"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
from typing import Any


SKILLS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SKILLS_ROOT.parent
CONFIG_PATH = SKILLS_ROOT / "config.json"


def _configure_utf8_console() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleCP(65001)
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except (AttributeError, OSError):
            pass
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"version": 1, "skills": {}}
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("skills/config.json 必须使用 version=1")
    if not isinstance(value.get("skills"), dict):
        raise ValueError("skills/config.json 中的 skills 必须是 JSON 对象")
    return value


def _save_config(config: dict[str, Any]) -> None:
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(CONFIG_PATH)


def _skill_directories() -> dict[str, Path]:
    return {
        path.parent.name: path.parent
        for path in sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    }


def _require_skill(name: str) -> None:
    if name not in _skill_directories():
        raise ValueError(f"不存在技能目录：{name}")


def list_skills() -> int:
    config = _load_config()
    settings = config["skills"]
    print(f"{'技能名称':<32} {'启用':<6} {'优先级':<8} 路径")
    for name, directory in _skill_directories().items():
        item = settings.get(name, {})
        enabled = item.get("enabled", True)
        priority = item.get("priority", 0)
        enabled_text = "是" if enabled else "否"
        print(f"{name:<32} {enabled_text:<6} {priority:<8} {directory}")
    return 0


def check_skills() -> int:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from desktop_agent.skills import SkillRegistry

    registry = SkillRegistry(SKILLS_ROOT)
    registry.discover()
    registry.build_tool_specs(python_executable=sys.executable)
    print(f"技能配置有效，已启用：{', '.join(registry.names()) or '无'}")
    return 0


def update_skill(name: str, *, enabled: bool | None = None, priority: int | None = None) -> int:
    _require_skill(name)
    if priority is not None and not -1000 <= priority <= 1000:
        raise ValueError("优先级必须在 -1000 到 1000 之间")
    config = _load_config()
    item = config["skills"].setdefault(name, {})
    if enabled is not None:
        item["enabled"] = enabled
    if priority is not None:
        item["priority"] = priority
    item.setdefault("enabled", True)
    item.setdefault("priority", 0)
    _save_config(config)
    print(f"已更新技能 {name}：enabled={item['enabled']}, priority={item['priority']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一管理项目技能")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出全部技能及配置")
    commands.add_parser("check", help="校验配置、技能和脚本清单")
    for command, help_text in (("enable", "启用技能"), ("disable", "禁用技能")):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("name", help="技能目录名称")
    priority = commands.add_parser("priority", help="设置路由优先级")
    priority.add_argument("name", help="技能目录名称")
    priority.add_argument("value", type=int, help="-1000 到 1000 的整数")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            return list_skills()
        if args.command == "check":
            return check_skills()
        if args.command == "enable":
            return update_skill(args.name, enabled=True)
        if args.command == "disable":
            return update_skill(args.name, enabled=False)
        if args.command == "priority":
            return update_skill(args.name, priority=args.value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"技能管理失败：{exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
