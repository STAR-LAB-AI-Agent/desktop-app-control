"""封装完整依赖和生命周期的桌面 Agent。"""

from __future__ import annotations

import sys

from .audit import TaskAuditor
from .config import AgentConfig
from .logging import TaskLogStore
from .runtime import TaskRuntime
from .skills import SkillRegistry
from .task import TaskRequest, TaskResult, TaskReview
from .tools import DesktopToolbox, ToolRegistry, ToolSpec
from .vision import DeepSeekVisionLocator
from .workflows import (
    BaiduSearchWorkflow,
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
            self.workflows.register(BaiduSearchWorkflow())
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
        return TaskRequest(kind="baidu_search", payload={"query": query})

    def create_general_task(
        self,
        task: str,
        *,
        max_steps: int | None = None,
    ) -> TaskRequest:
        steps = max_steps if max_steps is not None else self.config.max_steps
        skill_match = self.skills.route(task)
        if skill_match is not None:
            return TaskRequest(
                kind="skill",
                payload={
                    "task": task,
                    "max_steps": steps,
                    "skill_name": skill_match.definition.name,
                    "skill_variables": skill_match.variables,
                },
            )
        return TaskRequest(
            kind="general",
            payload={
                "task": task,
                "max_steps": steps,
            },
        )

    def review(self, task: TaskRequest) -> TaskReview:
        return self.runtime.review(task)

    def execute(self, task_id: str, *, approved: bool | None = None) -> TaskResult:
        if approved is None:
            approved = self.config.full_trust
        return self.runtime.execute(task_id, approved=approved)

    def cancel(self, task_id: str) -> bool:
        return self.runtime.cancel(task_id)
