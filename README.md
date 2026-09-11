# Desktop AI Agent

一个使用视觉模型定位界面元素、使用 PyAutoGUI 执行动作的桌面 Agent MVP。

## 工作流

```text
提交任务
  → 生成动作计划
  → 任务审核（输入、敏感信息、风险）
  → 展示计划并等待批准
  → 顺序调用小型工具
  → 视觉确认最终结果
  → 写入该任务自己的日志目录
```

当前实现了百度搜索工作流、由视觉模型逐步选择小型工具的低风险通用工作流，
以及按任务语义自动路由的场景 Skill。

## 启动

在 `desktop-ai` 环境中设置 `DEEPSEEK_API_KEY`，然后从项目根目录运行：

```powershell
python main.py search "要搜索的内容"
```

### 桌面悬浮任务框

双击 `launch_agent.bat` 可以无控制台启动悬浮任务框。窗口始终置顶，输入自然语言
任务后按 Enter 执行，按 Esc 清空。

执行期间悬浮窗保持可见并显示红色“终止”按钮。终止会立即阻止后续规划和工具调用；
若正在等待模型响应，则在当前请求返回后停止。它与命令行共用 `main.py` 中的
`AgentConfig` 参数和 API key。

程序会先输出审核报告和完整动作计划，输入 `y` 后才会操作桌面。

只查看计划：

```powershell
python main.py search "要搜索的内容" --dry-run
```

审核通过后自动批准：

```powershell
python main.py search "要搜索的内容" --yes
```

执行通用桌面任务：

```powershell
python main.py run "在当前百度页面搜索 Python 教程"
```

默认最大规划步数为 40。可通过 `--max-steps` 或悬浮窗参数调整；长任务可调用
最长 120 秒且支持终止的 `sleep`，短页面切换继续使用 `wait`。

翻译桌面论文的 Abstract 以及 Section 1 到 Section 5
（会自动命中 `chatgpt-paper-abstract` Skill）：

```powershell
python main.py run "翻译 GROOT 论文"
```

该 Skill 会先查找桌面上名称唯一匹配的 PDF，再打开 ChatGPT 桌面版、新建聊天、
选择 Work、上传精确匹配的文件，然后依次请求翻译 Abstract、Section 1 到 Section 5。
每段提交后都会等待生成完成；没有匹配或存在多个匹配时会停止，不会猜测文件；
若遇到登录或身份验证，也会停止并交给用户处理。

完全信任模式会跳过人工批准，但仍保留敏感信息检查、危险任务拦截、
定位置信度、最大步数和 PyAutoGUI 紧急停止：

```powershell
python main.py run "在当前页面找到搜索框并搜索天气" --full-trust
```

也可以在 `main.py` 中设置 `FULL_TRUST = True`，将它作为本机默认值。

限制原子工具调用数和指定统一日志目录：

```powershell
python main.py run "在当前页面搜索天气" --max-operations 20 --logs-dir logs
```

每个任务会按照“本地时间_任务简介”创建独立目录：

```text
logs/
└── 2026-09-11_10-03-04-123_翻译_GROOT_论文/
    ├── images/
    │   ├── 001_find_desktop_file_after.png
    │   ├── 002_hotkey_after.png
    │   └── 003_click_target_grid.png
    ├── json/
    │   ├── task.json
    │   ├── review.json
    │   ├── result.json
    │   └── events.jsonl
    └── operations/
        ├── 001_find_desktop_file.json
        ├── 002_hotkey.json
        └── steps.jsonl
```

`operations/steps.jsonl` 和每一步独立 JSON 会记录原子操作编号、工具名称、模型对该步
操作的讲解、参数、返回结果、调用次数、画面变化分数和截图路径。当点击后
`screen_changed=false` 时，通用工作流会结合新截图反思，
改用更具体的目标描述、键盘操作或等待。搜索输入后优先使用 Enter；确认没有结果时，
才使用带网格辅助线的鼠标点击作为回退。

悬浮任务框下方提供最大步数、原子操作数、定位置信度、网格行列数和
完全信任设置。参数只影响本次启动的悬浮窗任务，不修改 `main.py` 默认值。

也可以安装为命令：

```powershell
python -m pip install -e .
desk-agent search "要搜索的内容"
```

将鼠标移至屏幕左上角可以触发 PyAutoGUI 的紧急停止机制。

## 目录职责

- `main.py`：本机默认参数和启动入口。
- `desktop_agent/config.py`：统一的 `AgentConfig`。
- `desktop_agent/logging.py`：创建任务日志目录并统一保存 JSON、事件和原子操作。
- `desktop_agent/agent.py`：封装模型、工具、审核、工作流和运行时。
- `desktop_agent/vision.py`：截图和视觉坐标定位。
- `desktop_agent/tools/base.py`：工具协议和注册表。
- `desktop_agent/tools/mouse.py`：鼠标、滚动和视觉确认工具。
- `desktop_agent/tools/keyboard.py`：文本、按键和快捷键工具。
- `desktop_agent/tools/system.py`：短 `wait` 和可终止的长 `sleep` 等通用控制工具。
- `desktop_agent/tools/files.py`：只读查找桌面文件，避免模型猜测上传路径。
- `desktop_agent/tools/grid.py`：点击定位使用的网格辅助线。
- `desktop_agent/tools/monitor.py`：调用计数、原子动作讲解、截图和画面变化检测。
- `desktop_agent/tools/toolbox.py`：组装默认工具集。
- `desktop_agent/workflows.py`：将工具组合成具体任务。
- `desktop_agent/skills.py`：发现、加载和路由项目内的场景 Skill。
- `desktop_agent/audit.py`：执行前任务审核。
- `desktop_agent/runtime.py`：审批、状态流转、异常处理和日志。
- `desktop_agent/cli.py`：启动入口及人工审批交互。
- `skills/<skill-name>/SKILL.md`：场景的长程规划、恢复策略和安全边界。
- `skills/<skill-name>/skill.py`：任务匹配、变量提取、审核配置和可选执行前预检。
- `skills/<skill-name>/scripts/`：跨 Runtime 的确定性脚本；可由 nanobot 直接执行，也可通过清单适配成本项目工具。
- `docs/SKILL_AND_ROUTING_GUIDE.md`：新增 Skill 和配置路由的中文教程与模板。

日志统一写入 `logs/<时间_任务简介>/`。新增固定工作流时，实现一个 `Workflow` 并注册到
`DesktopAgent`；新增场景 Skill 时只需要增加 Skill 文件夹，不需要修改主工作流或审核器。

`main.py` 通过 `AgentConfig` 向 Agent 传入 API、模型、信任模式、定位阈值、
最大步数、动作间隔和日志路径。新增工具时创建一个 `ToolSpec`，再调用
`agent.register_tool(...)`；新增任务时调用 `agent.register_workflow(...)`。

当任务需要启动尚未显示的软件时，Agent 必须调用原子工具
`open_app_via_windows_search`。工具内部一次完成 `Win+S`、覆盖旧查询、输入软件名和
按 Enter；模型不会在中途根据搜索历史、推荐项或最近使用记录做点击决策。工具返回后，
Agent 才根据新截图确认窗口是否出现。默认名称映射配置在
`AgentConfig.application_search_names`，例如浏览器使用 `Edge`、音乐软件使用“音乐”、
翻译软件使用 `ChatGPT`；可继续添加自己的软件别名。

在浏览器或应用内搜索时，Agent 聚焦搜索框后调用 `submit_search_query`，原子完成覆盖
旧文本、输入查询和按 Enter。自动补全、历史记录、曾搜索内容和推荐词不会成为下一轮
规划依据；模型只在工具返回后的结果页继续观察。

## 扩展 Skill

每个 Skill 使用独立子目录，例如：

```text
skills/
└── chatgpt-paper-abstract/
    ├── SKILL.md
    ├── skill.py
    ├── scripts/
    │   ├── inspect_chatgpt_translation_state.py
    │   └── inspect_chatgpt_translation_state.tool.json
    └── agents/openai.yaml
```

`skill.py` 只负责判断是否命中和提取变量；真正的视觉 API 调用、工具循环、日志、
终止控制与审核仍复用 Agent 主链路。这样不会为每个场景复制一套 Agent，也能保证
未命中的普通任务继续走通用工作流。

`SKILL.md + scripts/` 遵循 Agent Skills 的可移植结构。nanobot 等 Runtime 可按 Skill
中的相对路径直接运行脚本；本项目读取相邻的 `*.tool.json`，用
`agent-skill-script/v1` JSON 协议调用同一脚本，不维护第二份 Python 工具实现。

从零配置自己的 Skill，请直接阅读
[Skill 与路由配置指南](docs/SKILL_AND_ROUTING_GUIDE.md)。
