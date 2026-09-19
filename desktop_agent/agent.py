"""封装完整依赖和生命周期的桌面 Agent。"""

from __future__ import annotations

import sys

from .audit import TaskAuditor
from .config import AgentConfig
from .logging import TaskLogStore
from .routing import ModelSkillRouter
from .runtime import TaskRuntime
from .skills import SkillRegistry
from .task import TaskRequest, TaskResult, TaskReview
from .tools import DesktopToolbox, ToolRegistry, ToolSpec
from .vision import DeepSeekVisionLocator
from .workflows import (
    GeneralTaskWorkflow,
    SkillTaskWorkflow,
    Workflow,
    WorkflowRegistry,
)


class DesktopAgent:
    def __init__(
        self,
        config: AgentConfig,
        *,
        locator: DeepSeekVisionLocator | None = None,
        auditor: TaskAuditor | None = None,
        workflows: WorkflowRegistry | None = None,
        skill_router: ModelSkillRouter | None = None,
    ) -> None:
        self.config = config
        self.locator = locator or DeepSeekVisionLocator(
            api_key=config.api_key,
            api_url=config.api_url,
            model=config.model,
        )
        self.logs = TaskLogStore(config.logs_dir)
        self.toolbox = DesktopToolbox(
            self.locator,
            min_confidence=config.min_confidence,
            action_pause=config.action_pause,
            logs=self.logs,
            max_atomic_operations=config.max_atomic_operations,
            tool_call_limits=config.tool_call_limits,
            observation_delay=config.observation_delay,
            grid_rows=config.grid_rows,
            grid_columns=config.grid_columns,
        )
        self.tools: ToolRegistry = self.toolbox.build_registry()
        self.skills = SkillRegistry(config.skills_dir)
        self.skills.discover()
        self.skill_router = skill_router or ModelSkillRouter(
            self.locator.ask_text_json
        )
        self.tools.register_many(
            self.skills.build_tool_specs(
                python_executable=sys.executable,
                env_overrides={
                    "DEEPSEEK_API_KEY": config.api_key or "",
                    "DEEPSEEK_API_URL": config.api_url,
                    "DEEPSEEK_MODEL": config.model,
                },
                artifact_dir_provider=lambda: (
                    self.toolbox.monitor.run_dir / "images"
                    if self.toolbox.monitor.run_dir is not None
                    else None
                ),
            )
        )

        self.workflows = workflows or WorkflowRegistry()
        if workflows is None:
            self.workflows.register(
                GeneralTaskWorkflow(
                    self.locator,
                    self.config.application_search_names,
                    excluded_tools=set(self.skills.all_tool_names()),
                )
            )
            self.workflows.register(
                SkillTaskWorkflow(
                    self.locator,
                    self.skills,
                    self.config.application_search_names,
                )
            )
        self.runtime = TaskRuntime(
            self.tools,
            self.workflows,
            auditor=auditor or TaskAuditor(self.skills),
            logs=self.logs,
        )

    def register_tool(self, spec: ToolSpec) -> None:
        self.tools.register(spec)

    def register_workflow(self, workflow: Workflow) -> None:
        self.workflows.register(workflow)

    def create_search_task(self, query: str) -> TaskRequest:
        """保留旧命令兼容性，搜索任务统一交给通用工作流。"""
        query = query.strip()
        task = f"在当前页面搜索：{query}" if query else ""
        return self.create_general_task(task)

    def create_general_task(
        self,
        task: str,
        *,
        max_steps: int | None = None,
    ) -> TaskRequest:
        steps = max_steps if max_steps is not None else self.config.max_steps
        route = self.skill_router.decide(task, self.skills.definitions())
        route_metadata = {"skill_route": route.to_dict()}
        if route.route != ModelSkillRouter.GENERAL_ROUTE:
            skill_match = self.skills.prepare(route.route, task)
            return TaskRequest(
                kind="skill",
                payload={
                    "task": task,
                    "max_steps": steps,
                    "skill_name": skill_match.definition.name,
                    "skill_variables": skill_match.variables,
                    **route_metadata,
                },
            )
        return TaskRequest(
            kind="general",
            payload={
                "task": task,
                "max_steps": steps,
                **route_metadata,
            },
        )

    def review(self, task: TaskRequest) -> TaskReview:
        return self.runtime.review(task)

    def execute(self, task_id: str, *, approved: bool | None = None) -> TaskResult:
        if approved is None:
            approved = self.config.full_trust
        set_cancel_check = getattr(self.locator, "set_cancel_check", None)
        if callable(set_cancel_check):
            set_cancel_check(lambda: self.runtime.raise_if_cancelled(task_id))
        try:
            return self.runtime.execute(task_id, approved=approved)
        finally:
            if callable(set_cancel_check):
                set_cancel_check(None)

    def cancel(self, task_id: str) -> bool:
        return self.runtime.cancel(task_id)
