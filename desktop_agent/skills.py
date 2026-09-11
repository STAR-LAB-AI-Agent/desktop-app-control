"""项目内 Skill 的发现、延迟加载和路由。"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tools.skill_scripts import load_skill_script_tool


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    directory: Path
    handler: Any
    script_manifests: tuple[Path, ...] = ()

    def instructions(self) -> str:
        text = (self.directory / "SKILL.md").read_text(encoding="utf-8")
        return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)


@dataclass(frozen=True)
class SkillMatch:
    definition: SkillDefinition
    variables: dict[str, Any]


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._skills: dict[str, SkillDefinition] = {}
        self._skill_tool_names: dict[str, tuple[str, ...]] = {}

    def discover(self) -> None:
        self._skills.clear()
        self._skill_tool_names.clear()
        if not self.root.exists():
            return
        for skill_md in sorted(self.root.glob("*/SKILL.md")):
            metadata = _read_frontmatter(skill_md)
            name = metadata.get("name", "").strip()
            description = metadata.get("description", "").strip()
            if not name or not description:
                raise ValueError(f"Skill 缺少 name 或 description：{skill_md}")
            if name != skill_md.parent.name:
                raise ValueError(
                    f"Skill 名称必须与文件夹一致：name={name!r}, folder={skill_md.parent.name!r}"
                )
            if name in self._skills:
                raise ValueError(f"Skill 名称重复：{name}")
            handler = _load_handler(skill_md.parent, name)
            if handler is None:
                raise ValueError(f"Skill 缺少 skill.py：{skill_md.parent}")
            if getattr(handler, "name", None) != name:
                raise ValueError(f"skill.py 的 name 与 SKILL.md 不一致：{skill_md.parent}")
            self._skills[name] = SkillDefinition(
                name=name,
                description=description,
                directory=skill_md.parent,
                handler=handler,
                script_manifests=tuple(
                    sorted((skill_md.parent / "scripts").glob("*.tool.json"))
                ),
            )

    def route(self, task: str) -> SkillMatch | None:
        matches = [
            definition
            for definition in self._skills.values()
            if definition.handler is not None and definition.handler.matches(task)
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"任务同时匹配多个 Skill：{[item.name for item in matches]}")
        definition = matches[0]
        return SkillMatch(definition, definition.handler.prepare(task))

    def get(self, name: str) -> SkillDefinition:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise ValueError(f"未知 Skill：{name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._skills)

    def build_tool_specs(self, **dependencies: Any) -> list[Any]:
        """创建各 Skill 声明的可选专项工具。"""
        specs: list[Any] = []
        self._skill_tool_names.clear()
        for definition in self._skills.values():
            if not definition.script_manifests:
                continue
            skill_specs = [
                load_skill_script_tool(manifest, **dependencies)
                for manifest in definition.script_manifests
            ]
            names = tuple(str(spec.name) for spec in skill_specs)
            if len(names) != len(set(names)):
                raise ValueError(f"Skill 专项工具名称重复：{definition.name}")
            self._skill_tool_names[definition.name] = names
            specs.extend(skill_specs)
        return specs

    def tool_names(self, skill_name: str) -> tuple[str, ...]:
        return self._skill_tool_names.get(skill_name, ())

    def all_tool_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for names in self._skill_tool_names.values()
            for name in names
        )


def _read_frontmatter(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as file:
        if file.readline().strip() != "---":
            return metadata
        for line in file:
            stripped = line.strip()
            if stripped == "---":
                break
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"\'')
    return metadata


def _load_handler(directory: Path, name: str):
    module_path = directory / "skill.py"
    if not module_path.exists():
        return None
    module_name = "_desktop_agent_skill_" + re.sub(r"[^A-Za-z0-9_]", "_", name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Skill 模块：{module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_skill", None)
    if factory is None:
        raise ValueError(f"Skill 缺少 create_skill()：{module_path}")
    return factory()
