# 技能与路由配置指南

这份指南说明如何给桌面智能体增加一个场景技能。目标是让你只需要新增一个
文件夹，不必修改智能体主循环、工作流注册表或审核器。

## 1. 先理解调用流程

```text
用户输入任务
  → 读取 skills/config.json 中的启用状态和优先级
  → SkillRegistry 扫描 skills/*/SKILL.md
  → 大模型读取 general 和全部已启用 Skill 的 description
  → 大模型返回唯一 route、confidence 和 reason
  → 选择专项 Skill 时调用 prepare(task) 提取变量
  → build_review(variables) 生成审核信息
  → 可选的 prepare_execution(...) 做确定性预检
  → 可选读取 scripts/*.tool.json，把标准脚本适配为本项目工具
  → 加载 SKILL.md 正文作为专用提示词
  → SkillTaskWorkflow 使用现有桌面工具逐步执行
```

项目启动时会自动扫描 `skills/` 的直接子目录，并通过 `skills/config.json` 统一覆盖
启用状态和路由优先级。没有写进配置的技能仍会被发现，默认启用且优先级为 0。
`description` 是大模型路由的主要依据。任务不明确属于专项技能时，模型选择 `general`；
`priority` 仅在多个专项技能语义上同样合适时作为平局提示。模型返回未知路由或专项路由
置信度低于 0.60 时，运行时会安全回退到 `general`。

## 2. 最小目录结构

假设要增加一个“用记事本记录文字”的技能：

```text
skills/
├── config.json         # 统一启用状态和路由优先级
├── manage.py           # 技能管理命令行入口
└── notepad-note/
    ├── SKILL.md
    ├── skill.py
    └── scripts/       # 可选：可被不同智能体运行时执行的脚本
```

`agents/openai.yaml` 是可选的展示信息，不参与这个项目的运行时路由。

在 `skills/config.json` 中增加可选配置：

```json
{
  "version": 1,
  "skills": {
    "notepad-note": {
      "enabled": true,
      "priority": 50
    }
  }
}
```

- `enabled` 控制是否加载技能。
- `priority` 取值范围为 -1000 到 1000，只在多个专项技能同样合适时提供平局参考。
- 未配置的技能默认 `enabled=true`、`priority=0`。

统一管理命令：

```powershell
python skills/manage.py list
python skills/manage.py check
python skills/manage.py enable notepad-note
python skills/manage.py disable notepad-note
python skills/manage.py priority notepad-note 50
```

## 3. 编写 SKILL.md

复制下面模板，并把名称、触发描述和流程换成自己的内容：

```markdown
---
name: notepad-note
description: 当用户要求桌面智能体打开 Windows 记事本并输入一段文字时使用。
---

# 使用记事本记录文字

## 目标

打开 Windows 记事本，输入用户要求的文字，并在确认文字已经显示后结束任务。

## 流程

1. 如果记事本尚未显示，调用 `open_app_via_windows_search`，并将 `app_name` 设置为
   `Notepad`。不要点击搜索历史、推荐项或任务栏图标。
2. 等待编辑区显示。
3. 输入路由变量提供的准确 `note_text`。
4. 确认文字已经显示，然后调用 `finish`。

## 边界

- 除非用户明确要求，否则不要保存或覆盖文件。
- 如果 Windows 请求管理员权限，停止执行。
```

注意：

- `name` 使用小写字母、数字和连字符，并且必须与文件夹同名。
- `description` 会直接交给大模型做路由，必须同时说明适用和不适用的场景，避免写成
  “处理桌面任务”这类过宽描述。
- 正文只写会改变智能体决策的流程、恢复条件和边界。
- `SKILL.md` 是提示词，不直接执行 Python。

## 4. 编写 skill.py 参数准备器

下面是可以直接修改的完整模板：

```python
from __future__ import annotations

from typing import Any


class NotepadNoteSkill:
    name = "notepad-note"

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
    """SkillRegistry 通过这个固定入口创建参数准备器。"""
    return NotepadNoteSkill()
```

必须提供的方法：

| 方法 | 用途 | 要求 |
| --- | --- | --- |
| `prepare(task)` | 提取路由变量 | 返回可 JSON 序列化的字典 |
| `build_review(variables)` | 生成审核配置 | 风险只能是 `low`、`medium`、`high` |
| `create_skill()` | 创建技能实例 | 函数名固定 |

## 5. 可选：执行前做确定性预检

如果模型操作界面前必须先获得可靠数据，可以增加 `prepare_execution()`。论文技能
就是先查找唯一 PDF，再把精确路径交给视觉智能体：

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

## 6. 可选：为技能增加跨运行时专项脚本

为了兼容 nanobot、Codex 等智能体技能运行时，确定性逻辑应放在标准的 `scripts/`
目录，不要依赖某个运行时才能导入的 `tools.py`。脚本应支持直接通过命令行调用，并以
JSON 作为稳定的输入输出格式。

本项目额外支持 `agent-skill-script/v1` 适配协议：在脚本旁增加一个 `*.tool.json` 清单，
声明 `name`、`description`、`entrypoint`、`parameters` 和 `timeout_seconds`。启动时会把
同一份脚本自动包装成 `ToolSpec`，且只向所属技能暴露。其他运行时不需要理解这个
清单，只需按 `SKILL.md` 中的相对路径直接执行脚本。

统一标准输入（stdin）：

```json
{
  "protocol": "agent-skill-script/v1",
  "arguments": {"expected_segment": "Section 1"},
  "context": {"artifact_dir": "可选的截图输出目录"}
}
```

统一标准输出（stdout）必须是单个 JSON 对象；成功时返回 `{"ok": true, ...}` 且退出码为 0，
失败时返回 `{"ok": false, "error": {...}}` 且退出码非 0。密钥只能通过环境变量传入，
不得放进命令行参数、清单或日志。

专项工具适合把截图立即转换成结构化状态。例如论文翻译技能的
`inspect_chatgpt_translation_state` 只识别停止按钮、发送按钮、回答操作按钮和窗口遮挡，
返回 `generating`、`complete`、`obscured`、`not_visible` 或 `unknown`。工具分析的原始截图
也会保存到运行时提供的产物目录中。

不要只返回截图路径：下一轮规划器无法直接读取路径指向的图片。专项截图脚本应在内部
完成视觉判断，并把有限、明确的状态作为 JSON 返回。

### nanobot 加载方式

nanobot 会扫描当前工作区的 `skills/<skill-name>/SKILL.md`。把完整技能文件夹复制
到 nanobot 工作区的 `skills/` 下，并确保脚本需要的环境变量已设置即可：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"
python .\skills\chatgpt-paper-abstract\scripts\inspect_chatgpt_translation_state.py --describe
```

`--describe` 应返回 `agent-skill-script/v1` 和脚本名称。实际任务中，nanobot 读取
`SKILL.md` 后通过自己的命令行工具执行其中给出的相对脚本路径。本项目则自动读取
`*.tool.json`，所以模型看到的是同名原生工具；两边最终执行的是同一个 Python 文件。

## 7. 当前可用工具

| 工具 | 用途 |
| --- | --- |
| `open_app_via_windows_search` | 原子完成 Win+S、覆盖旧查询、输入软件名和按回车键；忽略搜索历史与推荐项 |
| `click_target` | 通过视觉定位单击目标 |
| `double_click_target` | 双击文件、桌面图标等目标 |
| `assert_visible` | 确认某个结果已经出现 |
| `type_text` | 向当前焦点输入文本 |
| `submit_search_query` | 在已聚焦的搜索框中原子输入查询并按回车键，忽略历史和自动补全 |
| `press_key` | 按单个键，例如回车键 |
| `hotkey` | 执行快捷键组合 |
| `scroll` | 滚动页面 |
| `wait` | 最长 10 秒的短等待 |
| `sleep` | 最长 120 秒、可被终止的长等待 |
| `find_desktop_file` | 只读查找桌面文件 |
| `inspect_chatgpt_translation_state` | 论文翻译技能专用：截图并判断生成、完成或遮挡状态 |
| `inspect_video_playback_state` | 视频播放技能专用：比较两张截图并判断搜索、加载、暂停或播放状态 |

在 `SKILL.md` 里直接写工具名，模型就能在该场景中选择它。新增底层工具时，在
`desktop_agent/tools/` 中创建 `ToolSpec`，然后加入 `DesktopToolbox.build_registry()`。
需要启动应用时，优先直接写 `open_app_via_windows_search` 及准确的 `app_name`，不要让
模型拆分搜索步骤或根据 Windows 搜索中的历史记录、推荐项选择目标。
需要在应用内部执行搜索时，先让模型聚焦正确的输入框，再使用 `submit_search_query`；
不要把输入和回车键拆开，也不要让技能指示模型点击自动补全或历史记录。

## 8. 测试路由

先使用 `--dry-run`，确认大模型返回了正确路由，而且不会操作桌面：

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

任务 JSON 的 `skill_route` 还会记录模型的 `route`、`confidence` 和 `reason`。添加新技能
时不需要修改路由 Python 代码；重点是把 frontmatter 的 `description` 写清楚。

检查技能目录和配置：

```powershell
python skills/manage.py check
```

最后运行项目测试：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

需要独立运行、无需启动主智能体循环的脚本与命令行接口测试统一放在
`tests/script_cli/`。其中自动测试不能访问网络或操作桌面；手动截图/API 测试必须通过
文件名和说明明确标注。

## 9. 配置检查清单

- 文件夹名称与 `SKILL.md` 的 `name` 一致。
- `skills/config.json` 中的名称存在对应目录，启用状态和优先级正确。
- `description` 清楚区分适用和不适用场景，模型能据此与 `general` 及其他技能区分。
- `prepare()` 提取了 `SKILL.md` 中使用的全部变量。
- `build_review()` 明确说明外部发送、上传、覆盖、删除等影响。
- 每个不可无限重试的步骤都有停止条件。
- 登录、验证码、付款、删除等高影响界面不会被默认绕过。
- `--dry-run` 显示了预期的技能名称和审核信息。

现有论文翻译技能和网页视频播放技能是完整参考：
`skills/chatgpt-paper-abstract/`、`skills/web-video-playback/`。
