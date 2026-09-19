import unittest
from unittest.mock import Mock, patch

from PIL import Image

from desktop_agent.tools.base import ToolRegistry, ToolSpec
from desktop_agent.workflows import GeneralTaskWorkflow


class VideoWorkflowTests(unittest.TestCase):
    def test_play_click_is_rechecked_and_finished_without_third_planner_call(self):
        locator = Mock()
        locator.ask_json.side_effect = [
            {
                "tool": "inspect_video_playback_state",
                "arguments": {"video_query": "复仇者联盟"},
                "reason": "先检查播放器",
            },
            {
                "tool": "click_target",
                "arguments": {"target": "播放器中央的播放按钮"},
                "reason": "点击一次播放",
            },
        ]
        inspect = Mock(side_effect=[
            {"ok": True, "state": "paused", "can_finish": False},
            {"ok": True, "state": "playing", "can_finish": True},
        ])
        click = Mock(return_value={"ok": True})
        tools = ToolRegistry()
        tools.register(ToolSpec(
            "inspect_video_playback_state",
            "inspect",
            {
                "type": "object",
                "properties": {"video_query": {"type": "string"}},
                "required": ["video_query"],
                "additionalProperties": False,
            },
            inspect,
        ))
        tools.register(ToolSpec(
            "click_target",
            "click",
            {
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
                "additionalProperties": False,
            },
            click,
        ))

        with patch(
            "desktop_agent.workflows.pyautogui.screenshot",
            return_value=Image.new("RGB", (10, 10)),
        ):
            result = GeneralTaskWorkflow(locator)._execute_agent(
                "我要看复仇者联盟",
                6,
                tools,
                skill_variables={"video_query": "复仇者联盟"},
            )

        self.assertEqual(locator.ask_json.call_count, 2)
        self.assertEqual(inspect.call_count, 2)
        click.assert_called_once_with(target="播放器中央的播放按钮")
        self.assertEqual(result[-1]["tool"], "finish")


if __name__ == "__main__":
    unittest.main()
