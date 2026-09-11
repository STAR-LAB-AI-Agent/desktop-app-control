"""组装默认工具集。"""

from __future__ import annotations

import pyautogui

from ..vision import DeepSeekVisionLocator
from ..logging import TaskLogStore
from .applications import ApplicationTools
from .base import ToolRegistry
from .files import FileTools
from .keyboard import KeyboardTools
from .monitor import ToolExecutionMonitor
from .mouse import MouseTools
from .system import SystemTools


class DesktopToolbox:
    def __init__(
        self,
        locator: DeepSeekVisionLocator,
        *,
        min_confidence: float = 0.75,
        action_pause: float = 0.3,
        logs: TaskLogStore | None = None,
        max_atomic_operations: int = 50,
        tool_call_limits: dict[str, int] | None = None,
        observation_delay: float = 0.6,
        grid_rows: int = 8,
        grid_columns: int = 8,
    ) -> None:
        self.locator = locator
        self.min_confidence = min_confidence
        self.action_pause = action_pause
        self.monitor = ToolExecutionMonitor(
            logs=logs,
            max_atomic_operations=max_atomic_operations,
            tool_call_limits=tool_call_limits or {},
            observation_delay=observation_delay,
        )
        self.grid_rows = grid_rows
        self.grid_columns = grid_columns
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = action_pause

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry(self.monitor)
        groups = (
            ApplicationTools(cancel_check=self.monitor.raise_if_cancelled),
            MouseTools(
                self.locator,
                self.min_confidence,
                grid_rows=self.grid_rows,
                grid_columns=self.grid_columns,
                artifact_writer=self.monitor.save_artifact,
            ),
            KeyboardTools(),
            FileTools(),
            SystemTools(cancel_check=self.monitor.raise_if_cancelled),
        )
        for group in groups:
            registry.register_many(group.specs())
        return registry

    # 保留旧方法名，避免现有调用立即失效。
    def registry(self) -> ToolRegistry:
        return self.build_registry()
