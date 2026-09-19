"""命令行启动、审核展示和人工审批。"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from dataclasses import replace
from pathlib import Path
import sys

from .agent import DesktopAgent
from .config import AgentConfig
from .escape import EscapeStopListener
from .task import ReviewDecision, TaskStatus


def _configure_utf8_console() -> None:
    """让 Windows 控制台和 Python 输出使用相同的 UTF-8 编码。"""
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


def _print_json(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _add_common_arguments(parser: argparse.ArgumentParser, config: AgentConfig) -> None:
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=config.min_confidence,
        help="视觉定位最低置信度",
    )
    parser.add_argument("--dry-run", action="store_true", help="只审核和展示计划")
    parser.add_argument("--yes", action="store_true", help="审核通过后自动批准")
    parser.add_argument(
        "--full-trust",
        action=argparse.BooleanOptionalAction,
        default=config.full_trust,
        help="跳过人工批准；硬性安全审核仍然保留",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=config.logs_dir,
        help="按任务保存 JSON、原子操作和截图的根目录",
    )
    parser.add_argument(
        "--max-operations",
        type=int,
        default=config.max_atomic_operations,
        help="单任务最大原子工具调用数",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="监听 127.0.0.1:5678 并等待调试器连接",
    )


def build_parser(config: AgentConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="视觉桌面 Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser(
        "search",
        help="兼容入口：将当前页面搜索交给通用工作流",
    )
    search.add_argument("query", help="搜索关键词")
    _add_common_arguments(search, config)

    general = subparsers.add_parser("run", help="由大模型路由并执行桌面任务")
    general.add_argument("task", help="自然语言任务描述")
    general.add_argument("--max-steps", type=int, default=config.max_steps)
    _add_common_arguments(general, config)
    return parser


def main(config: AgentConfig | None = None) -> int:
    _configure_utf8_console()
    defaults = config or AgentConfig()
    args = build_parser(defaults).parse_args()
    if args.debug:
        import debugpy

        debugpy.listen(("127.0.0.1", 5678))
        print("调试器正在监听 127.0.0.1:5678，等待连接……")
        debugpy.wait_for_client()

    run_config = replace(
        defaults,
        min_confidence=args.min_confidence,
        full_trust=args.full_trust,
        logs_dir=args.logs_dir,
        max_atomic_operations=args.max_operations,
        max_steps=getattr(args, "max_steps", defaults.max_steps),
    )
    agent = DesktopAgent(run_config)

    if args.command == "search":
        task = agent.create_search_task(args.query)
    elif args.command == "run":
        task = agent.create_general_task(args.task, max_steps=args.max_steps)
    else:
        return 2

    route = task.payload.get("skill_route")
    if isinstance(route, dict):
        print("\n任务路由：")
        _print_json(route)

    review = agent.review(task)
    print("\n任务审核：")
    _print_json(review.to_dict())

    if review.decision == ReviewDecision.REJECT:
        return 2
    if args.dry_run:
        return 0

    trusted = agent.config.full_trust
    approved = args.yes or trusted
    if trusted:
        print("\n完全信任模式：审核已通过，跳过人工确认。")
    elif not approved:
        answer = input("\n批准执行以上任务？[y/N] ").strip().lower()
        approved = answer in {"y", "yes"}

    # CLI 运行时没有 Tk 窗口可接收按键，使用全局 Esc 监听器将取消事件
    # 传给当前任务；按住 Esc 只触发一次，松开后再次按下可停止下一次任务。
    def stop_from_escape() -> None:
        if agent.cancel(task.id):
            print("\n检测到 Esc，正在强制停止任务……", flush=True)

    with EscapeStopListener(stop_from_escape):
        result = agent.execute(task.id, approved=approved)
    print("\n任务结果：")
    _print_json(result.to_dict())
    return 0 if result.status == TaskStatus.SUCCEEDED else 1
