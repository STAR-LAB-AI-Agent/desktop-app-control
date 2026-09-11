"""Routing and input extraction for the ChatGPT paper translation skill."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class ChatGPTPaperAbstractSkill:
    name = "chatgpt-paper-abstract"
    exclude_tools_after_prepare = ("find_desktop_file",)

    def matches(self, task: str) -> bool:
        normalized = task.lower()
        wants_translation = "翻译" in task or "translate" in normalized
        mentions_paper = "论文" in task or "paper" in normalized or ".pdf" in normalized
        return wants_translation and mentions_paper

    def prepare(self, task: str) -> dict[str, Any]:
        return {
            "paper_query": self._extract_paper_query(task),
            "scope": "abstract_and_sections_1_to_5",
            "translation_segments": [
                "Abstract",
                "Section 1",
                "Section 2",
                "Section 3",
                "Section 4",
                "Section 5",
            ],
            "target_language": "中文",
            "destination": "ChatGPT desktop Work",
        }

    @staticmethod
    def build_review(variables: dict[str, Any]) -> dict[str, Any]:
        paper_query = str(variables.get("paper_query", "")).strip()
        if not paper_query:
            raise ValueError("没有从任务中解析出论文名称。")
        return {
            "risk": "medium",
            "summary": (
                f"使用 ChatGPT 桌面版 Work 功能上传桌面上的“{paper_query}”PDF，"
                "依次翻译 Abstract 以及 Section 1 到 Section 5。"
            ),
            "warnings": [
                "上传会把所选论文文件发送给 ChatGPT；执行前请确认你有权处理该文件。",
                "Agent 只会在桌面找到唯一匹配的 PDF 后继续；零个或多个匹配都会停止。",
                "翻译将分六次提交；每一段完成后才会继续下一段。",
                "若 ChatGPT 尚未登录或要求验证，Agent 会停止并等待人工处理。",
            ],
        }

    @staticmethod
    def prepare_execution(
        tools: Any,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        paper_query = variables.get("paper_query", "").strip()
        result = tools.execute(
            "find_desktop_file",
            {"query": paper_query, "extension": ".pdf"},
            explanation=f"在桌面预检并唯一确定论文文件：{paper_query}",
        )
        matches = list(result.get("matches") or [])
        if result.get("status") == "ambiguous":
            names = "、".join(Path(path).name for path in matches)
            raise RuntimeError(
                f"桌面上有多个与“{paper_query}”同等匹配的 PDF：{names}。"
                "请在任务中提供更精确的文件名。"
            )
        if not result.get("ok") or len(matches) != 1:
            raise RuntimeError(
                f"桌面上没有找到与“{paper_query}”唯一匹配的 PDF。"
                "请确认文件位于 Windows 桌面并检查文件名。"
            )

        resolved = dict(variables)
        resolved["paper_path"] = matches[0]
        resolved["paper_filename"] = Path(matches[0]).name
        resolved["paper_match_method"] = str(result.get("match_method") or "")
        return resolved

    @staticmethod
    def _extract_paper_query(task: str) -> str:
        patterns = (
            r"翻译(?:一下)?\s*(?P<name>.+?)\s*(?:这篇)?论文",
            r"(?P<name>[^，。]+?)\s*(?:论文|\.pdf).*?翻译",
            r"translate\s+(?P<name>.+?)\s+(?:paper|\.pdf)",
        )
        for pattern in patterns:
            match = re.search(pattern, task, flags=re.IGNORECASE)
            if match:
                value = match.group("name").strip(" 《》\"'，,。.")
                value = re.sub(
                    r"^(?:请|麻烦)?(?:帮我)?(?:把)?\s*"
                    r"(?:(?:桌面上|桌面)(?:的)?)?\s*(?:the\s+)?",
                    "",
                    value,
                    flags=re.IGNORECASE,
                )
                if value:
                    return value
        return task.strip()


def create_skill() -> ChatGPTPaperAbstractSkill:
    return ChatGPTPaperAbstractSkill()
