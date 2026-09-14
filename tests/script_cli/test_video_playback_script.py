from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).parents[2]
SCRIPT = (
    ROOT
    / "skills"
    / "web-video-playback"
    / "scripts"
    / "inspect_video_playback_state.py"
)


def load_video_inspection_module():
    spec = importlib.util.spec_from_file_location("test_video_inspector", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VideoPlaybackScriptTests(unittest.TestCase):
    def test_script_describes_independent_cli_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--describe"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        description = json.loads(completed.stdout)
        self.assertEqual(description["protocol"], "agent-skill-script/v1")
        self.assertEqual(description["name"], "inspect_video_playback_state")
        self.assertIn("playing", description["output_states"])

    def test_two_screenshots_can_confirm_playing(self) -> None:
        module = load_video_inspection_module()
        screenshots = iter(
            (
                Image.new("RGB", (320, 180), "black"),
                Image.new("RGB", (320, 180), "navy"),
            )
        )

        def fake_vision(image, prompt):
            self.assertEqual(image.width, 640)
            self.assertIn("BEFORE", prompt)
            return {
                "browser_visible": True,
                "video_site_visible": True,
                "site_home_visible": False,
                "search_results_visible": False,
                "player_visible": True,
                "title_matches_query": True,
                "play_button_visible": False,
                "pause_button_visible": True,
                "loading_visible": False,
                "timeline_advanced": True,
                "player_frame_changed": True,
                "blocking_dialog_visible": False,
                "window_obscured": False,
                "evidence": ["进度条前进且暂停按钮可见"],
            }

        with tempfile.TemporaryDirectory() as directory:
            result = module.inspect_video_playback_state(
                "Python 教程",
                sample_seconds=0,
                artifact_dir=Path(directory),
                screenshot=lambda: next(screenshots),
                ask_json=fake_vision,
            )
            self.assertTrue(Path(result["images"]["comparison"]).is_file())

        self.assertEqual(result["state"], "playing")
        self.assertTrue(result["can_finish"])


if __name__ == "__main__":
    unittest.main()
