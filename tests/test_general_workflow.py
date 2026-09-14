from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from desktop_agent.agent import DesktopAgent
from desktop_agent.config import AgentConfig


class GeneralWorkflowTests(unittest.TestCase):
    def test_legacy_search_entry_uses_general_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = DesktopAgent(
                AgentConfig(
                    api_key="test-key",
                    logs_dir=Path(directory),
                    skills_dir=Path(__file__).parents[1] / "skills",
                ),
                locator=Mock(),
            )

        request = agent.create_search_task("北京理工大学")
        self.assertEqual(request.kind, "general")
        self.assertEqual(request.payload["task"], "在当前页面搜索：北京理工大学")


if __name__ == "__main__":
    unittest.main()
