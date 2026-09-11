"""键盘和文本输入工具。"""

from __future__ import annotations

import time
from typing import Any

import pyautogui

from .base import ToolSpec


class KeyboardTools:
    @staticmethod
    def type_text(text: str, interval: float = 0.02) -> dict[str, Any]:
        if len(text) > 2000:
            raise ValueError("单次输入不得超过 2000 个字符")
        try:
            import pyperclip
        except ImportError:
            pyperclip = None

        if pyperclip is None:
            if not text.isascii():
                raise RuntimeError("输入中文需要安装 pyperclip")
            pyautogui.write(text, interval=interval)
            return {"ok": True, "characters": len(text)}

        try:
            old_clipboard = pyperclip.paste()
        except pyperclip.PyperclipException:
            old_clipboard = None
        try:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
        finally:
            if old_clipboard is not None:
                pyperclip.copy(old_clipboard)
        return {"ok": True, "characters": len(text)}

    @staticmethod
    def press_key(key: str) -> dict[str, Any]:
        pyautogui.press(key)
        return {"ok": True, "key": key}

    @classmethod
    def submit_search_query(cls, query: str) -> dict[str, Any]:
        """在已聚焦的搜索框中覆盖旧内容并直接提交，不暴露建议列表给规划器。"""
        if not isinstance(query, str):
            raise TypeError("query 必须是字符串")
        text = query.strip()
        if not text:
            raise ValueError("query 不能为空")
        if "\n" in text or "\r" in text:
            raise ValueError("query 必须是单行搜索内容")
        if len(text) > 2000:
            raise ValueError("query 不得超过 2000 个字符")

        pyautogui.hotkey("ctrl", "a")
        cls.type_text(text)
        pyautogui.press("enter")
        return {
            "ok": True,
            "query": text,
            "submitted": True,
            "ignored_suggestions": True,
        }

    @staticmethod
    def hotkey(keys: list[str]) -> dict[str, Any]:
        if not keys or len(keys) > 4:
            raise ValueError("快捷键必须包含 1 到 4 个按键")
        pyautogui.hotkey(*keys)
        return {"ok": True, "keys": keys}

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "type_text",
                "向当前获得焦点的输入框输入文本",
                {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                self.type_text,
            ),
            ToolSpec(
                "press_key",
                "按下单个键，例如 enter、esc 或 tab",
                {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                    "additionalProperties": False,
                },
                self.press_key,
            ),
            ToolSpec(
                "submit_search_query",
                (
                    "在已聚焦的搜索框中原子完成覆盖旧内容、输入查询和按 Enter；"
                    "不要与自动补全、搜索历史或推荐项交互"
                ),
                {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2000,
                            "description": "用户要求搜索的准确内容",
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                self.submit_search_query,
            ),
            ToolSpec(
                "hotkey",
                "按下快捷键组合",
                {
                    "type": "object",
                    "properties": {
                        "keys": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["keys"],
                    "additionalProperties": False,
                },
                self.hotkey,
            ),
        ]
