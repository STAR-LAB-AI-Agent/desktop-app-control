"""与具体应用无关的控制工具。"""

from __future__ import annotations

import time
from typing import Any, Callable

from .base import ToolSpec


class SystemTools:
    def __init__(self, cancel_check: Callable[[], None] | None = None) -> None:
        self.cancel_check = cancel_check

    def _sleep_interruptibly(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            if self.cancel_check is not None:
                self.cancel_check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.25, remaining))

    def wait(self, seconds: float) -> dict[str, Any]:
        actual = max(0, min(10, float(seconds)))
        self._sleep_interruptibly(actual)
        return {"ok": True, "seconds": actual}

    def sleep(self, seconds: float) -> dict[str, Any]:
        actual = max(0, min(120, float(seconds)))
        self._sleep_interruptibly(actual)
        return {"ok": True, "seconds": actual, "kind": "long_wait"}

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "wait",
                "等待界面加载，最长 10 秒",
                {
                    "type": "object",
                    "properties": {"seconds": {"type": "number"}},
                    "required": ["seconds"],
                    "additionalProperties": False,
                },
                self.wait,
            ),
            ToolSpec(
                "sleep",
                "等待耗时任务继续运行，适合生成、翻译等长任务，最长 120 秒；等待期间可被终止",
                {
                    "type": "object",
                    "properties": {
                        "seconds": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 120,
                        }
                    },
                    "required": ["seconds"],
                    "additionalProperties": False,
                },
                self.sleep,
            ),
        ]
