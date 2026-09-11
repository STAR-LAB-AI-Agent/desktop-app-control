"""工具调用计数、截图缓存和屏幕变化检测。"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pyautogui
from PIL import Image, ImageChops, ImageStat

from ..logging import TaskLogStore


class TaskCancelledError(RuntimeError):
    """用户主动终止了正在运行的任务。"""


class ToolExecutionMonitor:
    def __init__(
        self,
        *,
        logs: TaskLogStore | None,
        max_atomic_operations: int,
        tool_call_limits: dict[str, int],
        observation_delay: float,
        change_threshold: float = 0.004,
    ) -> None:
        self.logs = logs
        self.max_atomic_operations = max_atomic_operations
        self.tool_call_limits = dict(tool_call_limits)
        self.observation_delay = observation_delay
        self.change_threshold = change_threshold
        self.operation_count = 0
        self.tool_counts: Counter[str] = Counter()
        self.run_dir: Path | None = None
        self.task_id: str | None = None
        self.cancel_event: threading.Event | None = None

    def start_run(
        self,
        task_id: str,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.operation_count = 0
        self.tool_counts.clear()
        self.task_id = task_id
        self.run_dir = None if self.logs is None else self.logs.task_dir(task_id)
        self.cancel_event = cancel_event

    def execute(
        self,
        name: str,
        handler: Callable[..., dict[str, Any]],
        arguments: dict[str, Any],
        explanation: str,
    ) -> dict[str, Any]:
        self.raise_if_cancelled()
        if self.operation_count >= self.max_atomic_operations:
            raise RuntimeError(
                f"达到原子操作上限 {self.max_atomic_operations}，任务已停止"
            )
        limit = self.tool_call_limits.get(name)
        if limit is not None and self.tool_counts[name] >= limit:
            raise RuntimeError(f"工具 {name} 达到单任务调用上限 {limit}")

        before = pyautogui.screenshot()
        self.operation_count += 1
        self.tool_counts[name] += 1
        index = self.operation_count
        error: str | None = None
        result: dict[str, Any] = {}
        try:
            result = handler(**arguments)
            self.raise_if_cancelled()
            return result
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            if self.observation_delay:
                time.sleep(self.observation_delay)
            after = pyautogui.screenshot()
            change_score = _screen_change_score(before, after)
            image_path = self.save_artifact(after, f"{index:03d}_{name}_after")
            result_without_telemetry = dict(result)
            telemetry = {
                "operation": index,
                "tool_calls": self.tool_counts[name],
                "screen_changed": change_score >= self.change_threshold,
                "change_score": round(change_score, 6),
                "image": str(image_path) if image_path else None,
            }
            result["telemetry"] = telemetry
            self._record(
                {
                    "operation": index,
                    "tool": name,
                    "explanation": explanation,
                    "arguments": arguments,
                    "result": result_without_telemetry,
                    "telemetry": telemetry,
                    "error": error,
                }
            )

    def raise_if_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise TaskCancelledError("任务已由用户终止")

    def save_artifact(self, image: Image.Image, label: str) -> Path | None:
        if self.run_dir is None:
            return None
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
        if not re.match(r"^\d{3}_", safe_label):
            safe_label = f"{self.operation_count:03d}_{safe_label}"
        path = self.run_dir / "images" / f"{safe_label}.png"
        image.save(path)
        return path

    def stats(self) -> dict[str, Any]:
        return {
            "atomic_operations": self.operation_count,
            "max_atomic_operations": self.max_atomic_operations,
            "tool_calls": dict(self.tool_counts),
            "task_log_dir": str(self.run_dir) if self.run_dir else None,
        }

    def _record(self, value: dict[str, Any]) -> None:
        if self.logs is None or self.task_id is None:
            return
        self.logs.record_operation(self.task_id, value)


def _screen_change_score(before: Image.Image, after: Image.Image) -> float:
    size = (320, 180)
    before_small = before.convert("L").resize(size)
    after_small = after.convert("L").resize(size)
    difference = ImageChops.difference(before_small, after_small)
    mean_difference = ImageStat.Stat(difference).mean[0]
    return mean_difference / 255.0
