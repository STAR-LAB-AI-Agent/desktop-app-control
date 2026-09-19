"""以确定性的键盘流程启动桌面应用。"""

from __future__ import annotations

import ctypes
import os
import time
from typing import Any, Callable

import pyautogui

from .base import ToolSpec
from .keyboard import KeyboardTools


APPLICATION_PROCESS_NAMES = {
    "钉钉": {"dingtalk.exe"},
    "dingtalk": {"dingtalk.exe"},
    "edge": {"msedge.exe"},
    "microsoft edge": {"msedge.exe"},
    "qq音乐": {"qqmusic.exe"},
    "chatgpt": {"chatgpt.exe"},
}


def application_window_status(app_name: str, *, activate: bool = False) -> dict[str, Any] | None:
    """用进程和顶层窗口确认应用已运行，必要时恢复其主窗口。"""
    if not hasattr(ctypes, "windll"):
        return None
    requested = app_name.strip().casefold()
    expected_processes = APPLICATION_PROCESS_NAMES.get(requested, set())
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    candidates: list[tuple[int, int, int, str, str]] = []
    matched_process = ""
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def process_name(hwnd) -> str:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return ""
        try:
            size = ctypes.c_ulong(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return os.path.basename(buffer.value).casefold()
            return ""
        finally:
            kernel32.CloseHandle(process)

    def collect(hwnd, _):
        nonlocal matched_process
        proc = process_name(hwnd)
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
        matches = proc in expected_processes or requested in title.casefold()
        if not matches:
            return True
        matched_process = proc or matched_process
        rect = (ctypes.c_long * 4)()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = max(0, rect[2] - rect[0])
        height = max(0, rect[3] - rect[1])
        usable = width >= 300 and height >= 200
        visible = bool(user32.IsWindowVisible(hwnd))
        iconic = bool(user32.IsIconic(hwnd))
        # Edge 关闭主窗口后仍可能保留 MSCTFIME UI、Default IME 等 0×0 的输入法
        # 辅助窗口。它们属于 msedge.exe，但不能代表浏览器已经显示。
        if not usable:
            return True
        # 浏览器等多进程应用会创建若干无标题的辅助顶层窗口。优先选择有标题的
        # 可见主窗口，否则可能把一个渲染辅助窗口当成浏览器并错误报告激活成功。
        if visible and usable and title:
            priority = 6
        elif visible and usable:
            priority = 5
        elif iconic and usable and title:
            priority = 4
        elif iconic and usable:
            priority = 3
        else:
            priority = 2
        candidates.append((priority, width * height, int(hwnd), title, proc))
        return True

    user32.EnumWindows(callback_type(collect), 0)
    if not candidates and not matched_process:
        return None
    best = max(candidates) if candidates else None
    visible = False
    title = ""
    hwnd = None
    if best is not None:
        _, _, hwnd, title, proc = best
        matched_process = proc or matched_process
        if activate:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            target_thread = user32.GetWindowThreadProcessId(hwnd, None)
            foreground = user32.GetForegroundWindow()
            foreground_thread = (
                user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
            )
            current_thread = kernel32.GetCurrentThreadId()
            attached_foreground = bool(
                foreground_thread
                and foreground_thread != current_thread
                and user32.AttachThreadInput(current_thread, foreground_thread, True)
            )
            attached_target = bool(
                target_thread
                and target_thread != current_thread
                and target_thread != foreground_thread
                and user32.AttachThreadInput(current_thread, target_thread, True)
            )
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
            finally:
                if attached_target:
                    user32.AttachThreadInput(current_thread, target_thread, False)
                if attached_foreground:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            time.sleep(0.15)
        visible = bool(user32.IsWindowVisible(hwnd))
    foreground_hwnd = int(user32.GetForegroundWindow() or 0)
    foreground = False
    if hwnd and foreground_hwnd:
        target_pid = ctypes.c_ulong()
        foreground_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
        user32.GetWindowThreadProcessId(foreground_hwnd, ctypes.byref(foreground_pid))
        foreground = bool(target_pid.value and target_pid.value == foreground_pid.value)
    return {
        "verified_open": True,
        "foreground": foreground,
        "process_name": matched_process,
        "window_title": title,
        "window_visible": visible,
        "window_handle": hwnd,
    }


class ApplicationTools:
    """把会暴露中间 GUI 状态的应用搜索压缩成一个原子工具。"""

    def __init__(
        self,
        cancel_check: Callable[[], None] | None = None,
        *,
        search_delay: float = 0.4,
        launch_delay: float = 1.5,
    ) -> None:
        self.cancel_check = cancel_check
        self.search_delay = max(0.0, float(search_delay))
        self.launch_delay = max(0.0, float(launch_delay))

    def _check_cancelled(self) -> None:
        if self.cancel_check is not None:
            self.cancel_check()

    def _pause_interruptibly(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def open_app_via_windows_search(self, app_name: str) -> dict[str, Any]:
        if not isinstance(app_name, str):
            raise TypeError("app_name 必须是字符串")
        name = app_name.strip()
        if not name:
            raise ValueError("app_name 不能为空")
        if "\n" in name or "\r" in name:
            raise ValueError("app_name 必须是单行软件名称")
        if len(name) > 100:
            raise ValueError("app_name 不得超过 100 个字符")

        self._check_cancelled()
        existing = application_window_status(name, activate=True)
        if existing is not None and existing.get("foreground", True):
            return {
                "ok": True,
                "app_name": name,
                "method": "existing_process_or_window",
                "already_running": True,
                "ignored_search_history": True,
                **existing,
            }

        pyautogui.hotkey("win", "s")
        self._pause_interruptibly(self.search_delay)

        # 不读取、不点击搜索历史或推荐项；覆盖可能残留的旧查询，只提交明确的软件名。
        pyautogui.hotkey("ctrl", "a")
        KeyboardTools.type_text(name)
        self._check_cancelled()
        pyautogui.press("enter")
        self._pause_interruptibly(self.launch_delay)

        status = application_window_status(name, activate=True)
        deadline = time.monotonic() + 3.0
        while (
            (status is None or not status.get("foreground", True))
            and time.monotonic() < deadline
        ):
            self._pause_interruptibly(0.2)
            status = application_window_status(name, activate=True)

        foreground_verified = bool(status and status.get("foreground", True))
        return {
            "ok": foreground_verified,
            "app_name": name,
            "method": "windows_search_keyboard",
            "already_running": False,
            "verified_open": status is not None,
            "foreground": foreground_verified,
            "focus_failed": status is not None and not foreground_verified,
            "ignored_search_history": True,
            **(status or {}),
        }

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "open_app_via_windows_search",
                (
                    "通过一次原子键盘流程启动软件：Win+S、覆盖旧查询、输入软件名、按 Enter；"
                    "全程不点击搜索历史、推荐项或任务栏图标"
                ),
                {
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 100,
                            "description": "Windows 搜索使用的准确软件名",
                        }
                    },
                    "required": ["app_name"],
                    "additionalProperties": False,
                },
                self.open_app_via_windows_search,
            )
        ]
