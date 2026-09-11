"""桌面 Agent 工具包。"""

from .applications import ApplicationTools
from .base import RecoverableToolError, ToolRegistry, ToolSpec
from .files import FileTools
from .keyboard import KeyboardTools
from .monitor import TaskCancelledError, ToolExecutionMonitor
from .mouse import MouseTools
from .skill_scripts import SCRIPT_PROTOCOL, SkillScriptTool
from .system import SystemTools
from .toolbox import DesktopToolbox

__all__ = [
    "ApplicationTools",
    "DesktopToolbox",
    "FileTools",
    "KeyboardTools",
    "MouseTools",
    "RecoverableToolError",
    "SCRIPT_PROTOCOL",
    "SkillScriptTool",
    "SystemTools",
    "ToolRegistry",
    "ToolSpec",
    "ToolExecutionMonitor",
    "TaskCancelledError",
]
