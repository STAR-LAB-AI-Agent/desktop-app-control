"""Agent 的集中配置。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .vision import DEFAULT_API_URL, DEFAULT_MODEL


@dataclass(frozen=True, slots=True)
class AgentConfig:
    api_key: str | None = None
    api_url: str = DEFAULT_API_URL
    model: str = DEFAULT_MODEL
    full_trust: bool = False
    min_confidence: float = 0.75
    max_steps: int = 40
    max_atomic_operations: int = 50
    action_pause: float = 0.3
    observation_delay: float = 0.6
    logs_dir: Path | None = Path("logs")
    skills_dir: Path = Path("skills")
    grid_rows: int = 8
    grid_columns: int = 8
    application_search_names: dict[str, str] = field(
        default_factory=lambda: {
            "浏览器": "Edge",
            "Microsoft Edge": "Edge",
            "音乐软件": "音乐",
            "音乐": "音乐",
            "翻译软件": "ChatGPT",
            "ChatGPT": "ChatGPT",
        }
    )
    tool_call_limits: dict[str, int] = field(
        default_factory=lambda: {
            "open_app_via_windows_search": 6,
            "click_target": 8,
            "double_click_target": 6,
            "assert_visible": 10,
            "type_text": 12,
            "submit_search_query": 12,
            "press_key": 12,
            "hotkey": 8,
            "scroll": 10,
            "wait": 10,
            "sleep": 12,
            "inspect_chatgpt_translation_state": 12,
            "find_desktop_file": 3,
        }
    )

    def __post_init__(self) -> None:
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence 必须在 0 到 1 之间")
        if not 1 <= self.max_steps <= 60:
            raise ValueError("max_steps 必须在 1 到 60 之间")
        if not 1 <= self.max_atomic_operations <= 100:
            raise ValueError("max_atomic_operations 必须在 1 到 100 之间")
        if not 0 <= self.action_pause <= 5:
            raise ValueError("action_pause 必须在 0 到 5 秒之间")
        if not 0 <= self.observation_delay <= 10:
            raise ValueError("observation_delay 必须在 0 到 10 秒之间")
        if not 2 <= self.grid_rows <= 20 or not 2 <= self.grid_columns <= 20:
            raise ValueError("网格行列数必须在 2 到 20 之间")
        if any(not key.strip() or not value.strip() for key, value in self.application_search_names.items()):
            raise ValueError("软件搜索名称的键和值不能为空")
        if any(limit < 1 for limit in self.tool_call_limits.values()):
            raise ValueError("每个工具的调用上限必须大于 0")
