"""兼容 `python main.py` 的启动入口。"""

import os
from pathlib import Path

from desktop_agent import AgentConfig
from desktop_agent.cli import main as run_cli


# 可以在本地填入精确值。提交或分享代码前请清空，避免泄露密钥。
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


# True：审核通过后不再询问，直接执行。硬性安全检查仍然保留。
FULL_TRUST = False


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash-vision-exp"
MIN_CONFIDENCE = 0.75
MAX_STEPS = 40
MAX_ATOMIC_OPERATIONS = 50
ACTION_PAUSE = 0.3
OBSERVATION_DELAY = 0.6
PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
SKILLS_DIR = PROJECT_ROOT / "skills"
GRID_ROWS = 8
GRID_COLUMNS = 8
TOOL_CALL_LIMITS = {
    "open_app_via_windows_search": 6,
    "click_target": 8,
    "double_click_target": 6,
    "assert_visible": 10,
    "type_text": 8,
    "submit_search_query": 12,
    "press_key": 12,
    "hotkey": 8,
    "scroll": 10,
    "wait": 10,
    "sleep": 12,
    "inspect_chatgpt_translation_state": 12,
    "find_desktop_file": 3,
}


def build_agent_config() -> AgentConfig:
    """命令行和桌面悬浮窗共用同一份本机配置。"""
    return AgentConfig(
        api_key=API_KEY or None,
        api_url=API_URL,
        model=MODEL,
        full_trust=FULL_TRUST,
        min_confidence=MIN_CONFIDENCE,
        max_steps=MAX_STEPS,
        max_atomic_operations=MAX_ATOMIC_OPERATIONS,
        action_pause=ACTION_PAUSE,
        observation_delay=OBSERVATION_DELAY,
        logs_dir=LOGS_DIR,
        skills_dir=SKILLS_DIR,
        grid_rows=GRID_ROWS,
        grid_columns=GRID_COLUMNS,
        tool_call_limits=TOOL_CALL_LIMITS,
    )


if __name__ == "__main__":
    raise SystemExit(run_cli(build_agent_config()))
