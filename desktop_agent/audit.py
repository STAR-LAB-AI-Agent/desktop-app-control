"""任务执行前审核：校验输入、风险和将要调用的工具。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .task import ReviewDecision, RiskLevel, TaskRequest, TaskReview, TaskStatus

if TYPE_CHECKING:
    from .skills import SkillRegistry


SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(api[_ -]?key|password|token)\s*[:=]\s*\S+"),
)

DANGEROUS_TASK_PATTERN = re.compile(
    r"删除|清空|卸载|安装|付款|支付|转账|购买|发送|发布|上传|登录|验证码|修改密码"
)


class TaskAuditor:
    def __init__(self, skills: SkillRegistry | None = None) -> None:
        self.skills = skills

    def review(self, request: TaskRequest, actions: list) -> TaskReview:
        request.status = TaskStatus.UNDER_REVIEW

        if request.kind == "baidu_search":
            return self._review_search(request, actions)
        if request.kind == "general":
            return self._review_general(request, actions)
        if request.kind == "skill":
            return self._review_skill(request, actions)
        return TaskReview(
            task_id=request.id,
            decision=ReviewDecision.REJECT,
            risk=RiskLevel.HIGH,
            summary=f"不支持的任务类型：{request.kind}",
            actions=actions,
            warnings=["没有与该任务类型对应的审核规则。"],
        )

    def _review_search(self, request: TaskRequest, actions: list) -> TaskReview:
        query = str(request.payload.get("query", "")).strip()
        if not query:
            return self._reject(request, actions, "搜索关键词不能为空。")
        if len(query) > 500:
            return self._reject(request, actions, "搜索关键词超过 500 字符。")
        if any(pattern.search(query) for pattern in SECRET_PATTERNS):
            return self._reject(
                request,
                actions,
                "搜索内容疑似包含 API key、密码或令牌，默认禁止发送。",
            )

        request.status = TaskStatus.AWAITING_APPROVAL
        return TaskReview(
            task_id=request.id,
            decision=ReviewDecision.CONFIRM,
            risk=RiskLevel.LOW,
            summary=f"在当前百度页面搜索：{query}",
            actions=actions,
            warnings=[
                "搜索关键词会提交给百度并触发页面跳转。",
                "执行期间请勿移动窗口；鼠标移到屏幕左上角可紧急停止。",
            ],
        )

    def _review_general(self, request: TaskRequest, actions: list) -> TaskReview:
        task = str(request.payload.get("task", "")).strip()
        if not task:
            return self._reject(request, actions, "任务描述不能为空。")
        if len(task) > 1000:
            return self._reject(request, actions, "任务描述超过 1000 字符。")
        if any(pattern.search(task) for pattern in SECRET_PATTERNS):
            return self._reject(request, actions, "任务疑似包含密钥、密码或令牌。")
        if DANGEROUS_TASK_PATTERN.search(task):
            return self._reject(
                request,
                actions,
                "当前通用工作流仅允许低风险操作，任务包含高影响动作。",
            )

        request.status = TaskStatus.AWAITING_APPROVAL
        return TaskReview(
            task_id=request.id,
            decision=ReviewDecision.CONFIRM,
            risk=RiskLevel.MEDIUM,
            summary=f"执行通用桌面任务：{task}",
            actions=actions,
            warnings=[
                "模型会在最大步数限制内根据屏幕内容动态选择工具。",
                "完全信任只跳过人工确认，不跳过硬性审核。",
                "鼠标移到屏幕左上角可紧急停止。",
            ],
        )

    def _review_skill(self, request: TaskRequest, actions: list) -> TaskReview:
        task = str(request.payload.get("task", "")).strip()
        skill_name = str(request.payload.get("skill_name", "")).strip()
        variables = request.payload.get("skill_variables") or {}

        if not task:
            return self._reject(request, actions, "任务描述不能为空。")
        if any(pattern.search(task) for pattern in SECRET_PATTERNS):
            return self._reject(request, actions, "任务疑似包含密钥、密码或令牌。")
        if self.skills is None:
            return self._reject(request, actions, "审核器没有连接 Skill 注册表。")
        try:
            definition = self.skills.get(skill_name)
        except ValueError as exc:
            return self._reject(request, actions, str(exc))
        build_review = getattr(definition.handler, "build_review", None)
        if build_review is None:
            return self._reject(
                request,
                actions,
                f"Skill {skill_name!r} 没有提供 build_review() 审核配置。",
            )
        try:
            details = build_review(variables)
        except (TypeError, ValueError) as exc:
            return self._reject(request, actions, str(exc))
        if not isinstance(details, dict):
            return self._reject(request, actions, "Skill 的 build_review() 必须返回字典。")
        try:
            risk = RiskLevel(str(details.get("risk", "high")))
        except ValueError:
            return self._reject(request, actions, "Skill 返回了无效的风险等级。")
        summary = str(details.get("summary", "")).strip()
        warnings = [str(item) for item in details.get("warnings", [])]
        if not summary:
            return self._reject(request, actions, "Skill 没有提供审核摘要。")

        request.status = TaskStatus.AWAITING_APPROVAL
        return TaskReview(
            task_id=request.id,
            decision=ReviewDecision.CONFIRM,
            risk=risk,
            summary=summary,
            actions=actions,
            warnings=warnings,
        )

    @staticmethod
    def _reject(request: TaskRequest, actions: list, reason: str) -> TaskReview:
        request.status = TaskStatus.REJECTED
        return TaskReview(
            task_id=request.id,
            decision=ReviewDecision.REJECT,
            risk=RiskLevel.HIGH,
            summary=reason,
            actions=actions,
            warnings=["任务不会执行。"],
        )
