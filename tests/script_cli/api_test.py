"""调用视觉 API，返回可交给 Agent 执行的鼠标点击原子操作流。

这个文件是手动集成测试，不会真的点击鼠标。默认截取当前屏幕，也可以传入图片：

    conda run -n desktop-ai python tests/script_cli/api_test.py "点击百度搜索框"
    conda run -n desktop-ai python tests/script_cli/api_test.py "打开新聊天" --image screen.png

运行前设置 ``DEEPSEEK_API_KEY``。模型只允许返回 ``click_target``；如果一次点击
可能改变界面，本轮操作流必须在该点击后结束，由 Agent 重新截图后再规划下一步。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pyautogui
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_agent.vision import (  # noqa: E402
    DEFAULT_API_URL,
    DEFAULT_MODEL,
    DeepSeekVisionLocator,
)


CLICK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "click_target",
        "description": "根据自然语言描述定位并单击当前截图中的可见元素",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "足够精确、可从当前截图唯一定位的目标描述",
                }
            },
            "required": ["target"],
            "additionalProperties": False,
        },
    },
}


def build_prompt(task: str, image_size: tuple[int, int], max_clicks: int) -> str:
    """构造只允许鼠标单击操作的规划提示词。"""
    return f"""
你是桌面 Agent 的鼠标点击规划器。
用户任务：{task}
当前截图尺寸：width={image_size[0]}, height={image_size[1]}。

可用工具：
{json.dumps([CLICK_TOOL_SCHEMA], ensure_ascii=False)}

请根据当前截图返回一个鼠标点击原子操作流。规则：
1. 每一步只能调用 click_target，一步只代表一次鼠标单击。
2. target 必须描述当前截图中真实可见、可以唯一定位的界面元素，不返回坐标。
3. 不得使用双击、键盘输入、快捷键、滚动、等待或其他工具。
4. 不得猜测点击之后才会出现的控件。如果某次点击可能改变界面，必须在该步结束本轮；
   Agent 会执行后重新截图，再请求下一轮操作。
5. 不得点击搜索历史、自动补全、推荐内容或与任务无关的控件。
6. 最多返回 {max_clicks} 步。若任务已经完成，status=complete 且 operations=[]；
   若当前截图中没有可靠的可点击目标，status=blocked 且 operations=[]。
7. status=ready 时 operations 至少包含一步，index 从 1 连续递增。

只返回一个 JSON 对象，不要解释：
{{
  "status": "ready|blocked|complete",
  "operations": [
    {{
      "index": 1,
      "tool": "click_target",
      "arguments": {{"target": "当前截图中的精确目标描述"}},
      "reason": "为什么此时需要点击它"
    }}
  ],
  "summary": "本轮规划说明"
}}
""".strip()


def validate_click_flow(raw: dict[str, Any], max_clicks: int) -> dict[str, Any]:
    """校验并规范化模型返回值，避免测试把任意动作当作可执行工具调用。"""
    status = str(raw.get("status", "")).strip().lower()
    if status not in {"ready", "blocked", "complete"}:
        raise ValueError(f"无效 status：{status!r}")

    operations = raw.get("operations")
    if not isinstance(operations, list):
        raise ValueError("operations 必须是 JSON 数组")
    if len(operations) > max_clicks:
        raise ValueError(
            f"模型返回了 {len(operations)} 步，超过上限 {max_clicks}"
        )
    if status == "ready" and not operations:
        raise ValueError("status=ready 时必须至少返回一个点击操作")
    if status != "ready" and operations:
        raise ValueError(f"status={status} 时 operations 必须为空")

    normalized: list[dict[str, Any]] = []
    for expected_index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise ValueError(f"第 {expected_index} 个操作必须是 JSON 对象")
        if int(operation.get("index", 0)) != expected_index:
            raise ValueError(f"第 {expected_index} 个操作的 index 不连续")
        if operation.get("tool") != "click_target":
            raise ValueError(
                f"第 {expected_index} 个操作使用了不允许的工具："
                f"{operation.get('tool')!r}"
            )

        arguments = operation.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError(f"第 {expected_index} 个操作的 arguments 必须是对象")
        if set(arguments) != {"target"}:
            raise ValueError(
                f"第 {expected_index} 个操作只允许 target 参数：{arguments!r}"
            )
        target = str(arguments.get("target", "")).strip()
        if not target:
            raise ValueError(f"第 {expected_index} 个操作缺少 target")

        normalized.append(
            {
                "index": expected_index,
                "tool": "click_target",
                "arguments": {"target": target},
                "reason": str(operation.get("reason", "")).strip(),
            }
        )

    return {
        "status": status,
        "operations": normalized,
        "summary": str(raw.get("summary", "")).strip(),
    }


def load_image(image_path: Path | None) -> Image.Image:
    """读取指定截图；未指定时获取当前桌面。"""
    if image_path is None:
        return pyautogui.screenshot()
    with Image.open(image_path) as image:
        return image.convert("RGB")


def request_click_flow(
    task: str,
    image: Image.Image,
    *,
    max_clicks: int = 3,
    api_key: str | None = None,
    api_url: str = DEFAULT_API_URL,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """请求并校验一轮鼠标点击原子操作流。"""
    if not task.strip():
        raise ValueError("任务不能为空")
    if not 1 <= max_clicks <= 10:
        raise ValueError("max_clicks 必须在 1 到 10 之间")

    locator = DeepSeekVisionLocator(
        api_key=api_key,
        api_url=api_url,
        model=model,
    )
    raw = locator.ask_json(image, build_prompt(task.strip(), image.size, max_clicks))
    return validate_click_flow(raw, max_clicks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="让视觉 API 返回 click_target 鼠标点击原子操作流（不会实际点击）"
    )
    parser.add_argument("task", help="希望通过鼠标点击完成的桌面任务")
    parser.add_argument(
        "--image",
        type=Path,
        help="使用已有截图；不传时截取当前桌面",
    )
    parser.add_argument(
        "--max-clicks",
        type=int,
        default=3,
        help="单轮最多规划的点击数，默认 3",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("DEEPSEEK_API_URL", DEFAULT_API_URL),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image = load_image(args.image)
    flow = request_click_flow(
        args.task,
        image,
        max_clicks=args.max_clicks,
        api_url=args.api_url,
        model=args.model,
    )
    print(json.dumps(flow, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
