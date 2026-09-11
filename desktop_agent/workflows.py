"""任务工作流及注册表。"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any

import pyautogui

from .task import PlannedAction, TaskRequest
from .tools import RecoverableToolError, ToolRegistry
from .skills import SkillRegistry
from .vision import DeepSeekVisionLocator


class Workflow(ABC):
    kind: str

    @abstractmethod
    def plan(self, request: TaskRequest) -> list[PlannedAction]:
        raise NotImplementedError

    def execute(
        self,
        request: TaskRequest,
        tools: ToolRegistry,
        actions: list[PlannedAction],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index, action in enumerate(actions, start=1):
            result = tools.execute(
                action.tool,
                action.arguments,
                explanation=action.purpose,
            )
            results.append(
                {
                    "index": index,
                    "tool": action.tool,
                    "purpose": action.purpose,
                    "result": result,
                }
            )
        return results


class BaiduSearchWorkflow(Workflow):
    kind = "baidu_search"

    def plan(self, request: TaskRequest) -> list[PlannedAction]:
        query = str(request.payload.get("query", "")).strip()
        return [
            PlannedAction(
                "click_target",
                {"target": "百度主页中央的搜索输入框"},
                "定位并聚焦搜索框",
            ),
            PlannedAction("hotkey", {"keys": ["ctrl", "a"]}, "清除已有搜索词"),
            PlannedAction("type_text", {"text": query}, "输入搜索关键词"),
            PlannedAction("press_key", {"key": "enter"}, "提交搜索"),
            PlannedAction("wait", {"seconds": 1.5}, "等待搜索结果页面加载"),
            PlannedAction(
                "assert_visible",
                {"target": "百度搜索结果页面中的搜索结果列表"},
                "确认搜索结果已经出现",
            ),
            PlannedAction(
                "click_target",
                {"target": "百度搜索框右侧的百度一下按钮"},
                "仅在 Enter 未触发页面更新时使用的鼠标回退操作",
            ),
        ]

    def execute(
        self,
        request: TaskRequest,
        tools: ToolRegistry,
        actions: list[PlannedAction],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        def run(action: PlannedAction, purpose: str | None = None) -> dict[str, Any]:
            explanation = purpose or action.purpose
            result = tools.execute(
                action.tool,
                action.arguments,
                explanation=explanation,
            )
            results.append(
                {
                    "index": len(results) + 1,
                    "tool": action.tool,
                    "purpose": explanation,
                    "result": result,
                }
            )
            return result

        for action in actions[:5]:
            run(action)

        try:
            run(actions[5])
            return results
        except RuntimeError as first_error:
            results.append(
                {
                    "index": len(results) + 1,
                    "tool": "reflection",
                    "purpose": "Enter 后未确认页面更新，切换为鼠标点击回退",
                    "result": {"ok": False, "reason": str(first_error)},
                }
            )

        run(actions[6])
        run(PlannedAction("wait", {"seconds": 1.5}, "等待点击后的页面更新"))
        run(
            PlannedAction(
                "assert_visible",
                {"target": "百度搜索结果页面中的搜索结果列表"},
                "再次确认搜索结果已经出现",
            )
        )
        return results


class GeneralTaskWorkflow(Workflow):
    """让视觉模型根据当前屏幕逐步选择工具。"""

    kind = "general"

    def __init__(
        self,
        locator: DeepSeekVisionLocator,
        application_search_names: dict[str, str] | None = None,
        excluded_tools: set[str] | None = None,
    ) -> None:
        self.locator = locator
        self.application_search_names = dict(application_search_names or {})
        self.excluded_tools = set(excluded_tools or ())

    def plan(self, request: TaskRequest) -> list[PlannedAction]:
        return [
            PlannedAction(
                "agent_loop",
                {
                    "task": str(request.payload.get("task", "")),
                    "max_steps": int(request.payload.get("max_steps", 40)),
                },
                "观察屏幕并逐步调用允许的工具，直到确认任务完成",
            )
        ]

    def execute(
        self,
        request: TaskRequest,
        tools: ToolRegistry,
        actions: list[PlannedAction],
    ) -> list[dict[str, Any]]:
        task = str(request.payload["task"]).strip()
        max_steps = max(1, min(60, int(request.payload.get("max_steps", 40))))
        return self._execute_agent(task, max_steps, tools)

    def _execute_agent(
        self,
        task: str,
        max_steps: int,
        tools: ToolRegistry,
        *,
        skill_instructions: str = "",
        skill_variables: dict[str, Any] | None = None,
        excluded_tools: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        excluded = set(self.excluded_tools)
        excluded.update(excluded_tools or ())
        schemas = [
            schema
            for schema in tools.schemas()
            if schema.get("function", {}).get("name") not in excluded
        ]

        for index in range(1, max_steps + 1):
            tools.raise_if_cancelled()
            image = pyautogui.screenshot()
            decision = self.locator.ask_json(
                image,
                self._planner_prompt(
                    task,
                    schemas,
                    history,
                    image.size,
                    skill_instructions=skill_instructions,
                    skill_variables=skill_variables or {},
                    application_search_names=self.application_search_names,
                ),
            )
            tools.raise_if_cancelled()
            tool_name = str(decision.get("tool", ""))
            arguments = decision.get("arguments") or {}
            reason = str(decision.get("reason", ""))

            if tool_name == "finish":
                result = {
                    "ok": True,
                    "summary": str(arguments.get("summary", "任务已完成")),
                }
                history.append(
                    {"index": index, "tool": "finish", "reason": reason, "result": result}
                )
                return history

            if not isinstance(arguments, dict):
                raise ValueError("模型返回的 arguments 必须是 JSON 对象")
            try:
                result = tools.execute(
                    tool_name,
                    arguments,
                    explanation=reason,
                )
            except RecoverableToolError as exc:
                result = {
                    "ok": False,
                    "recoverable": True,
                    "error": str(exc),
                    "instruction": "重新观察当前截图，反思目标是否仍然存在并更换策略",
                }
            history.append(
                {
                    "index": index,
                    "tool": tool_name,
                    "reason": reason,
                    "result": result,
                }
            )

        raise RuntimeError(f"任务超过最大执行步数 {max_steps}，已停止")

    @staticmethod
    def _planner_prompt(
        task: str,
        schemas: list[dict[str, Any]],
        history: list[dict[str, Any]],
        image_size: tuple[int, int],
        *,
        skill_instructions: str = "",
        skill_variables: dict[str, Any] | None = None,
        application_search_names: dict[str, str] | None = None,
    ) -> str:
        skill_section = ""
        if skill_instructions:
            skill_section = f"""

当前任务已路由到专用 Skill。以下指令只适用于当前任务，优先级高于通用建议：
{skill_instructions}

Skill 已解析变量：
{json.dumps(skill_variables or {}, ensure_ascii=False)}
"""
        return f"""
你是桌面操作 Agent。用户任务：{task}
当前截图尺寸：width={image_size[0]}, height={image_size[1]}。
{skill_section}

软件启动搜索名称：
{json.dumps(application_search_names or {}, ensure_ascii=False)}

每轮只选择一个工具。可用工具：
{json.dumps(schemas, ensure_ascii=False)}

最近六步执行历史：
{json.dumps(history[-6:], ensure_ascii=False)}

规则：
1. 根据当前截图选择下一步，不得猜测不可见状态。
2. 名为 Desktop Agent、任务审核或任务输入框的界面属于控制器本身，
   不是用户任务的操作目标；如果短暂看到它们，应调用 wait，不能点击。
3. 当任务需要打开当前屏幕上尚未显示的软件时，必须调用
   open_app_via_windows_search，并按照“软件启动搜索名称”传入准确的软件名。
   这个工具会在一次原子操作中完成 Win+S、覆盖旧查询、输入软件名和按 Enter。
   不得自行拆分成 hotkey/type_text/press_key，也不得点击任务栏图标、搜索历史、
   最近使用、推荐项或搜索建议；这些中间 GUI 内容与任务无关。工具返回后再根据新截图
   确认目标软件是否出现。Windows 搜索中只能使用软件名，不能传入用户要在软件内部
   完成的任务内容。若目标软件已经可见，不要重复启动。
4. 优先让 click_target 根据自然语言定位目标。
5. 当目标是在浏览器或应用的搜索框中搜索时，先确认并聚焦正确的搜索框，然后必须调用
   submit_search_query，一次完成覆盖旧文本、输入准确查询和按 Enter。不得拆分成
   type_text/press_key，也不得点击自动补全、搜索历史、曾搜索过的内容、推荐词或搜索建议；
   它们即使与查询相同也不是结果页。工具返回后再从新截图判断搜索结果。非搜索类输入
   仍可使用 type_text；需要提交时优先按 Enter，不要先寻找提交按钮。
6. 工具结果中的 telemetry.screen_changed=false 表示画面变化不明显。若该工具是
   click_target，必须结合新截图反思：可能点错、目标被遮挡、尚未聚焦或页面未加载；
   改用更精确的目标描述、键盘方式或等待，不要原样重复点击。
7. result.recoverable=true 表示工具没有执行成功。必须查看新截图，确认旧目标是否
   已消失，再选择新目标；不能因为旧目标失败而直接结束整个任务。
8. click_target 会自动给定位截图加网格辅助线，网格不会改变原始屏幕坐标。
9. 仅当界面惯例明确需要双击（如桌面图标、文件、列表项）时使用
   double_click_target；普通按钮、链接和输入框仍使用 click_target。
10. 不要重复已经成功的动作。只有截图已显示最终结果时才能调用 finish。
11. 不得执行任务之外的操作或使用未列出的工具。

只返回 JSON：
{{"tool":"工具名或finish","arguments":{{}},"reason":"简短原因"}}
finish 的 arguments 格式为 {{"summary":"完成情况"}}。
""".strip()


class SkillTaskWorkflow(GeneralTaskWorkflow):
    """仅为命中的场景加载对应 SKILL.md 并执行。"""

    kind = "skill"

    def __init__(
        self,
        locator: DeepSeekVisionLocator,
        skills: SkillRegistry,
        application_search_names: dict[str, str] | None = None,
    ) -> None:
        super().__init__(locator, application_search_names)
        self.skills = skills

    def plan(self, request: TaskRequest) -> list[PlannedAction]:
        return [
            PlannedAction(
                "skill_agent_loop",
                {
                    "skill": request.payload.get("skill_name"),
                    "variables": request.payload.get("skill_variables", {}),
                    "max_steps": int(request.payload.get("max_steps", 40)),
                },
                "加载匹配的场景 Skill，并按专用流程逐步执行和验证",
            )
        ]

    def execute(
        self,
        request: TaskRequest,
        tools: ToolRegistry,
        actions: list[PlannedAction],
    ) -> list[dict[str, Any]]:
        definition = self.skills.get(str(request.payload["skill_name"]))
        max_steps = max(1, min(60, int(request.payload.get("max_steps", 40))))
        variables = dict(request.payload.get("skill_variables") or {})
        prepare_execution = getattr(definition.handler, "prepare_execution", None)
        if prepare_execution is not None:
            variables = prepare_execution(tools, variables)
        excluded_tools = set(
            getattr(definition.handler, "exclude_tools_after_prepare", ())
        )
        excluded_tools.update(
            set(self.skills.all_tool_names())
            - set(self.skills.tool_names(definition.name))
        )
        return self._execute_agent(
            str(request.payload["task"]).strip(),
            max_steps,
            tools,
            skill_instructions=definition.instructions(),
            skill_variables=variables,
            excluded_tools=excluded_tools,
        )


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        if workflow.kind in self._workflows:
            raise ValueError(f"工作流重复注册：{workflow.kind}")
        self._workflows[workflow.kind] = workflow

    def get(self, kind: str) -> Workflow:
        try:
            return self._workflows[kind]
        except KeyError as exc:
            raise ValueError(f"未知任务类型：{kind}") from exc
