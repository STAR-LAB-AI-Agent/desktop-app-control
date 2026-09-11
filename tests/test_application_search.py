import unittest
from unittest.mock import Mock, call, patch

from desktop_agent.config import AgentConfig
from desktop_agent.tools.applications import ApplicationTools
from desktop_agent.tools.keyboard import KeyboardTools
from desktop_agent.workflows import GeneralTaskWorkflow


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


if __name__ == "__main__":
    unittest.main()
