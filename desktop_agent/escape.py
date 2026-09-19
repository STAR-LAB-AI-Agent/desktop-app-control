"""全局 Esc 强制停止监听器。

任务窗口在执行时会自动最小化，因此 Tk 的普通 ``<Escape>`` 绑定收不到
按键。Windows 的 ``GetAsyncKeyState`` 可以在后台线程读取 Esc 的按下沿，
再调用当前任务的取消回调，不需要额外安装键盘钩子包。
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from typing import Callable, Any


class EscapeStopListener:
    """监听一次 Esc 按下事件并调用 ``on_escape``。"""

    def __init__(self, on_escape: Callable[[], Any], *, poll_interval: float = 0.02) -> None:
        self.on_escape = on_escape
        self.poll_interval = max(0.01, float(poll_interval))
        self._stop_event = threading.Event()
        self.triggered = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def start(self) -> "EscapeStopListener":
        if not self.supported or self._thread is not None:
            return self
        self._stop_event.clear()
        self.triggered.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="desktop-agent-escape-stop",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)

    def _run(self) -> None:
        try:
            get_async_key_state = ctypes.windll.user32.GetAsyncKeyState
        except (AttributeError, OSError):
            return

        # 先清除 GetAsyncKeyState 的历史低位。否则监听器启动之前的一次 Esc
        # 也可能在任务开始后被误认为新的人工终止操作。
        get_async_key_state(0x1B)
        was_pressed = False
        while not self._stop_event.is_set():
            state = int(get_async_key_state(0x1B))
            pressed = bool(state & 0x8000)
            pressed_since_last_poll = bool(state & 0x0001)
            if (pressed or pressed_since_last_poll) and not was_pressed:
                self.triggered.set()
                try:
                    self.on_escape()
                except Exception:
                    # 停止动作不能让监听线程异常退出主任务；实际任务会在
                    # 下一次取消检查点抛出 TaskCancelledError。
                    pass
            was_pressed = pressed
            time.sleep(self.poll_interval)

    def __enter__(self) -> "EscapeStopListener":
        return self.start()

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.stop()
