from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
    def test_visual_request_retries_connection_reset(self) -> None:
        module = load_video_inspection_module()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                content = json.dumps({"player_visible": True})
                return json.dumps({
                    "choices": [{"message": {"content": content}}]
                }).encode("utf-8")

        with patch.dict(module.os.environ, {"DEEPSEEK_API_KEY": "test-key"}), \
             patch.object(
                 module.urllib.request,
                 "urlopen",
                 side_effect=[ConnectionResetError(10054, "reset"), Response()],
             ) as urlopen, patch.object(module.time, "sleep") as sleep:
            result = module.ask_vision_json(Image.new("RGB", (4, 4)), "check")

        self.assertTrue(result["player_visible"])
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_invalid_backslash_in_model_evidence_is_repaired(self) -> None:
        module = load_video_inspection_module()
        value = module._extract_json(
            '{"player_visible":true,"evidence":["广告位 C:\\video\\playing"]}'
        )
        self.assertTrue(value["player_visible"])
        self.assertEqual(value["evidence"], [r"广告位 C:\video\playing"])

    def test_invalid_backslash_in_outer_api_json_is_repaired(self) -> None:
        module = load_video_inspection_module()
        value = module._loads_json_tolerant(
            '{"choices":[{"message":{"content":"播放器 C:\\video"}}]}'
        )
        self.assertEqual(
            value["choices"][0]["message"]["content"],
            r"播放器 C:\video",
        )

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

    def test_playing_ad_can_finish_even_when_title_does_not_match(self) -> None:
        module = load_video_inspection_module()
        screenshots = iter(
            (
                Image.new("RGB", (320, 180), "black"),
                Image.new("RGB", (320, 180), "gray"),
            )
        )

        def fake_vision(image, prompt):
            self.assertIn("广告、片头或正片", prompt)
            return {
                "browser_visible": True,
                "video_site_visible": True,
                "site_home_visible": False,
                "search_results_visible": False,
                "player_visible": True,
                "title_matches_query": False,
                "play_button_visible": False,
                "pause_button_visible": True,
                "loading_visible": False,
                "timeline_advanced": True,
                "player_frame_changed": True,
                "blocking_dialog_visible": False,
                "window_obscured": False,
                "evidence": ["广告进度条正在前进"],
            }

        with tempfile.TemporaryDirectory() as directory:
            result = module.inspect_video_playback_state(
                "复仇者联盟",
                sample_seconds=0,
                artifact_dir=Path(directory),
                screenshot=lambda: next(screenshots),
                ask_json=fake_vision,
            )

        self.assertEqual(result["state"], "playing")
        self.assertTrue(result["can_finish"])

    def test_unrelated_paused_video_is_still_wrong_video(self) -> None:
        module = load_video_inspection_module()
        screenshots = iter(
            (
                Image.new("RGB", (320, 180), "black"),
                Image.new("RGB", (320, 180), "black"),
            )
        )

        def fake_vision(image, prompt):
            return {
                "browser_visible": True,
                "video_site_visible": True,
                "site_home_visible": False,
                "search_results_visible": False,
                "player_visible": True,
                "title_matches_query": False,
                "play_button_visible": True,
                "pause_button_visible": False,
                "loading_visible": False,
                "timeline_advanced": False,
                "player_frame_changed": False,
                "blocking_dialog_visible": False,
                "window_obscured": False,
                "evidence": ["无关视频处于暂停状态"],
            }

        with tempfile.TemporaryDirectory() as directory:
            result = module.inspect_video_playback_state(
                "复仇者联盟",
                sample_seconds=0,
                artifact_dir=Path(directory),
                screenshot=lambda: next(screenshots),
                ask_json=fake_vision,
            )

        self.assertEqual(result["state"], "wrong_video")
        self.assertFalse(result["can_finish"])


if __name__ == "__main__":
    unittest.main()
