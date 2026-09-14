import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from desktop_agent.audit import TaskAuditor
from desktop_agent.skills import SkillRegistry
from desktop_agent.task import PlannedAction, ReviewDecision, TaskRequest
from desktop_agent.tools.files import _match_rank


class FakeTools:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    def execute(
        self,
        name: str,
        arguments: dict,
        *,
        explanation: str = "",
    ) -> dict:
        self.calls.append((name, arguments))
        return self.result


class SkillRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry(Path(__file__).parents[1] / "skills")
        self.registry.discover()

    def test_routes_paper_translation_and_extracts_name(self) -> None:
        cases = {
            "翻译 GROOT 论文": "GROOT",
            "翻译一下桌面上的 Attention Is All You Need 论文": (
                "Attention Is All You Need"
            ),
            "把 GROOT 论文翻译一下": "GROOT",
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                match = self.registry.route(task)
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.definition.name, "chatgpt-paper-abstract")
                self.assertEqual(match.variables["paper_query"], expected)
                self.assertEqual(
                    match.variables["translation_segments"],
                    [
                        "Abstract",
                        "Section 1",
                        "Section 2",
                        "Section 3",
                        "Section 4",
                        "Section 5",
                    ],
                )

    def test_unrelated_task_stays_general(self) -> None:
        self.assertIsNone(self.registry.route("在百度搜索天气"))

    def test_routes_video_playback_and_extracts_platform(self) -> None:
        cases = (
            (
                "在B站搜索并播放 Python 教程视频",
                "哔哩哔哩",
                "https://www.bilibili.com",
                "Python 教程",
            ),
            (
                "Use YouTube to search and play a Python tutorial video",
                "YouTube",
                "https://www.youtube.com",
                "Python tutorial",
            ),
        )
        for task, platform, url, query in cases:
            with self.subTest(task=task):
                match = self.registry.route(task)
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.definition.name, "web-video-playback")
                self.assertEqual(match.variables["requested_platform"], platform)
                self.assertEqual(match.variables["platform_url"], url)
                self.assertEqual(match.variables["video_query"], query)

    def test_skill_config_controls_priority(self) -> None:
        self.assertEqual(self.registry.get("chatgpt-paper-abstract").priority, 100)
        self.assertEqual(self.registry.get("web-video-playback").priority, 90)

    def test_disabled_skill_is_not_loaded(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            disabled = root / "disabled-skill"
            disabled.mkdir()
            (disabled / "SKILL.md").write_text("故意无效", encoding="utf-8")
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "skills": {
                            "disabled-skill": {"enabled": False, "priority": 0}
                        },
                    }
                ),
                encoding="utf-8",
            )

            registry = SkillRegistry(root)
            registry.discover()

        self.assertEqual(registry.names(), ())

    def test_skill_specific_screenshot_tool_is_discovered(self) -> None:
        specs = self.registry.build_tool_specs(
            python_executable="python",
            env_overrides={"DEEPSEEK_API_KEY": "test-key"},
            artifact_dir_provider=lambda: Path("artifacts"),
        )
        tools = {spec.name: spec for spec in specs}
        self.assertIn("inspect_chatgpt_translation_state", tools)
        self.assertEqual(
            self.registry.tool_names("chatgpt-paper-abstract"),
            ("inspect_chatgpt_translation_state",),
        )
        self.assertEqual(
            self.registry.all_tool_names(),
            (
                "inspect_chatgpt_translation_state",
                "inspect_video_playback_state",
            ),
        )

        self.assertEqual(
            self.registry.tool_names("web-video-playback"),
            ("inspect_video_playback_state",),
        )

        definition = self.registry.get("chatgpt-paper-abstract")
        self.assertEqual(len(definition.script_manifests), 1)
        self.assertTrue(
            definition.script_manifests[0].name.endswith(".tool.json")
        )

    def test_skill_task_requires_confirmation(self) -> None:
        match = self.registry.route("翻译 GROOT 论文")
        assert match is not None
        request = TaskRequest(
            kind="skill",
            payload={
                "task": "翻译 GROOT 论文",
                "skill_name": match.definition.name,
                "skill_variables": match.variables,
            },
        )
        review = TaskAuditor(self.registry).review(
            request,
            [PlannedAction("skill_agent_loop", {}, "test")],
        )
        self.assertEqual(review.decision, ReviewDecision.CONFIRM)
        self.assertTrue(any("上传" in warning for warning in review.warnings))
        self.assertIn("Section 5", review.summary)

    def test_visual_confusable_filename_is_supported(self) -> None:
        self.assertEqual(_match_rank("groot", "gr00t"), 2)

    def test_execution_preflight_resolves_file_once(self) -> None:
        definition = self.registry.get("chatgpt-paper-abstract")
        tools = FakeTools(
            {
                "ok": True,
                "status": "found",
                "matches": [r"C:\Users\test\Desktop\GR00T.pdf"],
                "match_method": "visual_confusable_exact",
            }
        )
        variables = definition.handler.prepare_execution(
            tools,
            {"paper_query": "GROOT"},
        )
        self.assertEqual(len(tools.calls), 1)
        self.assertEqual(variables["paper_filename"], "GR00T.pdf")
        self.assertEqual(variables["paper_match_method"], "visual_confusable_exact")

    def test_execution_preflight_stops_when_file_is_missing(self) -> None:
        definition = self.registry.get("chatgpt-paper-abstract")
        tools = FakeTools(
            {
                "ok": False,
                "status": "not_found",
                "matches": [],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "没有找到"):
            definition.handler.prepare_execution(tools, {"paper_query": "missing"})
        self.assertEqual(len(tools.calls), 1)


if __name__ == "__main__":
    unittest.main()
