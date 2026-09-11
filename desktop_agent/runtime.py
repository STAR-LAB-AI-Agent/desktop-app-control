"""任务状态机：审核、审批、执行和日志。"""

from __future__ import annotations

import threading

from .audit import TaskAuditor
from .logging import TaskLogStore
from .task import ReviewDecision, TaskRequest, TaskResult, TaskReview, TaskStatus
from .tools import TaskCancelledError, ToolRegistry
from .workflows import Workflow, WorkflowRegistry


class TaskRuntime:
    def __init__(
        self,
        tools: ToolRegistry,
        workflows: WorkflowRegistry,
        *,
        auditor: TaskAuditor | None = None,
        logs: TaskLogStore | None = None,
    ) -> None:
        self.tools = tools
        self.workflows = workflows
        self.auditor = auditor or TaskAuditor()
        self.logs = logs or TaskLogStore()
        self._reviewed: dict[str, tuple[TaskRequest, TaskReview, Workflow]] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def review(self, request: TaskRequest) -> TaskReview:
        self.logs.start_task(request.to_dict())
        self.logs.record_event(
            request.id,
            "task_submitted",
            {"task": request.to_dict()},
        )
        try:
            workflow = self.workflows.get(request.kind)
            actions = workflow.plan(request)
            review = self.auditor.review(request, actions)
        except Exception as exc:
            request.status = TaskStatus.REJECTED
            review = TaskReview(
                task_id=request.id,
                decision=ReviewDecision.REJECT,
                risk=self._high_risk(),
                summary=str(exc),
                actions=[],
                warnings=["任务规划失败，不会执行。"],
            )
            workflow = None

        self.logs.write_json(request.id, "review.json", review.to_dict())
        self.logs.record_event(
            request.id,
            "task_reviewed",
            {"review": review.to_dict()},
        )
        if workflow is not None:
            self._reviewed[request.id] = (request, review, workflow)
            self._cancel_events[request.id] = threading.Event()
        return review

    def cancel(self, task_id: str) -> bool:
        event = self._cancel_events.get(task_id)
        if event is None:
            return False
        event.set()
        self.logs.record_event(task_id, "task_cancel_requested", {"task_id": task_id})
        return True

    def execute(self, task_id: str, *, approved: bool) -> TaskResult:
        if task_id not in self._reviewed:
            raise ValueError("任务尚未审核或任务编号无效")
        request, review, workflow = self._reviewed.pop(task_id)
        cancel_event = self._cancel_events.get(task_id)

        if review.decision == ReviewDecision.REJECT:
            self._cancel_events.pop(task_id, None)
            result = TaskResult(task_id, TaskStatus.REJECTED, [], review.summary)
            self._finish_log(result)
            return result
        if review.decision == ReviewDecision.CONFIRM and not approved:
            request.status = TaskStatus.CANCELLED
            result = TaskResult(task_id, TaskStatus.CANCELLED, [])
            self._cancel_events.pop(task_id, None)
            self.logs.record_event(
                task_id,
                "task_cancelled",
                {"result": result.to_dict()},
            )
            self.logs.write_json(task_id, "result.json", result.to_dict())
            return result

        request.status = TaskStatus.RUNNING
        self.logs.record_event(task_id, "task_started", {"task_id": task_id})
        self.tools.start_run(task_id, cancel_event)
        try:
            steps = workflow.execute(request, self.tools, review.actions)
            request.status = TaskStatus.SUCCEEDED
            result = TaskResult(
                task_id,
                TaskStatus.SUCCEEDED,
                steps,
                metadata=self.tools.stats(),
            )
        except TaskCancelledError as exc:
            request.status = TaskStatus.CANCELLED
            result = TaskResult(
                task_id,
                TaskStatus.CANCELLED,
                [],
                str(exc),
                metadata=self.tools.stats(),
            )
        except Exception as exc:
            request.status = TaskStatus.FAILED
            result = TaskResult(
                task_id,
                TaskStatus.FAILED,
                [],
                str(exc),
                metadata=self.tools.stats(),
            )
        self._cancel_events.pop(task_id, None)
        self._finish_log(result)
        return result

    def _finish_log(self, result: TaskResult) -> None:
        self.logs.write_json(result.task_id, "result.json", result.to_dict())
        self.logs.record_event(
            result.task_id,
            "task_finished",
            {"result": result.to_dict()},
        )

    @staticmethod
    def _high_risk():
        from .task import RiskLevel

        return RiskLevel.HIGH
