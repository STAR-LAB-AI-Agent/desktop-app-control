import unittest
from unittest.mock import Mock, call, patch

from PIL import Image

from desktop_agent.config import AgentConfig
from desktop_agent.tools.applications import ApplicationTools
from desktop_agent.tools.base import ToolRegistry, ToolSpec
from desktop_agent.tools.keyboard import KeyboardTools
from desktop_agent.workflows import GeneralTaskWorkflow, is_simple_application_open_task


class ApplicationSearchPromptTests(unittest.TestCase):
    def test_default_application_search_names(self) -> None:
        names = AgentConfig().application_search_names
        self.assertEqual(names["浏览器"], "Edge")
        self.assertEqual(names["音乐软件"], "音乐")
        self.assertEqual(names["翻译软件"], "ChatGPT")

    def test_planner_receives_windows_search_strategy(self) -> None:
        prompt = GeneralTaskWorkflow._planner_prompt(
            "打开浏览器",
            [],
            [],
            (2560, 1440),
            application_search_names={"浏览器": "Edge"},
        )
        self.assertIn("open_app_via_windows_search", prompt)
        self.assertIn("Win+S", prompt)
        self.assertIn('"浏览器": "Edge"', prompt)
        self.assertIn("不得点击任务栏图标、搜索历史", prompt)
        self.assertIn("submit_search_query", prompt)
        self.assertIn("不得点击自动补全、搜索历史", prompt)


class ApplicationToolsTests(unittest.TestCase):
    def test_tool_schema_is_registered(self) -> None:
        spec = ApplicationTools(search_delay=0, launch_delay=0).specs()[0]
        self.assertEqual(spec.name, "open_app_via_windows_search")
        self.assertEqual(spec.parameters["required"], ["app_name"])

    @patch("desktop_agent.tools.applications.KeyboardTools.type_text")
    @patch("desktop_agent.tools.applications.pyautogui")
    def test_search_is_one_keyboard_only_operation(
        self,
        pyautogui_mock: Mock,
        type_text_mock: Mock,
    ) -> None:
        events: list[object] = []
        pyautogui_mock.hotkey.side_effect = lambda *keys: events.append(call.hotkey(*keys))
        type_text_mock.side_effect = lambda text: events.append(call.type_text(text))
        pyautogui_mock.press.side_effect = lambda key: events.append(call.press(key))

        verified = {
            "verified_open": True,
            "process_name": "msedge.exe",
            "window_title": "Edge",
            "window_visible": True,
            "window_handle": 123,
        }
        with patch(
            "desktop_agent.tools.applications.application_window_status",
            side_effect=[None, verified],
        ):
            result = ApplicationTools(search_delay=0, launch_delay=0).open_app_via_windows_search(
                "Edge"
            )

        self.assertEqual(
            events,
            [
                call.hotkey("win", "s"),
                call.hotkey("ctrl", "a"),
                call.type_text("Edge"),
                call.press("enter"),
            ],
        )
        self.assertTrue(result["ignored_search_history"])
        self.assertTrue(result["verified_open"])

    @patch("desktop_agent.tools.applications.pyautogui")
    def test_existing_dingtalk_is_activated_without_search(self, pyautogui_mock: Mock) -> None:
        status = {
            "verified_open": True,
            "process_name": "dingtalk.exe",
            "window_title": "DingTalk",
            "window_visible": True,
            "window_handle": 456,
        }
        with patch(
            "desktop_agent.tools.applications.application_window_status",
            return_value=status,
        ):
            result = ApplicationTools(search_delay=0, launch_delay=0).open_app_via_windows_search(
                "钉钉"
            )
        self.assertTrue(result["verified_open"])
        self.assertTrue(result["already_running"])
        self.assertEqual(result["method"], "existing_process_or_window")
        pyautogui_mock.hotkey.assert_not_called()

    @patch("desktop_agent.tools.applications.KeyboardTools.type_text")
    @patch("desktop_agent.tools.applications.pyautogui")
    def test_background_edge_falls_back_to_windows_search(
        self,
        pyautogui_mock: Mock,
        type_text_mock: Mock,
    ) -> None:
        background = {
            "verified_open": True,
            "foreground": False,
            "process_name": "msedge.exe",
            "window_title": "Microsoft Edge",
            "window_visible": True,
            "window_handle": 123,
        }
        foreground = {**background, "foreground": True}
        with patch(
            "desktop_agent.tools.applications.application_window_status",
            side_effect=[background, foreground],
        ):
            result = ApplicationTools(search_delay=0, launch_delay=0).open_app_via_windows_search(
                "Edge"
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["foreground"])
        pyautogui_mock.hotkey.assert_any_call("win", "s")
        type_text_mock.assert_called_once_with("Edge")

    def test_rejects_multiline_app_name(self) -> None:
        with self.assertRaises(ValueError):
            ApplicationTools(search_delay=0, launch_delay=0).open_app_via_windows_search(
                "Edge\n北京理工大学"
            )


class SearchSubmissionTests(unittest.TestCase):
    def test_tool_schema_is_registered(self) -> None:
        specs = {spec.name: spec for spec in KeyboardTools().specs()}
        self.assertIn("submit_search_query", specs)
        self.assertEqual(specs["submit_search_query"].parameters["required"], ["query"])

    @patch.object(KeyboardTools, "type_text")
    @patch("desktop_agent.tools.keyboard.pyautogui")
    def test_query_is_typed_and_submitted_without_gui_selection(
        self,
        pyautogui_mock: Mock,
        type_text_mock: Mock,
    ) -> None:
        events: list[object] = []
        pyautogui_mock.hotkey.side_effect = lambda *keys: events.append(call.hotkey(*keys))
        type_text_mock.side_effect = lambda text: events.append(call.type_text(text))
        pyautogui_mock.press.side_effect = lambda key: events.append(call.press(key))

        result = KeyboardTools.submit_search_query("北京理工大学")

        self.assertEqual(
            events,
            [
                call.hotkey("ctrl", "a"),
                call.type_text("北京理工大学"),
                call.press("enter"),
            ],
        )
        self.assertTrue(result["ignored_suggestions"])


class ApplicationOpenWorkflowTests(unittest.TestCase):
    def test_simple_open_task_finishes_after_native_verification(self) -> None:
        locator = Mock()
        locator.ask_json.return_value = {
            "tool": "open_app_via_windows_search",
            "arguments": {"app_name": "钉钉"},
            "reason": "启动钉钉",
        }
        opener = Mock(return_value={
            "ok": True,
            "app_name": "钉钉",
            "verified_open": True,
            "process_name": "dingtalk.exe",
            "window_visible": True,
        })
        tools = ToolRegistry()
        tools.register(ToolSpec(
            "open_app_via_windows_search",
            "open",
            {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
                "additionalProperties": False,
            },
            opener,
        ))
        with patch(
            "desktop_agent.workflows.pyautogui.screenshot",
            return_value=Image.new("RGB", (10, 10)),
        ):
            result = GeneralTaskWorkflow(locator)._execute_agent(
                "打开我的钉钉", 6, tools
            )
        self.assertEqual(locator.ask_json.call_count, 1)
        opener.assert_called_once_with(app_name="钉钉")
        self.assertEqual(result[-1]["tool"], "finish")

    def test_open_intent_only_matches_simple_launch_request(self) -> None:
        self.assertTrue(is_simple_application_open_task("打开我的钉钉"))
        self.assertTrue(is_simple_application_open_task("请帮我启动 ChatGPT"))
        self.assertFalse(is_simple_application_open_task("打开浏览器搜索时政新闻"))


if __name__ == "__main__":
    unittest.main()
