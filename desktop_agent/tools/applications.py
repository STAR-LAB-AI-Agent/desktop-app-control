"""以确定性的键盘流程启动桌面应用。"""

from __future__ import annotations

import time
from typing import Any, Callable

import pyautogui

from .base import ToolSpec
from .keyboard import KeyboardTools


class ApplicationTools:
    """把会暴露中间 GUI 状态的应用搜索压缩成一个原子工具。"""

    def __init__(
        self,
        cancel_check: Callable[[], None] | None = None,
        *,
        search_delay: float = 0.4,
        launch_delay: float = 1.5,
    ) -> None:
        self.cancel_check = cancel_check
        self.search_delay = max(0.0, float(search_delay))
        self.launch_delay = max(0.0, float(launch_delay))

    def _check_cancelled(self) -> None:
        if self.cancel_check is not None:
            self.cancel_check()

    def _pause_interruptibly(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def open_app_via_windows_search(self, app_name: str) -> dict[str, Any]:
        if not isinstance(app_name, str):
            raise TypeError("app_name 必须是字符串")
        name = app_name.strip()
        if not name:
            raise ValueError("app_name 不能为空")
        if "\n" in name or "\r" in name:
            raise ValueError("app_name 必须是单行软件名称")
        if len(name) > 100:
            raise ValueError("app_name 不得超过 100 个字符")

        self._check_cancelled()
        pyautogui.hotkey("win", "s")
        self._pause_interruptibly(self.search_delay)

        # 不读取、不点击搜索历史或推荐项；覆盖可能残留的旧查询，只提交明确的软件名。
        pyautogui.hotkey("ctrl", "a")
        KeyboardTools.type_text(name)
        self._check_cancelled()
        pyautogui.press("enter")
        self._pause_interruptibly(self.launch_delay)

        return {
            "ok": True,
            "app_name": name,
            "method": "windows_search_keyboard",
            "ignored_search_history": True,
        }

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "open_app_via_windows_search",
                (
                    "通过一次原子键盘流程启动软件：Win+S、覆盖旧查询、输入软件名、按 Enter；"
                    "全程不点击搜索历史、推荐项或任务栏图标"
                ),
                {
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 100,
                            "description": "Windows 搜索使用的准确软件名",
                        }
                    },
                    "required": ["app_name"],
                    "additionalProperties": False,
                },
                self.open_app_via_windows_search,
            )
        ]
