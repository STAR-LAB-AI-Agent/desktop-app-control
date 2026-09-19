import unittest
from unittest.mock import Mock, patch

from PIL import Image

from desktop_agent.tools.base import RecoverableToolError
from desktop_agent.tools.mouse import MouseTools
from desktop_agent.vision import PointPrediction


class MouseStabilityTests(unittest.TestCase):
    def prediction(self):
        return PointPrediction(20, 20, 0.95, "target")

    def test_moving_screen_aborts_stale_click(self):
        locator = Mock()
        locator.locate.return_value = self.prediction()
        before = Image.new("RGB", (100, 100), "black")
        moved = Image.new("RGB", (100, 100), "white")
        with patch("desktop_agent.tools.mouse.pyautogui.screenshot", side_effect=[before, moved]), \
             patch("desktop_agent.tools.mouse.pyautogui.click") as click:
            with self.assertRaises(RecoverableToolError):
                MouseTools(locator, 0.75).click_target("target")
        click.assert_not_called()

    def test_stable_screen_clicks_latest_prediction(self):
        locator = Mock()
        locator.locate.return_value = self.prediction()
        image = Image.new("RGB", (100, 100), "black")
        with patch("desktop_agent.tools.mouse.pyautogui.screenshot", side_effect=[image, image]), \
             patch("desktop_agent.tools.mouse.pyautogui.click") as click:
            result = MouseTools(locator, 0.75).click_target("target")
        click.assert_called_once_with(20, 20, button="left")
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
