"""按任务组织事件、结构化结果、原子操作和截图目录。"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TaskLogStore:
    """为每个任务创建一个可独立查看和归档的日志目录。"""

    def __init__(self, root: Path | None = Path("logs")) -> None:
        self.root = root
        self._task_dirs: dict[str, Path] = {}
        self._lock = threading.RLock()

    def start_task(self, task: dict[str, Any]) -> Path | None:
        if self.root is None:
            return None
        task_id = str(task["id"])
        with self._lock:
            existing = self._task_dirs.get(task_id)
            if existing is not None:
                return existing

            self.root.mkdir(parents=True, exist_ok=True)
            timestamp = _folder_timestamp(str(task.get("created_at", "")))
            summary = _task_summary(task)
            candidate = self.root / f"{timestamp}_{summary}"
            directory = _unused_path(candidate)
            (directory / "images").mkdir(parents=True)
            (directory / "json").mkdir()
            (directory / "operations").mkdir()
            self._task_dirs[task_id] = directory
            _write_json(directory / "json" / "task.json", task)
            return directory

    def task_dir(self, task_id: str) -> Path | None:
        return self._task_dirs.get(task_id)

    def images_dir(self, task_id: str) -> Path | None:
        directory = self.task_dir(task_id)
        return None if directory is None else directory / "images"

    def record_event(
        self,
        task_id: str,
        event: str,
        data: dict[str, Any],
    ) -> None:
        directory = self.task_dir(task_id)
        if directory is None:
            return
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **data,
        }
        with self._lock:
            _append_jsonl(directory / "json" / "events.jsonl", entry)

    def write_json(self, task_id: str, filename: str, value: dict[str, Any]) -> None:
        directory = self.task_dir(task_id)
        if directory is None:
            return
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
        if not safe_name.endswith(".json"):
            safe_name += ".json"
        with self._lock:
            _write_json(directory / "json" / safe_name, value)

    def record_operation(
        self,
        task_id: str,
        operation: dict[str, Any],
    ) -> None:
        directory = self.task_dir(task_id)
        if directory is None:
            return
        index = int(operation.get("operation", 0))
        tool = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(operation.get("tool", "tool")),
        ).strip("_")
        operation_dir = directory / "operations"
        with self._lock:
            _append_jsonl(operation_dir / "steps.jsonl", operation)
            _write_json(operation_dir / f"{index:03d}_{tool}.json", operation)


def _folder_timestamp(created_at: str) -> str:
    try:
        value = datetime.fromisoformat(created_at).astimezone()
    except (TypeError, ValueError):
        value = datetime.now().astimezone()
    return value.strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]


def _task_summary(task: dict[str, Any]) -> str:
    payload = task.get("payload") or {}
    raw = str(payload.get("task") or payload.get("query") or task.get("kind") or "task")
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip(" ._")
    return (value or "task")[:48].rstrip(" ._")


def _unused_path(candidate: Path) -> Path:
    if not candidate.exists():
        return candidate
    for suffix in range(2, 1000):
        alternative = candidate.with_name(f"{candidate.name}_{suffix}")
        if not alternative.exists():
            return alternative
    raise RuntimeError(f"无法为任务创建唯一日志目录：{candidate}")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
