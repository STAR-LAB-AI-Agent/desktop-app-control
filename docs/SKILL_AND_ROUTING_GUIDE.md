# Skill 与路由配置指南

这份指南说明如何给 Desktop Agent 增加一个场景 Skill。目标是让你只需要新增一个
文件夹，不必修改 Agent 主循环、工作流注册表或审核器。

## 1. 先理解调用流程

```text
用户输入任务
  → SkillRegistry 扫描 skills/*/SKILL.md
  → 逐个调用 skill.py 的 matches(task)
  → 命中后调用 prepare(task) 提取变量
  → build_review(variables) 生成审核信息
  → 可选的 prepare_execution(...) 做确定性预检
  → 可选读取 scripts/*.tool.json，把标准脚本适配为本项目工具
  → 加载 SKILL.md 正文作为专用提示词
  → SkillTaskWorkflow 使用现有桌面工具逐步执行
```

路由不需要维护中央配置表。项目启动时会自动扫描 `skills/` 的直接子目录。
如果没有 Skill 命中，任务仍然进入通用工作流；如果同时命中多个 Skill，任务会停止并
报告冲突，所以 `matches()` 不要写得过宽。

## 2. 最小目录结构

假设要增加一个“用记事本记录文字”的 Skill：

```text
skills/
└── notepad-note/
    ├── SKILL.md
    ├── skill.py
    └── scripts/       # 可选：可被不同 Agent Runtime 执行的脚本
```

`agents/openai.yaml` 是可选的展示信息，不参与这个项目的运行时路由。

## 3. 编写 SKILL.md

复制下面模板，并把名称、触发描述和流程换成自己的内容：

```markdown
---
name: notepad-note
description: Use when the user asks the desktop agent to open Windows Notepad and type a note.
---

# Notepad Note

## Outcome

Open Windows Notepad, enter the requested text, and stop after the text is visibly present.

## Workflow

1. If Notepad is not visible, call `open_app_via_windows_search` with `app_name` set to
   `Notepad`. Do not click search history, recommendations, or taskbar icons.
2. Wait until the editor is visible.
3. Type the exact `note_text` supplied by the route variables.
4. Confirm the text is visible, then call `finish`.

## Boundaries

- Do not save or overwrite a file unless the user explicitly asks.
- If Windows asks for administrator permission, stop.
```

注意：

- `name` 使用小写字母、数字和连字符，并且必须与文件夹同名。
- `description` 决定这个 Skill 适用于什么场景，要具体，避免写成“处理桌面任务”。
- 正文只写会改变 Agent 决策的流程、恢复条件和边界。
- `SKILL.md` 是提示词，不直接执行 Python。

## 4. 编写 skill.py 路由

下面是可以直接修改的完整模板：

```python
from __future__ import annotations

from typing import Any


class NotepadNoteSkill:
    name = "notepad-note"

    def matches(self, task: str) -> bool:
        """只判断这个任务是否属于当前 Skill。"""
        return "记事本" in task and any(word in task for word in ("输入", "记录", "写"))

    def prepare(self, task: str) -> dict[str, Any]:
        """从用户任务中提取要交给 SKILL.md 使用的结构化变量。"""
        return {"note_text": task}

    @staticmethod
    def build_review(variables: dict[str, Any]) -> dict[str, Any]:
        """配置审核窗口中显示的风险、摘要和提醒。"""
        return {
            "risk": "low",
            "summary": "打开 Windows 记事本并输入用户提供的文字。",
            "warnings": ["默认不会保存或覆盖文件。"],
        }


def create_skill() -> NotepadNoteSkill:
    """SkillRegistry 通过这个固定入口创建路由处理器。"""
    return NotepadNoteSkill()
```

必须提供的方法：

| 方法 | 用途 | 要求 |
| --- | --- | --- |
| `matches(task)` | 判断是否命中 | 返回 `bool`，条件要有区分度 |
| `prepare(task)` | 提取路由变量 | 返回可 JSON 序列化的字典 |
| `build_review(variables)` | 生成审核配置 | 风险只能是 `low`、`medium`、`high` |
| `create_skill()` | 创建 Skill 实例 | 函数名固定 |

## 5. 可选：执行前做确定性预检

如果模型操作界面前必须先获得可靠数据，可以增加 `prepare_execution()`。论文 Skill
就是先查找唯一 PDF，再把精确路径交给视觉 Agent：

```python
class MySkill:
    exclude_tools_after_prepare = ("find_desktop_file",)

    @staticmethod
    def prepare_execution(tools, variables):
        result = tools.execute(
            "find_desktop_file",
            {"query": variables["file_query"], "extension": ".pdf"},
            explanation="在桌面唯一确定要使用的 PDF",
        )
        if not result["ok"]:
            raise RuntimeError("没有找到唯一匹配的 PDF")
        return {**variables, "file_path": result["matches"][0]}
```

`exclude_tools_after_prepare` 可以隐藏已经完成使命的工具，防止模型重复调用。
确定性检查失败时应直接给出清楚的错误，不要让模型猜文件、账号或不可见状态。

## 6. 可选：为 Skill 增加跨 Runtime 专项脚本

为了兼容 nanobot、Codex 等 Agent Skills Runtime，确定性逻辑应放在标准的 `scripts/`
目录，不要依赖某个 Runtime 才能导入的 `tools.py`。脚本应支持直接命令行调用，并以
JSON 作为稳定的输入输出格式。

本项目额外支持 `agent-skill-script/v1` 适配协议：在脚本旁增加一个 `*.tool.json` 清单，
声明 `name`、`description`、`entrypoint`、`parameters` 和 `timeout_seconds`。启动时会把
同一份脚本自动包装成 `ToolSpec`，且只向所属 Skill 暴露。其他 Runtime 不需要理解这个
清单，只需按 `SKILL.md` 中的相对路径直接执行脚本。

统一 stdin 输入：

```json
{
  "protocol": "agent-skill-script/v1",
  "arguments": {"expected_segment": "Section 1"},
  "context": {"artifact_dir": "可选的截图输出目录"}
}
```

统一 stdout 输出必须是单个 JSON 对象；成功时返回 `{"ok": true, ...}` 且退出码为 0，
失败时返回 `{"ok": false, "error": {...}}` 且退出码非 0。密钥只能通过环境变量传入，
不得放进命令行参数、清单或日志。

专项工具适合把截图立即转换成结构化状态。例如论文翻译 Skill 的
`inspect_chatgpt_translation_state` 只识别停止按钮、发送按钮、回答操作按钮和窗口遮挡，
返回 `generating`、`complete`、`obscured`、`not_visible` 或 `unknown`。工具分析的原始截图
也会保存到 Runtime 提供的 artifact 目录中。

不要只返回截图路径：下一轮规划器无法直接读取路径指向的图片。专项截图脚本应在内部
完成视觉判断，并把有限、明确的状态作为 JSON 返回。

### nanobot 加载方式

nanobot 会扫描当前 workspace 的 `skills/<skill-name>/SKILL.md`。把完整 Skill 文件夹复制
到 nanobot workspace 的 `skills/` 下，并确保脚本需要的环境变量已设置即可：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"
python .\skills\chatgpt-paper-abstract\scripts\inspect_chatgpt_translation_state.py --describe
```

`--describe` 应返回 `agent-skill-script/v1` 和脚本名称。实际任务中，nanobot 读取
`SKILL.md` 后通过自己的 shell 工具执行其中给出的相对脚本路径。本项目则自动读取
`*.tool.json`，所以模型看到的是同名原生工具；两边最终执行的是同一个 Python 文件。

## 7. 当前可用工具

| 工具 | 用途 |
| --- | --- |
| `open_app_via_windows_search` | 原子完成 Win+S、覆盖旧查询、输入软件名和 Enter；忽略搜索历史与推荐项 |
| `click_target` | 通过视觉定位单击目标 |
| `double_click_target` | 双击文件、桌面图标等目标 |
| `assert_visible` | 确认某个结果已经出现 |
| `type_text` | 向当前焦点输入文本 |
| `submit_search_query` | 在已聚焦的搜索框中原子输入查询并按 Enter，忽略历史和自动补全 |
| `press_key` | 按单个键，例如 Enter |
| `hotkey` | 执行快捷键组合 |
| `scroll` | 滚动页面 |
| `wait` | 最长 10 秒的短等待 |
| `sleep` | 最长 120 秒、可被终止的长等待 |
| `find_desktop_file` | 只读查找桌面文件 |
| `inspect_chatgpt_translation_state` | 论文翻译 Skill 专用：截图并判断生成、完成或遮挡状态 |

在 `SKILL.md` 里直接写工具名，模型就能在该场景中选择它。新增底层工具时，在
`desktop_agent/tools/` 中创建 `ToolSpec`，然后加入 `DesktopToolbox.build_registry()`。
需要启动应用时，优先直接写 `open_app_via_windows_search` 及准确的 `app_name`，不要让
模型拆分搜索步骤或根据 Windows 搜索中的历史记录、推荐项选择目标。
需要在应用内部执行搜索时，先让模型聚焦正确的输入框，再使用 `submit_search_query`；
不要把输入和 Enter 拆开，也不要让 Skill 指示模型点击自动补全或历史记录。

## 8. 测试路由

先使用 dry-run，确认任务命中了正确 Skill，而且不会操作桌面：

```powershell
python main.py run "在记事本记录今天完成了测试" --dry-run
```

审核输出中应看到：

```json
{
  "tool": "skill_agent_loop",
  "arguments": {
    "skill": "notepad-note"
  }
}
```

验证 Skill 文件格式：

```powershell
$env:PYTHONUTF8 = "1"
D:\Anaconda3\python.exe "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" ".\skills\notepad-note"
```

最后运行项目测试：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## 8. 配置检查清单

- 文件夹名称与 `SKILL.md` 的 `name` 一致。
- `matches()` 能命中目标说法，但不会命中大量无关任务。
- `prepare()` 提取了 `SKILL.md` 中使用的全部变量。
- `build_review()` 明确说明外部发送、上传、覆盖、删除等影响。
- 每个不可无限重试的步骤都有停止条件。
- 登录、验证码、付款、删除等高影响界面不会被默认绕过。
- `--dry-run` 显示了预期的 Skill 名称和审核信息。

现有论文 Skill 是完整参考：`skills/chatgpt-paper-abstract/`。
