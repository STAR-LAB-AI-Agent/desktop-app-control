"""鼠标、滚动和视觉确认工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pyautogui

from ..vision import DeepSeekVisionLocator
from .base import RecoverableToolError, ToolSpec
from .grid import add_grid
from .monitor import _screen_change_score


STALE_SCREEN_THRESHOLD = 0.018


class MouseTools:
    def __init__(
        self,
        locator: DeepSeekVisionLocator,
        min_confidence: float,
        *,
        grid_rows: int = 10,
        grid_columns: int = 10,
        artifact_writer: Callable[[Any, str], Path | None] | None = None,
    ) -> None:
        self.locator = locator
        self.min_confidence = min_confidence
        self.grid_rows = grid_rows
        self.grid_columns = grid_columns
        self.artifact_writer = artifact_writer

    def _locate_safely(self, image, target: str):
        try:
            return self.locator.locate(image, target)
        except (ValueError, KeyError, TypeError) as exc:
            raise RecoverableToolError(
                f"定位结果格式或坐标无效，本次未执行鼠标动作；请重新观察并定位：{exc}"
            ) from exc

    def _locate_with_grid(self, target: str, action_name: str):
        raw_image = pyautogui.screenshot()
        guided_image = add_grid(
            raw_image,
            rows=self.grid_rows,
            columns=self.grid_columns,
        )
        grid_path = None
        if self.artifact_writer is not None:
            grid_path = self.artifact_writer(guided_image, f"{action_name}_grid")
        point = self._locate_safely(guided_image, target)
        if point.confidence < self.min_confidence:
            raise RecoverableToolError(
                f"定位置信度 {point.confidence:.2f} 低于阈值 {self.min_confidence:.2f}"
            )
        current_image = pyautogui.screenshot()
        change_score = _screen_change_score(raw_image, current_image)
        if change_score >= STALE_SCREEN_THRESHOLD:
            current_path = None
            if self.artifact_writer is not None:
                current_path = self.artifact_writer(current_image, f"{action_name}_stale_screen")
            raise RecoverableToolError(
                "定位完成后屏幕已经发生明显变化，本次未执行鼠标点击；"
                f"请基于最新截图重新定位。change_score={change_score:.4f}, "
                f"current_image={current_path}"
            )
        return point, grid_path

    def click_target(self, target: str, button: str = "left") -> dict[str, Any]:
        if button not in {"left", "right"}:
            raise ValueError("button 必须是 left 或 right")
        point, grid_path = self._locate_with_grid(target, "click_target")
        pyautogui.click(point.x, point.y, button=button)
        return {
            "ok": True,
            "clicks": 1,
            "button": button,
            **point.to_dict(),
            "grid_image": str(grid_path) if grid_path else None,
        }

    def double_click_target(self, target: str, interval: float = 0.15) -> dict[str, Any]:
        point, grid_path = self._locate_with_grid(target, "double_click_target")
        actual_interval = max(0.05, min(0.5, float(interval)))
        pyautogui.doubleClick(
            point.x,
            point.y,
            interval=actual_interval,
        )
        return {
            "ok": True,
            "clicks": 2,
            "interval": actual_interval,
            **point.to_dict(),
            "grid_image": str(grid_path) if grid_path else None,
        }

    def assert_visible(self, target: str) -> dict[str, Any]:
        point = self._locate_safely(pyautogui.screenshot(), target)
        if point.confidence < self.min_confidence:
            raise RecoverableToolError(
                f"未可靠识别到目标：{target}；confidence={point.confidence:.2f}"
            )
        return {"ok": True, "visible": True, **point.to_dict()}

    @staticmethod
    def scroll(amount: int) -> dict[str, Any]:
        actual = max(-20, min(20, int(amount)))
        pyautogui.scroll(actual)
        return {"ok": True, "amount": actual}

    def specs(self) -> list[ToolSpec]:
        target_parameters = {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
            "additionalProperties": False,
        }
        return [
            ToolSpec(
                "click_target",
                "根据自然语言描述定位并点击可见元素；button 默认为 left，right 用于打开右键菜单",
                {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
                    },
                    "required": ["target"],
                    "additionalProperties": False,
                },
                self.click_target,
            ),
            ToolSpec(
                "double_click_target",
                "定位并双击需要双击打开的元素，例如桌面图标、文件或列表项",
                {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "interval": {
                            "type": "number",
                            "description": "两次点击间隔秒数，默认 0.15",
                        },
                    },
                    "required": ["target"],
                    "additionalProperties": False,
                },
                self.double_click_target,
            ),
            ToolSpec(
                "assert_visible",
                "确认描述的元素当前可见，用于验证操作结果",
                target_parameters,
                self.assert_visible,
            ),
            ToolSpec(
                "scroll",
                "滚动当前界面，正数向上、负数向下",
                {
                    "type": "object",
                    "properties": {"amount": {"type": "integer"}},
                    "required": ["amount"],
                    "additionalProperties": False,
                },
                self.scroll,
            ),
        ]
