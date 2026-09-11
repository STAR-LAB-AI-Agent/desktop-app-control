"""基于视觉定位和 PyAutoGUI 的桌面 Agent。"""

from .agent import DesktopAgent
from .config import AgentConfig
from .logging import TaskLogStore
from .vision import DeepSeekVisionLocator

__all__ = ["AgentConfig", "DeepSeekVisionLocator", "DesktopAgent", "TaskLogStore"]
