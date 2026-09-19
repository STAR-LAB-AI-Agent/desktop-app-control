"""只读文件发现工具。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .base import ToolSpec


class FileTools:
    @staticmethod
    def find_desktop_file(query: str, extension: str = ".pdf") -> dict[str, Any]:
        normalized_query = _normalize(query)
        normalized_extension = extension.lower()
        if normalized_extension and not normalized_extension.startswith("."):
            normalized_extension = "." + normalized_extension

        if not normalized_query:
            return {
                "ok": False,
                "status": "invalid_query",
                "query": query,
                "count": 0,
                "matches": [],
                "ambiguous": False,
                "reason": "文件查询名称不能为空",
            }

        ranked_matches: list[tuple[int, Path]] = []
        for desktop in _desktop_directories():
            for path in desktop.iterdir():
                if not path.is_file():
                    continue
                if normalized_extension and path.suffix.lower() != normalized_extension:
                    continue
                normalized_name = _normalize(path.stem)
                rank = _match_rank(normalized_query, normalized_name)
                if rank:
                    ranked_matches.append((rank, path.resolve()))

        best_rank = max((rank for rank, _ in ranked_matches), default=0)
        unique_matches = sorted(
            {str(path) for rank, path in ranked_matches if rank == best_rank}
        )
        status = (
            "found"
            if len(unique_matches) == 1
            else "ambiguous"
            if len(unique_matches) > 1
            else "not_found"
        )
        return {
            "ok": len(unique_matches) == 1,
            "status": status,
            "query": query,
            "count": len(unique_matches),
            "matches": unique_matches[:10],
            "ambiguous": len(unique_matches) > 1,
            "match_method": _MATCH_METHODS.get(best_rank),
            "reason": (
                "找到唯一匹配文件"
                if status == "found"
                else "匹配到多个同等候选文件，不能自动选择"
                if status == "ambiguous"
                else "桌面上没有匹配的 PDF 文件"
            ),
        }

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "find_desktop_file",
                "在 Windows 桌面中查找与名称匹配的文件；只读取文件名，不打开或上传",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "extension": {"type": "string", "default": ".pdf"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                self.find_desktop_file,
            )
        ]


def _desktop_directories() -> list[Path]:
    candidates = [Path.home() / "Desktop"]
    for variable in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Desktop")
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if candidate.is_dir() and key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def _normalize(value: str) -> str:
    value = re.sub(r"(?i)\.pdf$", "", value)
    value = value.replace("论文", "")
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value).lower()


_VISUAL_CONFUSABLES = str.maketrans({"o": "0", "i": "1", "l": "1"})
_MATCH_METHODS = {
    4: "exact",
    3: "substring",
    2: "visual_confusable_exact",
    1: "visual_confusable_substring",
}


def _match_rank(query: str, name: str) -> int:
    if not query or not name:
        return 0
    if query == name:
        return 4
    if query in name or name in query:
        return 3

    visual_query = query.translate(_VISUAL_CONFUSABLES)
    visual_name = name.translate(_VISUAL_CONFUSABLES)
    if visual_query == visual_name:
        return 2
    if visual_query in visual_name or visual_name in visual_query:
        return 1
    return 0
