from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from desktop_agent.tools.skill_scripts import SCRIPT_PROTOCOL, SkillScriptTool


ROOT = Path(__file__).parents[1]
SCRIPT = (
    ROOT
    / "skills"
    / "chatgpt-paper-abstract"
    / "scripts"
    / "inspect_chatgpt_translation_state.py"
)


def load_inspection_module():
    spec = importlib.util.spec_from_file_location("test_chatgpt_inspector", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortableInspectionScriptTests(unittest.TestCase):
    def test_script_describes_runtime_neutral_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--describe"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        description = json.loads(completed.stdout)
        self.assertEqual(description["protocol"], SCRIPT_PROTOCOL)
        self.assertEqual(description["name"], "inspect_chatgpt_translation_state")

    def test_inspection_derives_complete_from_ui_indicators(self) -> None:
        module = load_inspection_module()
        screenshot = Image.new("RGB", (2560, 1440), "black")

        def fake_vision(image, prompt):
            self.assertIn("不要使用画面变化率", prompt)
            return {
                "chatgpt_visible": True,
                "conversation_obscured": False,
                "stop_button_visible": False,
                "send_button_visible": True,
                "latest_response_actions_visible": True,
                "evidence": ["发送箭头和最新回答操作按钮可见"],
            }

        with tempfile.TemporaryDirectory() as directory:
            result = module.inspect_translation_state(
                "Section 1",
                artifact_dir=Path(directory),
                screenshot=lambda: screenshot,
                ask_json=fake_vision,
            )
            self.assertTrue(Path(result["inspection_image"]).is_file())

        self.assertEqual(result["state"], "complete")
        self.assertTrue(result["can_advance"])
        self.assertFalse(result["screen_changed_used"])


class SkillScriptAdapterTests(unittest.TestCase):
    def test_manifest_is_loaded_as_tool_spec(self) -> None:
        manifest = SCRIPT.with_suffix(".tool.json")
        tool = SkillScriptTool(manifest, python_executable=sys.executable)
        spec = tool.spec()
        self.assertEqual(spec.name, "inspect_chatgpt_translation_state")
        self.assertEqual(spec.parameters["required"], ["expected_segment"])

    def test_adapter_passes_versioned_json_over_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scripts_dir = Path(directory)
            entrypoint = scripts_dir / "echo_tool.py"
            entrypoint.write_text(
                "import json, sys\n"
                "request = json.load(sys.stdin)\n"
                "print(json.dumps({'ok': True, 'request': request}, ensure_ascii=False))\n",
                encoding="utf-8",
            )
            manifest = scripts_dir / "echo_tool.tool.json"
            manifest.write_text(
                json.dumps(
                    {
                        "protocol": SCRIPT_PROTOCOL,
                        "name": "echo_skill_script",
                        "description": "test",
                        "entrypoint": entrypoint.name,
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            tool = SkillScriptTool(
                manifest,
                python_executable=sys.executable,
                artifact_dir_provider=lambda: scripts_dir / "artifacts",
            )
            result = tool.execute(value="中文")

        request = result["request"]
        self.assertEqual(request["protocol"], SCRIPT_PROTOCOL)
        self.assertEqual(request["arguments"], {"value": "中文"})
        self.assertTrue(request["context"]["artifact_dir"].endswith("artifacts"))


if __name__ == "__main__":
    unittest.main()
