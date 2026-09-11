"""把 Agent Skill 中的可执行脚本适配为本项目的 ToolSpec。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from .base import ToolSpec


SCRIPT_PROTOCOL = "agent-skill-script/v1"


class SkillScriptTool:
    """执行一个由 ``*.tool.json`` 描述的跨 Runtime Skill 脚本。"""

    def __init__(
        self,
        manifest_path: Path,
        *,
        python_executable: str | None = None,
        env_overrides: dict[str, str] | None = None,
        artifact_dir_provider: Callable[[], Path | None] | None = None,
    ) -> None:
        self.manifest_path = manifest_path.resolve()
        self.python_executable = python_executable or sys.executable
        self.env_overrides = dict(env_overrides or {})
        self.artifact_dir_provider = artifact_dir_provider

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError(f"Skill 脚本清单必须是 JSON 对象：{manifest_path}")
        if manifest.get("protocol") != SCRIPT_PROTOCOL:
            raise ValueError(
                f"不支持的 Skill 脚本协议：{manifest.get('protocol')!r}"
            )

        self.name = str(manifest.get("name") or "").strip()
        self.description = str(manifest.get("description") or "").strip()
        self.parameters = manifest.get("parameters")
        entrypoint = str(manifest.get("entrypoint") or "").strip()
        if not self.name or not self.description or not isinstance(self.parameters, dict):
            raise ValueError(f"Skill 脚本清单缺少 name、description 或 parameters：{manifest_path}")
        if not entrypoint:
            raise ValueError(f"Skill 脚本清单缺少 entrypoint：{manifest_path}")

        scripts_dir = self.manifest_path.parent.resolve()
        self.entrypoint = (scripts_dir / entrypoint).resolve()
        try:
            self.entrypoint.relative_to(scripts_dir)
        except ValueError as exc:
            raise ValueError(f"Skill 脚本入口不能离开 scripts 目录：{entrypoint}") from exc
        if self.entrypoint.suffix.lower() != ".py" or not self.entrypoint.is_file():
            raise ValueError(f"Skill 脚本入口必须是存在的 Python 文件：{self.entrypoint}")

        timeout = float(manifest.get("timeout_seconds", 120))
        if not 1 <= timeout <= 300:
            raise ValueError("Skill 脚本 timeout_seconds 必须在 1 到 300 之间")
        self.timeout_seconds = timeout

    def execute(self, **arguments: Any) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if self.artifact_dir_provider is not None:
            artifact_dir = self.artifact_dir_provider()
            if artifact_dir is not None:
                context["artifact_dir"] = str(artifact_dir)

        request = {
            "protocol": SCRIPT_PROTOCOL,
            "arguments": arguments,
            "context": context,
        }
        environment = os.environ.copy()
        environment.update(
            {key: value for key, value in self.env_overrides.items() if value}
        )
        try:
            completed = subprocess.run(
                [self.python_executable, str(self.entrypoint)],
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=self.timeout_seconds,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Skill 脚本 {self.name} 超过 {self.timeout_seconds:g} 秒未返回"
            ) from exc

        stdout = completed.stdout.strip()
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as exc:
            stderr = completed.stderr.strip()
            detail = stderr or stdout or "没有输出"
            raise RuntimeError(f"Skill 脚本 {self.name} 未返回有效 JSON：{detail}") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"Skill 脚本 {self.name} 返回值必须是 JSON 对象")
        if completed.returncode != 0 or result.get("ok") is False:
            error = result.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("type") or error)
            else:
                message = str(error or completed.stderr.strip() or "执行失败")
            raise RuntimeError(f"Skill 脚本 {self.name} 执行失败：{message}")
        return result

    def spec(self) -> ToolSpec:
        return ToolSpec(
            self.name,
            self.description,
            self.parameters,
            self.execute,
        )


def load_skill_script_tool(
    manifest_path: Path,
    **runtime_options: Any,
) -> ToolSpec:
    return SkillScriptTool(manifest_path, **runtime_options).spec()
