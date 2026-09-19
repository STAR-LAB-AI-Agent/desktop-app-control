"""任务工作流及注册表。"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import re
from typing import Any

import pyautogui

from .task import PlannedAction, TaskRequest
from .tools import RecoverableToolError, ToolRegistry
from .skills import SkillRegistry
from .vision import DeepSeekVisionLocator
from .tools.music import extract_music_query, needs_music_verification


def is_simple_application_open_task(task: str) -> bool:
    """识别“打开我的钉钉”这类只要求启动应用的任务。"""
    value = re.sub(r"\s+", "", str(task or "")).casefold()
    value = re.sub(r"^(?:请帮我|麻烦帮我|帮我|我要|我想|请|麻烦)", "", value)
    if not re.match(r"^(?:打开|启动|运行)", value):
        return False
    remainder = re.sub(r"^(?:打开|启动|运行)(?:一下)?(?:我的)?", "", value)
    if not remainder:
        return False
    return not any(token in remainder for token in (
        "搜索", "查找", "播放", "查看", "进入", "然后", "并且", "翻译",
        "下载", "输入", "点击", "发送", "打开文件", "会议",
    ))


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
        if needs_music_verification(task):
            return self._execute_music_task(task, tools)
        return self._execute_agent(task, max_steps, tools)

    @staticmethod
    def _execute_music_task(task: str, tools: ToolRegistry) -> list[dict[str, Any]]:
        """用有限、可验证的流程完成听歌任务，避免模型重复搜索。"""
        required = {"search_music_query", "inspect_music_playback"}
        missing = required.difference(tools.names())
        if missing:
            raise RuntimeError(f"听歌任务缺少必要工具：{', '.join(sorted(missing))}")

        query = extract_music_query(task)
        history: list[dict[str, Any]] = []
        last_state = "unknown"
        last_error = ""
        # 最多重新搜索一次。超过两次通常表示窗口被遮挡、结果未加载或
        # 歌曲不存在，继续调用只会耗尽工具上限。
        for attempt in range(1, 3):
            tools.raise_if_cancelled()
            try:
                searched = tools.execute(
                    "search_music_query",
                    {"query": query},
                    explanation=f"第 {attempt} 次在 QQ 音乐搜索并播放目标歌曲《{query}》",
                )
            except RecoverableToolError as exc:
                tools.raise_if_cancelled()
                last_error = str(exc)
                history.append({
                    "index": len(history) + 1,
                    "tool": "search_music_query",
                    "result": {"ok": False, "recoverable": True, "error": last_error},
                })
                continue
            history.append({
                "index": len(history) + 1,
                "tool": "search_music_query",
                "result": searched,
            })

            verification = tools.execute(
                "inspect_music_playback",
                {"task": task},
                explanation="搜索并双击目标歌曲后核对曲名和播放状态",
            )
            history.append({
                "index": len(history) + 1,
                "tool": "inspect_music_playback",
                "result": verification,
            })
            last_state = str(verification.get("state", "unknown"))
            if verification.get("ok") is True and last_state == "playing":
                history.append({
                    "index": len(history) + 1,
                    "tool": "finish",
                    "result": {"ok": True, "summary": f"已确认《{query}》正在播放"},
                })
                return history
            if last_state == "paused" and "resume_music_playback" in tools.names():
                resumed = tools.execute(
                    "resume_music_playback",
                    {"task": task},
                    explanation="目标歌曲已载入但处于暂停状态，恢复播放",
                )
                history.append({
                    "index": len(history) + 1,
                    "tool": "resume_music_playback",
                    "result": resumed,
                })
                recheck = tools.execute(
                    "inspect_music_playback",
                    {"task": task},
                    explanation="恢复播放后复查曲名和播放状态",
                )
                history.append({
                    "index": len(history) + 1,
                    "tool": "inspect_music_playback",
                    "result": recheck,
                })
                last_state = str(recheck.get("state", "unknown"))
                if recheck.get("ok") is True and last_state == "playing":
                    history.append({
                        "index": len(history) + 1,
                        "tool": "finish",
                        "result": {"ok": True, "summary": f"已恢复并确认《{query}》正在播放"},
                    })
                    return history
            if last_state == "blocked":
                raise RuntimeError("音乐播放受登录、会员或付费限制阻止")

        tools.raise_if_cancelled()
        detail = last_error or f"最后验收状态为 {last_state}"
        raise RuntimeError(f"两次尝试后仍未能播放《{query}》：{detail}")

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
        allowed = {s["function"]["name"]: s["function"] for s in schemas}
        invalid_decisions = 0
        rejected_music_finishes = 0

        for index in range(1, max_steps + 1):
            tools.raise_if_cancelled()
            image = pyautogui.screenshot()
            try:
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
                self._validate_decision(decision, allowed)
            except (ValueError, TypeError) as exc:
                tools.raise_if_cancelled()
                invalid_decisions += 1
                history.append({
                    "index": index, "tool": "invalid_decision",
                    "result": {"ok": False, "recoverable": True,
                               "error": str(exc),
                               "instruction": "上一条指令格式错误，未执行任何动作。重新观察屏幕，返回合法的 tool 和 arguments；不要重复已成功的搜索或点击。"},
                })
                if invalid_decisions >= 3:
                    raise RuntimeError(f"模型连续3次返回无效操作指令，已停止：{exc}") from exc
                continue
            invalid_decisions = 0
            tools.raise_if_cancelled()
            tool_name = str(decision.get("tool", ""))
            arguments = decision.get("arguments") or {}
            reason = str(decision.get("reason", ""))

            # 新歌任务中，普通 click_target 点击搜索框容易因为旧画面或
            # 输入框未真正聚焦而重复执行。交给音乐专用原子工具一次完成
            # 定位、覆盖旧词和提交，且不消耗 click_target 调用次数。
            if (
                needs_music_verification(task)
                and tool_name == "click_target"
                and "search_music_query" in allowed
                and any(token in str(arguments.get("target", "")).lower()
                        for token in ("搜索框", "search box", "search field"))
            ):
                history.append({
                    "index": index,
                    "tool": "invalid_decision",
                    "result": {
                        "ok": False,
                        "recoverable": True,
                        "error": "音乐任务不能重复点击搜索框",
                        "instruction": "请调用 search_music_query 一次定位 QQ 音乐搜索框并提交本次歌曲，不要使用 click_target 搜索框",
                    },
                })
                continue

            if tool_name == "finish":
                if needs_music_verification(task):
                    # 每次结束都重新验收，不能复用点击之前的状态或模型自己的总结。
                    if "inspect_music_playback" not in allowed:
                        raise RuntimeError("缺少音乐播放验收工具，无法确认任务完成")
                    verification = tools.execute(
                        "inspect_music_playback", {"task": task},
                        explanation="结束前强制检查目标歌曲及播放时间是否前进",
                    )
                    history.append({"index": index, "tool": "inspect_music_playback", "result": verification})
                    tools.raise_if_cancelled()
                    if verification.get("state") != "playing" or verification.get("ok") is not True:
                        rejected_music_finishes += 1
                        if verification.get("state") == "blocked":
                            raise RuntimeError("音乐播放受阻：请检查登录或会员限制，未确认播放成功")
                        if verification.get("state") == "paused" and "resume_music_playback" in allowed:
                            resume = tools.execute(
                                "resume_music_playback", {"task": task},
                                explanation="目标歌曲已载入但处于暂停状态，改用 Windows 媒体会话恢复播放",
                            )
                            history.append({"index": index, "tool": "resume_music_playback", "result": resume})
                            if resume.get("state") == "playing" and resume.get("ok") is True:
                                rejected_music_finishes = 0
                            continue
                        if rejected_music_finishes >= 3:
                            raise RuntimeError("音乐播放连续3次未通过动态验收，未确认播放成功，请检查播放器状态")
                        continue
                    arguments = {"summary": "已核对目标曲目，Windows 媒体会话两次报告正在播放；未验证扬声器声音输出。"}
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
            if (
                tool_name == "open_app_via_windows_search"
                and result.get("verified_open") is True
                and result.get("foreground") is False
            ):
                app_name = str(result.get("app_name") or arguments.get("app_name") or "应用")
                raise RuntimeError(
                    f"{app_name} 已经运行，但 Windows 未能把它切换到前台；"
                    "已停止重复启动，请手动切换一次窗口后重试"
                )
            if (
                tool_name == "open_app_via_windows_search"
                and result.get("verified_open") is True
                and is_simple_application_open_task(task)
            ):
                app_name = str(result.get("app_name") or arguments.get("app_name") or "应用")
                history.append({
                    "index": index,
                    "tool": "finish",
                    "reason": "Windows 原生进程或窗口检查已确认应用运行",
                    "result": {
                        "ok": True,
                        "summary": f"已确认{app_name}成功打开",
                    },
                })
                return history
            # 视频检查器与音乐检查器一样，其结构化 playing 结果本身就是
            # 完成条件。不要再向规划模型请求一次“finish”，否则视频已经
            # 播放时的一次网络抖动会把成功任务错误地标记为失败。
            if (
                tool_name == "inspect_video_playback_state"
                and result.get("state") == "playing"
                and result.get("can_finish") is True
            ):
                history.append({
                    "index": index,
                    "tool": "finish",
                    "reason": "视频检查器已确认播放器正在播放",
                    "result": {
                        "ok": True,
                        "summary": "已确认视频网站播放器中的广告、片头或正片正在播放",
                    },
                })
                return history

            # 检查器刚报告 paused/video_page 后，模型只需负责定位一次播放
            # 按钮。点击成功后由工作流立即复查，避免为显而易见的下一步
            # 再调用规划 API。
            if tool_name == "click_target" and "inspect_video_playback_state" in allowed:
                previous_video_check = next(
                    (
                        item.get("result", {})
                        for item in reversed(history[:-1])
                        if item.get("tool") == "inspect_video_playback_state"
                    ),
                    None,
                )
                target_text = str(arguments.get("target", "")).casefold()
                clicked_play = "播放" in target_text or "play" in target_text
                if (
                    isinstance(previous_video_check, dict)
                    and previous_video_check.get("state") in {"paused", "video_page"}
                    and clicked_play
                ):
                    video_query = str(
                        (skill_variables or {}).get("video_query") or task
                    )
                    verification = tools.execute(
                        "inspect_video_playback_state",
                        {"video_query": video_query},
                        explanation="点击播放器播放按钮后立即复查视频是否已经开始播放",
                    )
                    history.append({
                        "index": index,
                        "tool": "inspect_video_playback_state",
                        "result": verification,
                    })
                    if (
                        verification.get("state") == "playing"
                        and verification.get("can_finish") is True
                    ):
                        history.append({
                            "index": index,
                            "tool": "finish",
                            "reason": "点击播放后检查器已确认视频正在播放",
                            "result": {
                                "ok": True,
                                "summary": "已点击播放并确认播放器画面正在连续播放",
                            },
                        })
                        return history
                    if verification.get("state") == "blocked":
                        raise RuntimeError("视频播放受到登录、验证码、付费或地区限制")
                    continue
            if (
                tool_name == "inspect_music_playback"
                and needs_music_verification(task)
                and result.get("state") == "wrong_track"
                and "search_music_query" in allowed
            ):
                # 媒体会话明确显示旧歌曲时，自动重新搜索并点击目标歌曲，
                # 避免把恢复动作交给模型后反复打开应用或检查旧歌曲。
                query = extract_music_query(task)
                searched = tools.execute(
                    "search_music_query",
                    {"query": query},
                    explanation="媒体会话显示旧歌曲，自动重新定位 QQ 音乐搜索框并点击目标歌曲",
                )
                history.append(
                    {"index": index, "tool": "search_music_query", "result": searched}
                )
                if searched.get("ok") is not True:
                    raise RuntimeError(
                        f"未能从旧歌曲恢复到目标歌曲《{query}》：{searched.get('error', '搜索失败')}"
                    )
                continue
            # 音乐验收本身就是完成条件。若模型主动调用验收工具并已得到
            # 严格的 playing 结果，直接结束任务，避免再次向模型请求无意义
            # 的下一步，尤其能避免媒体会话不可用时的重复 API 调用。
            if (
                tool_name == "inspect_music_playback"
                and needs_music_verification(task)
                and result.get("state") == "playing"
                and result.get("ok") is True
            ):
                history.append(
                    {
                        "index": index,
                        "tool": "finish",
                        "reason": "音乐验收已确认目标歌曲正在播放",
                        "result": {
                            "ok": True,
                            "summary": "已核对目标歌曲和播放进度，确认正在播放",
                        },
                    }
                )
                return history
            if (
                tool_name == "inspect_music_playback"
                and needs_music_verification(task)
                and result.get("state") == "paused"
                and "resume_music_playback" in allowed
            ):
                resume = tools.execute(
                    "resume_music_playback",
                    {"task": task},
                    explanation="验收确认歌曲处于暂停，自动恢复播放后重新验收",
                )
                history.append(
                    {"index": index, "tool": "resume_music_playback", "result": resume}
                )
                tools.raise_if_cancelled()
                # 恢复命令的返回值可能受 winrt 是否安装影响，因此无论
                # 返回值如何都再观察一次；只有进度实际前进才完成任务。
                verification = tools.execute(
                    "inspect_music_playback",
                    {"task": task},
                    explanation="恢复播放后复查目标歌曲和进度是否前进",
                )
                history.append(
                    {"index": index, "tool": "inspect_music_playback", "result": verification}
                )
                if verification.get("state") == "playing" and verification.get("ok") is True:
                    history.append(
                        {
                            "index": index,
                            "tool": "finish",
                            "reason": "恢复播放后已确认目标歌曲正在播放",
                            "result": {
                                "ok": True,
                                "summary": "已恢复播放并核对目标歌曲进度正在前进",
                            },
                        }
                    )
                    return history
                raise RuntimeError(
                    "自动恢复播放后仍无法确认目标歌曲正在播放，"
                    f"state={verification.get('state', 'unknown')}，已停止，避免重复验收"
                )

        raise RuntimeError(f"任务超过最大执行步数 {max_steps}，已停止")

    @staticmethod
    def _validate_decision(decision, allowed: dict[str, Any]) -> None:
        """在执行任何动作之前检查模型响应，包括被过滤掉的工具。"""
        if not isinstance(decision, dict):
            raise ValueError("操作指令必须是 JSON 对象")
        name = decision.get("tool")
        if not isinstance(name, str) or (name != "finish" and name not in allowed):
            raise ValueError("tool 缺失或不在当前允许的工具列表中")
        arguments = decision.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("arguments 必须是 JSON 对象，不能是文本、数组或空值")
        if name == "finish":
            if not isinstance(arguments.get("summary"), str) or not arguments["summary"].strip():
                raise ValueError("finish 必须提供非空 summary")
            return
        parameters = allowed[name].get("parameters", {})
        if any(key not in arguments for key in parameters.get("required", [])):
            raise ValueError(f"{name} 缺少必要参数")
        properties = parameters.get("properties", {})
        if parameters.get("additionalProperties") is False and arguments.keys() - properties.keys():
            raise ValueError(f"{name} 包含未声明的参数")
        types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
                 "array": list, "object": dict}
        for key, value in arguments.items():
            spec = properties.get(key, {})
            kind = spec.get("type")
            if kind in types and (not isinstance(value, types[kind]) or
                                  (kind in ("integer", "number") and isinstance(value, bool))):
                raise ValueError(f"{name}.{key} 参数类型错误")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"{name}.{key} 参数值不在允许范围内")

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
   搜索框点击后出现输入光标、选中文本或下拉建议列表，即可视为已聚焦；下一步立即调用
   submit_search_query 提交本次目标。旧搜索词仍显示是正常现象，该工具会覆盖它；
   不要为了等旧词消失或建议关闭而重复点击搜索框。
6. 工具结果中的 telemetry.screen_changed=false 表示画面变化不明显。若该工具是
   click_target，必须结合新截图反思：可能点错、目标被遮挡、尚未聚焦或页面未加载；
   改用更精确的目标描述、键盘方式或等待，不要原样重复点击。
7. result.recoverable=true 表示工具没有执行成功。必须查看新截图，确认旧目标是否
   已消失，再选择新目标；不能因为旧目标失败而直接结束整个任务。
8. click_target 会自动给定位截图加网格辅助线，网格不会改变原始屏幕坐标。
9. 仅当界面惯例明确需要双击（如桌面图标、文件、列表项）时使用
   double_click_target；普通按钮、链接和输入框仍使用 click_target。
10. 不要重复已经成功的动作。只有截图已显示最终结果时才能调用 finish。
    音乐播放必须用 inspect_music_playback 核对 Windows 媒体会话，assert_visible 不能证明正在播放。
    听歌任务搜索新歌曲时优先调用 search_music_query；它会重新定位 QQ 音乐搜索框、覆盖旧词并提交查询。
    不要用 click_target 反复点击搜索框，也不要把旧搜索结果当成本次歌曲。
    三角形是“播放”按钮，表示当前暂停；双竖线是“暂停”按钮。不能把两种图标混淆。
    验收返回 paused 时，优先调用 resume_music_playback 恢复播放并复查，
    不要优先点击底栏的小三角播放按钮；窗口移动、缩放或布局变化时小按钮容易点偏。
    不要重新搜索或重复右键已经载入的目标歌曲。unknown 表示系统状态不足以确认，不能直接报告成功。
    对于“我要听某首歌”等未指定视频网站的任务，使用配置中的音乐软件完成搜索和播放。
    点击歌曲行可能只是选中或载入歌曲；搜索结果出现、底栏显示歌名都不等于已经播放。
    本次用户任务中的歌名是唯一目标，不得把窗口残留的搜索词、歌曲列表或底栏曲目
    当成本次目标。例如用户要听《我怀念的》，当前显示《挪威的森林》时，必须先聚焦
    搜索框并用 submit_search_query 搜索“我怀念的”，不能右键或播放《挪威的森林》。
    每次准备播放前，先核对可见歌曲标题与用户要求一致；未找到匹配结果时继续查找，
    不得用第一条结果或上次播放的歌曲替代。click_target 的 target 必须明确包含本次歌名。
    音乐播放预设：确认已找到本次目标歌曲后，先在音乐软件窗口内对目标歌曲条目调用
    click_target，button="right"，打开右键菜单；不要右键标题栏或无关空白处。
    右键后必须观察新截图，确认菜单已出现，再用 click_target（button="left"）点击
    菜单中明确的“播放”项。不得根据右键前的截图猜测菜单位置，也不要点击播放全部、
    删除或其他无关菜单项。菜单未出现或没有“播放”时重新观察，不要盲目重复右键。
    如果目标歌曲已经显示暂停按钮且确认正在播放，跳过上述操作，避免打断播放。
    完成前用 assert_visible 确认目标曲目与暂停控件，或结合等待前后截图确认播放进度前进；
    证据不足时继续观察和操作，不得仅凭一次点击就报告播放成功。只能报告可见的播放状态，
    没有声音检测工具时不得声称已验证声音输出或“语音已打开”。
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
