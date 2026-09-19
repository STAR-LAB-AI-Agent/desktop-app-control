"""工具描述和注册表，与具体桌面实现解耦。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .monitor import ToolExecutionMonitor


ToolHandler = Callable[..., dict[str, Any]]


class RecoverableToolError(RuntimeError):
    """界面状态变化后可以重新观察并换策略的工具错误。"""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, monitor: ToolExecutionMonitor | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.monitor = monitor

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具重复注册：{spec.name}")
        self._tools[spec.name] = spec

    def register_many(self, specs: Iterable[ToolSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        explanation: str = "",
    ) -> dict[str, Any]:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ValueError(f"未知工具：{name}；可用工具={self.names()}") from exc
        if not isinstance(arguments, dict):
            raise TypeError("工具参数必须是 JSON 对象")
        if self.monitor is None:
            return tool.handler(**arguments)
        detail = explanation.strip() or tool.description
        return self.monitor.execute(name, tool.handler, arguments, detail)

    def start_run(self, task_id: str, cancel_event=None) -> None:
        if self.monitor is not None:
            self.monitor.start_run(task_id, cancel_event)

    def raise_if_cancelled(self) -> None:
        if self.monitor is not None:
            self.monitor.raise_if_cancelled()

    def stats(self) -> dict[str, Any]:
        return self.monitor.stats() if self.monitor is not None else {}
