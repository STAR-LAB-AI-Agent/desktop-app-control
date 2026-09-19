import unittest
from unittest.mock import Mock, patch
from PIL import Image

from desktop_agent.workflows import GeneralTaskWorkflow
from desktop_agent.tools.base import ToolRegistry, ToolSpec


class PlannerRecoveryTests(unittest.TestCase):
    def run_loop(self, responses, excluded=None):
        locator = Mock()
        locator.ask_json.side_effect = responses
        handler = Mock(return_value={"ok": True})
        tools = ToolRegistry()
        tools.register(ToolSpec("search", "search", {
            "type": "object", "properties": {"query": {"type": "string"}},
            "required": ["query"], "additionalProperties": False,
        }, handler))
        workflow = GeneralTaskWorkflow(locator, excluded_tools=excluded)
        with patch("desktop_agent.workflows.pyautogui.screenshot", return_value=Image.new("RGB", (100, 100))):
            result = workflow._execute_agent("search a topic", 10, tools)
        return result, handler, locator

    def test_missing_tool_recovers_without_repeating_search(self):
        result, handler, locator = self.run_loop([
            {"tool": "search", "arguments": {"query": "song"}},
            {"reason": "missing tool"},
            {"tool": "finish", "arguments": {"summary": "done"}},
        ])
        handler.assert_called_once_with(query="song")
        self.assertEqual(result[1]["tool"], "invalid_decision")
        self.assertIn("invalid_decision", locator.ask_json.call_args.args[1])

    def test_invalid_json_recovers(self):
        result, handler, _ = self.run_loop([
            ValueError("invalid JSON"),
            {"tool": "finish", "arguments": {"summary": "done"}},
        ])
        handler.assert_not_called()
        self.assertEqual(result[-1]["tool"], "finish")

    def test_repeated_invalid_response_stops(self):
        with self.assertRaisesRegex(RuntimeError, "3"):
            self.run_loop([{}, {}, {}])

    def test_bad_arguments_do_not_execute(self):
        for arguments in [None, [], {}, {"query": 42}, {"query": "x", "extra": 1}]:
            with self.subTest(arguments=arguments):
                _, handler, _ = self.run_loop([
                    {"tool": "search", "arguments": arguments},
                    {"tool": "finish", "arguments": {"summary": "done"}},
                ])
                handler.assert_not_called()

    def test_excluded_tool_cannot_execute(self):
        _, handler, _ = self.run_loop([
            {"tool": "search", "arguments": {"query": "song"}},
            {"tool": "finish", "arguments": {"summary": "done"}},
        ], {"search"})
        handler.assert_not_called()

    def test_invalid_finish_cannot_report_success(self):
        result, _, _ = self.run_loop([
            {"tool": "finish", "arguments": []},
            {"tool": "finish", "arguments": {"summary": "done"}},
        ])
        self.assertEqual(result[0]["tool"], "invalid_decision")


if __name__ == "__main__":
    unittest.main()
