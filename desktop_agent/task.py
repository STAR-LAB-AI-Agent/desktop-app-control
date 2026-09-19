"""任务、审核结果和运行结果的数据结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    REJECT = "reject"


@dataclass
class TaskRequest:
    kind: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.SUBMITTED
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(frozen=True)
class PlannedAction:
    tool: str
    arguments: dict[str, Any]
    purpose: str


@dataclass(frozen=True)
class TaskReview:
    task_id: str
    decision: ReviewDecision
    risk: RiskLevel
    summary: str
    actions: list[PlannedAction]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "decision": self.decision.value,
            "risk": self.risk.value,
            "summary": self.summary,
            "actions": [asdict(action) for action in self.actions],
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    steps: list[dict[str, Any]]
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    finished_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value
