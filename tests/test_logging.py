import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from desktop_agent.logging import TaskLogStore
from desktop_agent.runtime import TaskRuntime
from desktop_agent.task import TaskRequest
from desktop_agent.tools.base import ToolRegistry, ToolSpec
from desktop_agent.workflows import BaiduSearchWorkflow, WorkflowRegistry


class TaskLogStoreTests(unittest.TestCase):
    def test_creates_one_readable_directory_per_task(self) -> None:
        with TemporaryDirectory() as temporary:
            logs = TaskLogStore(Path(temporary))
            directory = logs.start_task(
                {
                    "id": "task-1",
                    "kind": "skill",
                    "payload": {"task": "翻译 GROOT 论文"},
                    "created_at": "2026-09-11T02:03:04.123000+00:00",
                    "status": "submitted",
                }
            )
            assert directory is not None
            self.assertIn("翻译_GROOT_论文", directory.name)
            self.assertTrue((directory / "images").is_dir())
            self.assertTrue((directory / "json" / "task.json").is_file())
            self.assertTrue((directory / "operations").is_dir())

    def test_records_explained_atomic_operation(self) -> None:
        with TemporaryDirectory() as temporary:
            logs = TaskLogStore(Path(temporary))
            directory = logs.start_task(
                {
                    "id": "task-2",
                    "kind": "general",
                    "payload": {"task": "打开记事本"},
                    "created_at": "2026-09-11T02:03:04+00:00",
                    "status": "submitted",
                }
            )
            assert directory is not None
            operation = {
                "operation": 1,
                "tool": "hotkey",
                "explanation": "打开 Windows 搜索",
                "arguments": {"keys": ["win", "s"]},
                "result": {"ok": True},
                "telemetry": {"screen_changed": True},
                "error": None,
            }
            logs.record_operation("task-2", operation)
            step_file = directory / "operations" / "001_hotkey.json"
            recorded = json.loads(step_file.read_text(encoding="utf-8"))
            self.assertEqual(recorded["explanation"], "打开 Windows 搜索")
            self.assertTrue((directory / "operations" / "steps.jsonl").is_file())

    def test_tool_registry_always_supplies_an_explanation(self) -> None:
        class CaptureMonitor:
            explanation = ""

            def execute(self, name, handler, arguments, explanation):
                self.explanation = explanation
                return handler(**arguments)

        monitor = CaptureMonitor()
        registry = ToolRegistry(monitor)  # type: ignore[arg-type]
        registry.register(
            ToolSpec(
                "demo",
                "默认动作讲解",
                {"type": "object", "properties": {}},
                lambda: {"ok": True},
            )
        )
        registry.execute("demo", {})
        self.assertEqual(monitor.explanation, "默认动作讲解")

    def test_runtime_keeps_task_and_review_in_the_same_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            logs = TaskLogStore(Path(temporary))
            workflows = WorkflowRegistry()
            workflows.register(BaiduSearchWorkflow())
            runtime = TaskRuntime(ToolRegistry(), workflows, logs=logs)
            request = TaskRequest(kind="baidu_search", payload={"query": "Python"})

            runtime.review(request)

            directory = logs.task_dir(request.id)
            assert directory is not None
            self.assertTrue((directory / "json" / "task.json").is_file())
            self.assertTrue((directory / "json" / "review.json").is_file())
            events = (directory / "json" / "events.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("task_submitted", events)
            self.assertIn("task_reviewed", events)


if __name__ == "__main__":
    unittest.main()
