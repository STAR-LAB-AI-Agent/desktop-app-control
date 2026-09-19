"""音乐播放的独立动态验收，不以一次按钮识别作为播放证据。"""
import ctypes
import os
import re
import time

import pyautogui
from PIL import Image, ImageChops

from .base import RecoverableToolError, ToolSpec
from .keyboard import KeyboardTools
from .mouse import STALE_SCREEN_THRESHOLD
from .monitor import _screen_change_score
from .system import SystemTools
from .media_session import read_media_sessions, matching_session, resume_media_session


def find_qq_music_window() -> int | None:
    """只查找 QQ 音乐真正的主窗口，不改变窗口状态。"""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    handles: list[tuple[int, int, int]] = []
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
            if kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(size)
            ):
                return os.path.basename(buffer.value).casefold()
            return ""
        finally:
            kernel32.CloseHandle(process)

    def collect(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.casefold()
        if ("qq音乐" in title or "qqmusic" in title
                or process_name(hwnd) == "qqmusic.exe"):
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            window_class = class_buffer.value.casefold()
            rect = (ctypes.c_long * 4)()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = max(0, rect[2] - rect[0])
            height = max(0, rect[3] - rect[1])
            visible = bool(user32.IsWindowVisible(hwnd))
            iconic = bool(user32.IsIconic(hwnd))
            # 优先选择当前屏幕上可见的大主窗口。QQMusic 可能同时保留一个
            # 最小化到 (-32000, -32000) 的旧顶层句柄；若优先选它，播放进度
            # 检测会裁到屏幕外并把正在播放误判为暂停。
            if iconic or (width >= 700 and height >= 400 and rect[2] > 0 and rect[3] > 0):
                usable_visible = (
                    visible and not iconic and width >= 700 and height >= 400
                    and rect[2] > 0 and rect[3] > 0
                )
                is_main_window = window_class == "txguifoundation"
                if is_main_window and usable_visible:
                    priority = 5
                elif is_main_window and iconic:
                    priority = 4
                else:
                    priority = 3 if usable_visible else (2 if iconic else 1)
                handles.append((priority, width * height, int(hwnd)))
        return True

    user32.EnumWindows(callback_type(collect), 0)
    if not handles:
        return None
    return max(handles)[2]


def activate_qq_music_window() -> int | None:
    """显示并临时置顶 QQ 音乐，返回真正的主窗口句柄。"""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = find_qq_music_window()
    if hwnd is None:
        return None
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE：同时恢复最小化或隐藏到托盘的主窗口
    # 临时置顶可以盖住腾讯会议等 always-on-top 浮窗；操作结束后会撤销。
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached: list[int] = []
    try:
        # Windows 会拒绝普通后台进程直接抢前台。临时合并输入线程后再激活，
        # 可确保后续键盘输入不会落到 VS Code 或终端。
        for thread_id in {target_thread, foreground_thread}:
            if thread_id and thread_id != current_thread:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached.append(thread_id)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for thread_id in attached:
            user32.AttachThreadInput(current_thread, thread_id, False)
    return hwnd if user32.IsWindowVisible(hwnd) else None


def is_qq_music_foreground(hwnd: int | None) -> bool:
    """Check the owning process, because QQMusic may focus a child top-level window."""
    if hwnd is None or not hasattr(ctypes, "windll"):
        return False
    user32 = ctypes.windll.user32
    foreground = user32.GetForegroundWindow()
    if not foreground or not user32.IsWindowVisible(hwnd):
        return False
    target_pid = ctypes.c_ulong()
    foreground_pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
    user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
    return bool(target_pid.value and target_pid.value == foreground_pid.value)


def release_qq_music_topmost(hwnd: int | None) -> None:
    """撤销搜索期间设置的置顶状态。"""
    if hwnd is None or not hasattr(ctypes, "windll"):
        return
    ctypes.windll.user32.SetWindowPos(
        hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040
    )


def qq_music_search_fallback_point(hwnd: int) -> tuple[int, int] | None:
    """Return a window-relative search-box point when visual locating is uncertain."""
    rect = qq_music_window_rect(hwnd)
    if rect is None:
        return None
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    if width < 700 or height < 400:
        return None
    # QQ 音乐的搜索框位于标题栏中部。坐标相对于当前窗口计算，移动窗口后仍然有效。
    return left + round(width * 0.425), top + max(48, round(height * 0.052))


def qq_music_window_rect(hwnd: int | None) -> tuple[int, int, int, int] | None:
    if hwnd is None or not hasattr(ctypes, "windll"):
        return None
    rect = (ctypes.c_long * 4)()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    left, top, right, bottom = map(int, rect)
    if right <= left or bottom <= top:
        return None
    # 本进程未声明 DPI aware 时，GetWindowRect 返回逻辑坐标，而
    # PyAutoGUI 的截图和鼠标使用物理像素。按目标窗口 DPI 换算，避免在
    # 125%/150% 缩放下搜索框与进度条区域整体偏移。
    try:
        awareness = ctypes.c_int(-1)
        result = ctypes.windll.shcore.GetProcessDpiAwareness(
            0, ctypes.byref(awareness)
        )
        if result == 0 and awareness.value == 0:
            dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd)) or 96
            scale = dpi / 96.0
            left, top, right, bottom = (
                round(left * scale), round(top * scale),
                round(right * scale), round(bottom * scale),
            )
    except (AttributeError, OSError):
        pass
    return left, top, right, bottom


def progress_region_change(
    before: Image.Image,
    after: Image.Image,
    window_rect: tuple[int, int, int, int] | None,
) -> dict[str, object]:
    """直接比较播放器已播时间和进度条，避免视觉模型把 00:01 误读成 00:31。"""
    if window_rect is None or before.size != after.size:
        return {"changed": False, "changed_pixels": 0, "change_ratio": 0.0,
                "window_rect": window_rect, "sample_box": None}
    left, top, right, bottom = window_rect
    width = right - left
    height = bottom - top
    if width < 700 or height < 400:
        return {"changed": False, "changed_pixels": 0, "change_ratio": 0.0,
                "window_rect": window_rect, "sample_box": None}
    # QQ 音乐底栏中“已播放时间 + 进度条起始段”的窗口相对区域。
    box = (
        max(0, left + round(width * 0.43)),
        max(0, bottom - max(75, round(height * 0.07))),
        min(before.width, left + round(width * 0.64)),
        min(before.height, bottom - max(14, round(height * 0.015))),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return {"changed": False, "changed_pixels": 0, "change_ratio": 0.0,
                "window_rect": window_rect, "sample_box": box}
    first = before.convert("L").crop(box)
    last = after.convert("L").crop(box)
    difference = ImageChops.difference(first, last)
    histogram = difference.histogram()
    changed_pixels = sum(histogram[2:])
    total_pixels = max(1, first.width * first.height)
    ratio = changed_pixels / total_pixels
    return {
        "changed": changed_pixels >= 6,
        "changed_pixels": changed_pixels,
        "change_ratio": round(ratio, 8),
        "window_rect": window_rect,
        "sample_box": box,
    }


def needs_music_verification(task: str) -> bool:
    if re.search(r"暂停|停止|不要播放|别播放|不要听", task):
        return False
    return bool(re.search(r"听|放歌|播歌|音乐|歌曲|歌单|单曲|play\s+(?:music|song)", task, re.I))


def extract_music_query(task: str) -> str:
    """从常见听歌表达中提取歌曲名，供自动搜索恢复使用。"""
    value = str(task or "").strip()
    value = re.sub(
        r"^(?:请|帮我|我想|我要|请帮我)?\s*(?:听|播放|放|搜|搜索)(?:一下|一首|歌曲)?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?:这首歌|这首歌曲|歌曲|歌)$", "", value).strip(" ：:，,。.!！")
    return value or str(task or "").strip()


def elapsed_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,3}:[0-5]\d", value):
        return None
    minutes, seconds = value.split(":")
    return int(minutes) * 60 + int(seconds)


def playback_state(evidence, interval, *, progress_changed: bool = False):
    if not isinstance(evidence, dict):
        return "unknown"
    if evidence.get("blocked") is True:
        return "blocked"
    if evidence.get("target_matches_before") is not True or evidence.get("target_matches_after") is not True:
        return "unknown"
    # 三角形代表可以开始播放，即目前暂停；双竖线才是暂停操作按钮。
    if evidence.get("control_after") == "play_triangle":
        return "paused"
    # 本地截图像素变化比模型 OCR 时间更可靠。双竖线存在且底部进度区域发生变化，
    # 即可证明当前曲目在验收窗口内实际播放过。
    if evidence.get("control_after") == "pause_bars" and progress_changed:
        return "playing"
    before = elapsed_seconds(evidence.get("elapsed_before"))
    after = elapsed_seconds(evidence.get("elapsed_after"))
    # 观察窗口约 3 秒。若时间完全不动，即使模型把小图标误读成
    # pause_bars，也应优先按暂停处理，进入恢复播放流程，而不是继续
    # 无限验收并最终撞上调用上限。
    if (evidence.get("control_after") == "pause_bars"
            and before is not None and after is not None and after == before):
        return "paused"
    if (evidence.get("control_after") == "pause_bars" and before is not None
            and after is not None and 1 <= after - before <= interval + 2):
        return "playing"
    return "unknown"


class MusicTools:
    def __init__(self, locator, monitor):
        self.locator = locator
        self.monitor = monitor

    def _focus_qq_music(self) -> int:
        """把 QQ 音乐重新置于前台，避免 VS Code 等窗口抢走截图焦点。"""
        self.monitor.raise_if_cancelled()
        hwnd = activate_qq_music_window()
        if hwnd is not None:
            SystemTools(self.monitor.raise_if_cancelled).wait(0.4)
            if is_qq_music_foreground(hwnd):
                return hwnd
            raise RecoverableToolError("QQ 音乐窗口未能取得前台焦点，已停止输入以避免误操作其他窗口")
        # 首次运行时窗口尚不存在，才通过 Windows 搜索启动；启动后再用
        # 原生窗口句柄激活，避免 Enter 后焦点回到 VS Code。
        pyautogui.hotkey("win", "s")
        SystemTools(self.monitor.raise_if_cancelled).wait(0.5)
        pyautogui.hotkey("ctrl", "a")
        KeyboardTools.type_text("QQ音乐")
        pyautogui.press("enter")
        SystemTools(self.monitor.raise_if_cancelled).wait(2.0)
        hwnd = activate_qq_music_window()
        SystemTools(self.monitor.raise_if_cancelled).wait(0.4)
        if hwnd is None or not is_qq_music_foreground(hwnd):
            raise RecoverableToolError("QQ 音乐启动后仍无法取得主窗口，未执行搜索")
        return hwnd

    def search_music_query(self, query: str):
        """在当前 QQ 音乐窗口中搜索并双击准确匹配的歌曲标题。"""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        query = query.strip()
        self.monitor.raise_if_cancelled()
        hwnd = self._focus_qq_music()
        try:
            before = pyautogui.screenshot()
            fallback = qq_music_search_fallback_point(hwnd)
            if fallback is None:
                raise RecoverableToolError("无法读取 QQ 音乐主窗口位置，未执行搜索")
            search_x, search_y = fallback
            search_method = "window_relative"

            # 显式移动再点击，既能保证输入焦点，也便于演示时观察实际操作。
            if not is_qq_music_foreground(hwnd):
                raise RecoverableToolError("点击搜索框前 QQ 音乐失去前台焦点，已停止输入")
            pyautogui.moveTo(search_x, search_y, duration=0.25)
            pyautogui.click()
            SystemTools(self.monitor.raise_if_cancelled).wait(0.2)
            KeyboardTools.submit_search_query(query)
            SystemTools(self.monitor.raise_if_cancelled).wait(1.8)

            results = pyautogui.screenshot()
            self.monitor.save_artifact(results, "music_search_results")
            result_point = self.locator.locate(
                results,
                f"QQ 音乐搜索结果歌曲列表中，标题严格等于《{query}》的第一首歌曲标题文字中央；不要选择歌手、歌单、搜索框、页面上方播放按钮或底部播放器",
            )
            self.monitor.raise_if_cancelled()
            if result_point.confidence < 0.70:
                SystemTools(self.monitor.raise_if_cancelled).wait(0.8)
                results = pyautogui.screenshot()
                result_point = self.locator.locate(
                    results,
                    f"QQ 音乐搜索结果歌曲列表中，标题严格等于《{query}》的第一首歌曲标题文字中央；不要选择歌手、歌单、搜索框、页面上方播放按钮或底部播放器",
                )
                self.monitor.raise_if_cancelled()
            if result_point.confidence < 0.70:
                raise RecoverableToolError(
                    f"已提交《{query}》，但未能可靠定位同名歌曲行，confidence={result_point.confidence:.2f}"
                )

            if not is_qq_music_foreground(hwnd):
                activate_qq_music_window()
                SystemTools(self.monitor.raise_if_cancelled).wait(0.2)
            current = pyautogui.screenshot()
            if not is_qq_music_foreground(hwnd):
                raise RecoverableToolError("点击歌曲前 QQ 音乐失去前台焦点，已停止操作")
            if _screen_change_score(results, current) >= STALE_SCREEN_THRESHOLD:
                raise RecoverableToolError("歌曲定位后画面发生变化，未执行双击")
            pyautogui.moveTo(result_point.x, result_point.y, duration=0.25)
            pyautogui.doubleClick(interval=0.12)
            SystemTools(self.monitor.raise_if_cancelled).wait(1.2)
            after = pyautogui.screenshot()
            change_score = _screen_change_score(results, after)
            return {
                "ok": True,
                "query": query,
                "submitted": True,
                "result_clicked": True,
                "play_command_sent": True,
                "method": f"{search_method}_search_double_click_title",
                "change_score": round(change_score, 6),
            }
        finally:
            release_qq_music_topmost(hwnd)

    def inspect_music_playback(self, task: str):
        self.monitor.raise_if_cancelled()
        window_rect = qq_music_window_rect(find_qq_music_window())
        native_before = read_media_sessions()
        before = pyautogui.screenshot()
        started = time.monotonic()
        before_path = self.monitor.save_artifact(before, "music_before")
        SystemTools(self.monitor.raise_if_cancelled).wait(3)
        after = pyautogui.screenshot()
        interval = time.monotonic() - started
        after_path = self.monitor.save_artifact(after, "music_after")
        native_after = read_media_sessions()
        progress_evidence = progress_region_change(before, after, window_rect)
        pair = Image.new("RGB", (max(before.width, after.width), before.height + after.height), "white")
        pair.paste(before, (0, 0))
        pair.paste(after, (0, before.height))
        prompt = f"""独立核对音乐播放状态。用户原始任务：{task}
图片上半部为之前截图，下半部为约{interval:.1f}秒后的截图。
只读取底部当前播放器或播放详情中的证据，不用搜索框、搜索结果、专辑封面推断正在播放。
分别核对当前播放歌曲是否符合用户要求（若指定歌手也必须匹配）。
逐字读取两张图的已播放时间 mm:ss，不要读取总时长、系统时钟、歌词或猜测缺失数字。
控制按钮三角形表示当前可播放，双竖线表示当前可暂停。不要根据任务预期反推图标。
时间不可见填 null，按钮不清楚填 unknown。登录、会员、付费限制填 blocked=true。
只返回 JSON：{{"target_matches_before":false,"target_matches_after":false,
"elapsed_before":null,"elapsed_after":null,"control_after":"play_triangle或pause_bars或unknown",
"blocked":false,"observation":"简述实际看到的图标和时间"}}"""
        try:
            evidence = self.locator.ask_json(pair, prompt)
        except (ValueError, TypeError):
            evidence = {"observation": "状态识别响应无效，不能确认播放"}
        self.monitor.raise_if_cancelled()
        visual_state = playback_state(
            evidence,
            interval,
            progress_changed=bool(progress_evidence["changed"]),
        )
        first = matching_session(task, native_before["sessions"])
        last = matching_session(task, native_after["sessions"])
        # 模型可以误读甚至编造时间；视觉结果绝不能单独授权 finish。
        state = "unknown"
        verification_source = "windows_media_session"
        if native_after.get("available") and native_after.get("sessions") and not last:
            # 有媒体会话但当前曲目与用户要求不一致，明确告诉工作流重新搜索，
            # 不要把“旧歌暂停”当成目标歌曲状态继续验收。
            state = "wrong_track"
        elif last and last["state"] == "paused":
            state = "paused"
        elif (first and last and first["app"] == last["app"]
              and first["title"] == last["title"] and first["artist"] == last["artist"]
              and first["state"] == last["state"] == "playing"
              and isinstance(evidence, dict)
              and evidence.get("target_matches_before") is True
              and evidence.get("target_matches_after") is True):
            state = "playing"
        elif visual_state in ("paused", "playing", "blocked"):
            state = visual_state
            if not native_before.get("available") or not native_after.get("available"):
                verification_source = (
                    "screenshot_pixel_progress"
                    if visual_state == "playing" and progress_evidence["changed"]
                    else "screenshot_fallback"
                )
        return {"ok": state == "playing", "state": state, "evidence": evidence,
                "verification_source": verification_source,
                "progress_evidence": progress_evidence,
                "native_before": native_before, "native_after": native_after,
                "before_image": str(before_path) if before_path else None,
                "after_image": str(after_path) if after_path else None,
                "instruction": "wrong_track 时重新搜索并点击目标歌曲；paused 时优先调用 resume_music_playback 恢复播放，再复查。unknown 表示缺少可靠证据，不要反复切换播放按钮或凭截图宣告成功。遇到会员或登录限制应停止并说明受阻。"}

    def resume_music_playback(self, task: str):
        self.monitor.raise_if_cancelled()
        before = read_media_sessions()
        result = resume_media_session(task)
        self.monitor.raise_if_cancelled()
        # playpause 是切换键，不是“只播放”命令。状态检测一旦误判，它会把
        # 已经播放的歌曲暂停，因此 WinRT 不可用时绝不发送该兜底按键。
        fallback_key_sent = False
        after = read_media_sessions()
        if result.get("state") != "playing":
            matched = matching_session(task, after.get("sessions", []))
            if matched and matched.get("state") == "playing":
                result = {**result, "ok": True, "state": "playing"}
        return {
            "ok": result.get("ok") is True,
            "state": result.get("state", "unknown"),
            "command_sent": result.get("command_sent", False),
            "fallback_key_sent": fallback_key_sent,
            "before": before,
            "after": after,
            "result": result,
            "instruction": "若 state 仍不是 playing，继续观察界面，不要凭一次播放命令报告完成。",
        }

    def specs(self):
        task_parameters = {"type": "object", "properties": {"task": {"type": "string"}},
                           "required": ["task"], "additionalProperties": False}
        return [
            ToolSpec(
                "search_music_query",
                "重新定位 QQ 音乐顶部搜索框，覆盖旧搜索词并提交新歌曲；听歌任务优先使用，不要先反复 click_target 搜索框",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 2000}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                self.search_music_query,
            ),
            ToolSpec(
                "inspect_music_playback",
                "读取 Windows 媒体会话并间隔复核当前歌曲，截图仅作辅助，系统证据不足时不确认播放",
                task_parameters,
                self.inspect_music_playback,
            ),
            ToolSpec(
                "resume_music_playback",
                "对唯一匹配当前任务歌名的 Windows 媒体会话发送播放命令，用于 paused 状态恢复播放，避免点击小播放按钮",
                task_parameters,
                self.resume_music_playback,
            ),
        ]
