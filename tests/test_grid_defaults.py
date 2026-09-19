import unittest

from desktop_agent.config import AgentConfig
from desktop_agent.tools.mouse import MouseTools
from desktop_agent.tools.toolbox import DesktopToolbox
from main import build_agent_config


class GridDefaultsTests(unittest.TestCase):
    def test_all_default_grid_sizes_are_ten_by_ten(self) -> None:
        config = AgentConfig()
        self.assertEqual((config.grid_rows, config.grid_columns), (10, 10))
        entry_config = build_agent_config()
        self.assertEqual(
            (entry_config.grid_rows, entry_config.grid_columns),
            (10, 10),
        )

        mouse = MouseTools(object(), 0.75)
        self.assertEqual((mouse.grid_rows, mouse.grid_columns), (10, 10))

        toolbox = DesktopToolbox(object())
        self.assertEqual((toolbox.grid_rows, toolbox.grid_columns), (10, 10))


if __name__ == "__main__":
    unittest.main()
