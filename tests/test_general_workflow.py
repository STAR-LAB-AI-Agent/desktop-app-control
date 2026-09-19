from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from desktop_agent.agent import DesktopAgent
from desktop_agent.config import AgentConfig
from desktop_agent.routing import ModelSkillRouter


class GeneralWorkflowTests(unittest.TestCase):
    def build_agent(self, directory: str, response: dict) -> DesktopAgent:
        return DesktopAgent(
            AgentConfig(
                api_key="test-key",
                logs_dir=Path(directory),
                skills_dir=Path(__file__).parents[1] / "skills",
            ),
            locator=Mock(),
            skill_router=ModelSkillRouter(lambda _prompt: response),
        )

    def test_legacy_search_entry_also_uses_model_router(self) -> None:
        prompts: list[str] = []

        def route(prompt: str) -> dict:
            prompts.append(prompt)
            return {
                "route": "general",
                "confidence": 0.99,
                "reason": "普通网页搜索",
            }

        with tempfile.TemporaryDirectory() as directory:
            agent = DesktopAgent(
                AgentConfig(
                    api_key="test-key",
                    logs_dir=Path(directory),
                    skills_dir=Path(__file__).parents[1] / "skills",
                ),
                locator=Mock(),
                skill_router=ModelSkillRouter(route),
            )

        request = agent.create_search_task("北京理工大学")
        self.assertEqual(request.kind, "general")
        self.assertEqual(request.payload["task"], "在当前页面搜索：北京理工大学")
        self.assertEqual(request.payload["skill_route"]["route"], "general")
        self.assertEqual(len(prompts), 1)

    def test_model_selected_skill_is_prepared_by_registry(self) -> None:
        cases = (
            (
                "翻译 GROOT 论文",
                "chatgpt-paper-abstract",
                "paper_query",
                "GROOT",
            ),
            (
                "在B站播放 Python 教程视频",
                "web-video-playback",
                "video_query",
                "Python 教程",
            ),
        )
        for task, route, variable_name, expected in cases:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                agent = self.build_agent(
                    directory,
                    {"route": route, "confidence": 0.98, "reason": "专项任务"},
                )
                request = agent.create_general_task(task, max_steps=17)

                self.assertEqual(request.kind, "skill")
                self.assertEqual(request.payload["skill_name"], route)
                self.assertEqual(request.payload["skill_variables"][variable_name], expected)
                self.assertEqual(request.payload["max_steps"], 17)


if __name__ == "__main__":
    unittest.main()
