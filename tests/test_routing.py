from pathlib import Path
import unittest

from desktop_agent.routing import ModelSkillRouter
from desktop_agent.skills import SkillRegistry


class ModelSkillRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry(Path(__file__).parents[1] / "skills")
        self.registry.discover()

    def decide(self, response: dict, task: str = "测试任务"):
        prompts: list[str] = []

        def ask_json(prompt: str) -> dict:
            prompts.append(prompt)
            return response

        decision = ModelSkillRouter(ask_json).decide(
            task,
            self.registry.definitions(),
        )
        return decision, prompts

    def test_model_can_select_each_of_the_three_routes(self) -> None:
        for route in (
            "general",
            "chatgpt-paper-abstract",
            "web-video-playback",
        ):
            with self.subTest(route=route):
                decision, _ = self.decide(
                    {"route": route, "confidence": 0.95, "reason": "符合说明"}
                )
                self.assertEqual(decision.route, route)
                self.assertEqual(decision.requested_route, route)

    def test_prompt_uses_enabled_skill_metadata(self) -> None:
        decision, prompts = self.decide(
            {"route": "general", "confidence": 0.9, "reason": "普通任务"},
            "打开浏览器搜索天气",
        )
        self.assertEqual(decision.route, "general")
        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        for definition in self.registry.definitions():
            self.assertIn(definition.name, prompt)
            self.assertIn(definition.description, prompt)
            self.assertIn(str(definition.priority), prompt)
        self.assertIn("打开浏览器搜索天气", prompt)

    def test_unknown_route_falls_back_to_general(self) -> None:
        decision, _ = self.decide(
            {"route": "invented-skill", "confidence": 1, "reason": "错误输出"}
        )
        self.assertEqual(decision.route, "general")
        self.assertEqual(decision.requested_route, "invented-skill")
        self.assertEqual(decision.confidence, 0.0)

    def test_low_confidence_specialized_route_falls_back_to_general(self) -> None:
        decision, _ = self.decide(
            {
                "route": "web-video-playback",
                "confidence": 0.3,
                "reason": "意图不明确",
            }
        )
        self.assertEqual(decision.route, "general")
        self.assertEqual(decision.requested_route, "web-video-playback")
        self.assertAlmostEqual(decision.confidence, 0.3)

    def test_confidence_is_normalized(self) -> None:
        decision, _ = self.decide(
            {"route": "general", "confidence": 9, "reason": "普通任务"}
        )
        self.assertEqual(decision.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
