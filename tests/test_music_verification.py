import unittest
from unittest.mock import Mock, patch
from PIL import Image
from desktop_agent.tools.music import (
    MusicTools,
    needs_music_verification,
    playback_state,
    progress_region_change,
)
from desktop_agent.tools.base import ToolRegistry, ToolSpec
from desktop_agent.task import TaskRequest
from desktop_agent.workflows import GeneralTaskWorkflow


class MusicVerificationTests(unittest.TestCase):
    def test_music_search_tool_locates_and_submits_once(self):
        locator = Mock()
        locator.locate.return_value = type(
            "Point", (), {"x": 220, "y": 160, "confidence": 0.95}
        )()
        monitor = Mock()
        screenshot = Image.new("RGB", (10, 10))
        with patch("desktop_agent.tools.music.pyautogui.screenshot", return_value=screenshot), \
             patch("desktop_agent.tools.music.activate_qq_music_window", return_value=123), \
             patch("desktop_agent.tools.music.is_qq_music_foreground", return_value=True), \
             patch("desktop_agent.tools.music.qq_music_search_fallback_point", return_value=(500, 80)), \
             patch("desktop_agent.tools.music.release_qq_music_topmost") as release, \
             patch("desktop_agent.tools.music.pyautogui.moveTo") as move_to, \
             patch("desktop_agent.tools.music.pyautogui.click") as click, \
             patch("desktop_agent.tools.music.pyautogui.doubleClick") as double_click, \
             patch("desktop_agent.tools.music.KeyboardTools.submit_search_query") as submit, \
             patch("desktop_agent.tools.music.SystemTools.wait"):
            result = MusicTools(locator, monitor).search_music_query("迷失的季节")
        self.assertTrue(result["ok"])
        self.assertTrue(result["play_command_sent"])
        submit.assert_called_once_with("迷失的季节")
        self.assertEqual(move_to.call_count, 2)
        self.assertEqual(click.call_count, 1)
        double_click.assert_called_once_with(interval=0.12)
        locator.locate.assert_called_once()
        release.assert_called_once_with(123)

    def test_music_search_uses_current_window_relative_point(self):
        locator = Mock()
        locator.locate.return_value = type(
            "Point", (), {"x": 220, "y": 160, "confidence": 0.95}
        )()
        monitor = Mock()
        screenshot = Image.new("RGB", (10, 10))
        with patch("desktop_agent.tools.music.pyautogui.screenshot", return_value=screenshot), \
             patch("desktop_agent.tools.music.activate_qq_music_window", return_value=123), \
             patch("desktop_agent.tools.music.is_qq_music_foreground", return_value=True), \
             patch("desktop_agent.tools.music.qq_music_search_fallback_point", return_value=(500, 80)), \
             patch("desktop_agent.tools.music.release_qq_music_topmost"), \
             patch("desktop_agent.tools.music.pyautogui.moveTo") as move_to, \
             patch("desktop_agent.tools.music.pyautogui.click"), \
             patch("desktop_agent.tools.music.pyautogui.doubleClick"), \
             patch("desktop_agent.tools.music.KeyboardTools.submit_search_query"), \
             patch("desktop_agent.tools.music.SystemTools.wait"):
            result = MusicTools(locator, monitor).search_music_query("迷失的季节")
        move_to.assert_any_call(500, 80, duration=0.25)
        self.assertEqual(result["method"], "window_relative_search_double_click_title")

    def test_music_search_failure_never_sends_escape(self):
        locator = Mock()
        locator.locate.return_value = type(
            "Point", (), {"x": 220, "y": 160, "confidence": 0.10}
        )()
        monitor = Mock()
        screenshot = Image.new("RGB", (10, 10))
        with patch("desktop_agent.tools.music.pyautogui.screenshot", return_value=screenshot), \
             patch("desktop_agent.tools.music.activate_qq_music_window", return_value=123), \
             patch("desktop_agent.tools.music.is_qq_music_foreground", return_value=True), \
             patch("desktop_agent.tools.music.qq_music_search_fallback_point", return_value=(500, 80)), \
             patch("desktop_agent.tools.music.release_qq_music_topmost"), \
             patch("desktop_agent.tools.music.pyautogui.moveTo"), \
             patch("desktop_agent.tools.music.pyautogui.click"), \
             patch("desktop_agent.tools.music.pyautogui.press") as press, \
             patch("desktop_agent.tools.music.KeyboardTools.submit_search_query"), \
             patch("desktop_agent.tools.music.SystemTools.wait"):
            with self.assertRaisesRegex(Exception, "歌曲行"):
                MusicTools(locator, monitor).search_music_query("迷失的季节")
        press.assert_not_called()

    def test_resume_without_winrt_never_toggles_media_key(self):
        unavailable = {
            "available": False,
            "sessions": [],
            "error": "ModuleNotFoundError: No module named 'winrt'",
        }
        with patch("desktop_agent.tools.music.read_media_sessions", return_value=unavailable), \
             patch("desktop_agent.tools.music.resume_media_session", return_value={
                 "ok": False, "state": "unknown", "command_sent": False,
             }), patch("desktop_agent.tools.music.pyautogui.press") as press:
            result = MusicTools(Mock(), Mock()).resume_music_playback("我要听挪威的森林")
        press.assert_not_called()
        self.assertFalse(result["fallback_key_sent"])
        self.assertEqual(result["state"], "unknown")
    def test_hallucinated_visual_progress_never_overrides_native_state(self):
        for sessions, expected in [([], "unknown"),
                                   ([{"title": "挪威的森林", "artist": "伍佰", "app": "music", "state": "paused"}], "paused")]:
            with self.subTest(expected=expected):
                locator = Mock()
                locator.ask_json.return_value = self.evidence()
                monitor = Mock()
                monitor.save_artifact.return_value = None
                with patch("desktop_agent.tools.music.read_media_sessions", return_value={"available": True, "sessions": sessions}), \
                     patch("desktop_agent.tools.music.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))), \
                     patch("desktop_agent.tools.music.SystemTools.wait"):
                    result = MusicTools(locator, monitor).inspect_music_playback("我要听挪威的森林")
                self.assertFalse(result["ok"])
                self.assertEqual(result["state"], expected)

    def evidence(self, **overrides):
        return dict(dict(target_matches_before=True, target_matches_after=True,
                         elapsed_before="01:00", elapsed_after="01:03",
                         control_after="pause_bars", blocked=False), **overrides)

    def test_dynamic_progress_required(self):
        self.assertEqual(playback_state(self.evidence(), 3), "playing")
        self.assertEqual(
            playback_state(self.evidence(elapsed_after="01:00"), 3),
            "paused",
        )
        for change in [dict(elapsed_after="01:00"), dict(elapsed_after=None),
                       dict(elapsed_after="03:59"), dict(target_matches_after=False),
                       dict(target_matches_before="true"), dict(control_after="unknown")]:
            with self.subTest(change=change):
                self.assertNotEqual(playback_state(self.evidence(**change), 3), "playing")

    def test_screenshot_fallback_is_allowed_when_media_session_unavailable(self):
        locator = Mock()
        locator.ask_json.return_value = self.evidence()
        monitor = Mock()
        monitor.save_artifact.return_value = None
        with patch("desktop_agent.tools.music.read_media_sessions", return_value={
            "available": False, "sessions": [], "error": "winrt unavailable",
        }), patch("desktop_agent.tools.music.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))), \
             patch("desktop_agent.tools.music.SystemTools.wait"), \
             patch("desktop_agent.tools.music.time.monotonic", side_effect=[0.0, 3.0]):
            result = MusicTools(locator, monitor).inspect_music_playback("我要听挪威的森林")
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "playing")
        self.assertEqual(result["verification_source"], "screenshot_fallback")

    def test_triangle_overrides_progress(self):
        self.assertEqual(playback_state(self.evidence(control_after="play_triangle"), 3), "paused")

    def test_local_progress_pixels_override_incorrect_ocr_time(self):
        before = Image.new("RGB", (1000, 600), "white")
        after = before.copy()
        # 窗口为 (100, 50)-(900, 550)，变化落在底栏已播时间/进度条区域。
        for x in range(450, 460):
            for y in range(500, 510):
                after.putpixel((x, y), (0, 0, 0))
        progress = progress_region_change(before, after, (100, 50, 900, 550))
        self.assertTrue(progress["changed"])
        evidence = self.evidence(elapsed_before="00:31", elapsed_after="00:31")
        self.assertEqual(
            playback_state(evidence, 3, progress_changed=True),
            "playing",
        )

    def test_static_progress_region_stays_paused(self):
        image = Image.new("RGB", (1000, 600), "white")
        progress = progress_region_change(image, image.copy(), (100, 50, 900, 550))
        self.assertFalse(progress["changed"])

    def test_inspection_uses_pixel_progress_when_winrt_is_missing(self):
        before = Image.new("RGB", (1000, 600), "white")
        after = before.copy()
        for x in range(450, 460):
            for y in range(500, 510):
                after.putpixel((x, y), (0, 0, 0))
        locator = Mock()
        locator.ask_json.return_value = self.evidence(
            elapsed_before="00:31",
            elapsed_after="00:31",
        )
        monitor = Mock()
        monitor.save_artifact.return_value = None
        unavailable = {
            "available": False,
            "sessions": [],
            "error": "ModuleNotFoundError: No module named 'winrt'",
        }
        with patch("desktop_agent.tools.music.find_qq_music_window", return_value=123), \
             patch("desktop_agent.tools.music.qq_music_window_rect", return_value=(100, 50, 900, 550)), \
             patch("desktop_agent.tools.music.read_media_sessions", return_value=unavailable), \
             patch("desktop_agent.tools.music.pyautogui.screenshot", side_effect=[before, after]), \
             patch("desktop_agent.tools.music.SystemTools.wait"), \
             patch("desktop_agent.tools.music.time.monotonic", side_effect=[0.0, 3.0]):
            result = MusicTools(locator, monitor).inspect_music_playback("我要听挪威的森林")
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "playing")
        self.assertEqual(result["verification_source"], "screenshot_pixel_progress")

    def test_scope(self):
        self.assertTrue(needs_music_verification("我要听挪威的森林"))
        self.assertFalse(needs_music_verification("暂停音乐"))
        self.assertFalse(needs_music_verification("打开浏览器搜索学校"))

    def test_finish_rejected_then_played_then_rechecked(self):
        locator = Mock()
        locator.ask_json.side_effect = [
            {"tool": "finish", "arguments": {"summary": "playing"}},
            {"tool": "resume", "arguments": {}},
            {"tool": "finish", "arguments": {"summary": "playing"}},
        ]
        checker = Mock(side_effect=[{"ok": False, "state": "paused"}, {"ok": True, "state": "playing"}])
        resume = Mock(return_value={"ok": True})
        tools = ToolRegistry()
        tools.register(ToolSpec("inspect_music_playback", "check", {}, checker))
        tools.register(ToolSpec("resume", "resume", {}, resume))
        with patch("desktop_agent.workflows.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))):
            result = GeneralTaskWorkflow(locator)._execute_agent("我要听挪威的森林", 6, tools)
        resume.assert_called_once()
        self.assertEqual(checker.call_count, 2)
        self.assertEqual(result[-1]["tool"], "finish")

    def test_repeated_finish_while_paused_fails(self):
        locator = Mock()
        locator.ask_json.return_value = {"tool": "finish", "arguments": {"summary": "playing"}}
        checker = Mock(return_value={"ok": False, "state": "paused"})
        tools = ToolRegistry()
        tools.register(ToolSpec("inspect_music_playback", "check", {}, checker))
        with patch("desktop_agent.workflows.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))):
            with self.assertRaisesRegex(RuntimeError, "3"):
                GeneralTaskWorkflow(locator)._execute_agent("我要听挪威的森林", 6, tools)
        self.assertEqual(checker.call_count, 3)

    def test_paused_finish_automatically_uses_media_resume(self):
        locator = Mock()
        locator.ask_json.side_effect = [
            {"tool": "finish", "arguments": {"summary": "playing"}},
            {"tool": "finish", "arguments": {"summary": "playing"}},
        ]
        checker = Mock(side_effect=[
            {"ok": False, "state": "paused"},
            {"ok": True, "state": "playing"},
        ])
        resume = Mock(return_value={"ok": True, "state": "playing"})
        tools = ToolRegistry()
        tools.register(ToolSpec("inspect_music_playback", "check", {}, checker))
        tools.register(ToolSpec(
            "resume_music_playback", "resume",
            {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
                "additionalProperties": False,
            },
            resume,
        ))
        with patch("desktop_agent.workflows.pyautogui.screenshot",
                   return_value=Image.new("RGB", (10, 10))):
            result = GeneralTaskWorkflow(locator)._execute_agent(
                "我要听挪威的森林", 6, tools
            )
        resume.assert_called_once_with(task="我要听挪威的森林")
        self.assertEqual(result[-1]["tool"], "finish")

    def test_inspect_playing_automatically_finishes_music_task(self):
        locator = Mock()
        locator.ask_json.return_value = {
            "tool": "inspect_music_playback",
            "arguments": {"task": "我要听挪威的森林"},
        }
        checker = Mock(return_value={"ok": True, "state": "playing"})
        tools = ToolRegistry()
        tools.register(ToolSpec(
            "inspect_music_playback", "check",
            {"type": "object", "properties": {"task": {"type": "string"}},
             "required": ["task"], "additionalProperties": False},
            checker,
        ))
        with patch("desktop_agent.workflows.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))):
            result = GeneralTaskWorkflow(locator)._execute_agent(
                "我要听挪威的森林", 6, tools
            )
        self.assertEqual(checker.call_count, 1)
        self.assertEqual(result[-1]["tool"], "finish")

    def test_wrong_track_automatically_researches_target(self):
        locator = Mock()
        locator.ask_json.side_effect = [
            {"tool": "inspect_music_playback", "arguments": {"task": "我要听挪威的森林"}},
            {"tool": "inspect_music_playback", "arguments": {"task": "我要听挪威的森林"}},
        ]
        checker = Mock(side_effect=[
            {"ok": False, "state": "wrong_track"},
            {"ok": True, "state": "playing"},
        ])
        search = Mock(return_value={"ok": True, "result_clicked": True})
        tools = ToolRegistry()
        task_schema = {
            "type": "object", "properties": {"task": {"type": "string"}},
            "required": ["task"], "additionalProperties": False,
        }
        tools.register(ToolSpec("inspect_music_playback", "check", task_schema, checker))
        tools.register(ToolSpec(
            "search_music_query", "search", {
                "type": "object", "properties": {"query": {"type": "string"}},
                "required": ["query"], "additionalProperties": False,
            }, search,
        ))
        with patch("desktop_agent.workflows.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))):
            result = GeneralTaskWorkflow(locator)._execute_agent(
                "我要听挪威的森林", 6, tools
            )
        search.assert_called_once_with(query="挪威的森林")
        self.assertEqual(checker.call_count, 2)
        self.assertEqual(result[-1]["tool"], "finish")

    def test_music_execute_uses_bounded_deterministic_flow(self):
        search = Mock(return_value={"ok": True, "result_clicked": True})
        checker = Mock(return_value={"ok": True, "state": "playing"})
        tools = ToolRegistry()
        tools.register(ToolSpec("search_music_query", "search", {}, search))
        tools.register(ToolSpec("inspect_music_playback", "check", {}, checker))
        request = TaskRequest(
            kind="general",
            payload={"task": "我要听挪威的森林", "max_steps": 40},
        )
        result = GeneralTaskWorkflow(Mock()).execute(request, tools, [])
        search.assert_called_once_with(query="挪威的森林")
        checker.assert_called_once_with(task="我要听挪威的森林")
        self.assertEqual(result[-1]["tool"], "finish")

    def test_inspect_paused_automatically_resumes_and_rechecks(self):
        locator = Mock()
        locator.ask_json.return_value = {
            "tool": "inspect_music_playback",
            "arguments": {"task": "我要听挪威的森林"},
        }
        checker = Mock(side_effect=[
            {"ok": False, "state": "paused"},
            {"ok": True, "state": "playing"},
        ])
        resume = Mock(return_value={"ok": False, "state": "unknown"})
        tools = ToolRegistry()
        task_schema = {
            "type": "object", "properties": {"task": {"type": "string"}},
            "required": ["task"], "additionalProperties": False,
        }
        tools.register(ToolSpec("inspect_music_playback", "check", task_schema, checker))
        tools.register(ToolSpec("resume_music_playback", "resume", task_schema, resume))
        with patch("desktop_agent.workflows.pyautogui.screenshot", return_value=Image.new("RGB", (10, 10))):
            result = GeneralTaskWorkflow(locator)._execute_agent(
                "我要听挪威的森林", 6, tools
            )
        resume.assert_called_once_with(task="我要听挪威的森林")
        self.assertEqual(checker.call_count, 2)
        self.assertEqual(result[-1]["tool"], "finish")
