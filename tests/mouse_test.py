"""用视觉模型定位桌面元素，并通过 pyautogui 移动或点击。

运行示例：
    conda run -n desktop-ai python tests/mouse_test.py
    conda run -n desktop-ai python tests/mouse_test.py --click

需要提前设置环境变量 DEEPSEEK_API_KEY。不要把密钥写进源码。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

import pyautogui


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash-vision-exp"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


@dataclass(frozen=True)
class PointPrediction:
    x: int
    y: int
    confidence: float
    description: str


def screenshot_data_url() -> tuple[str, int, int]:
    image = pyautogui.screenshot()
    width, height = image.size
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", width, height


def extract_json(text: str) -> dict[str, object]:
    """兼容纯 JSON 和 Markdown 代码块两种返回。"""
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"模型没有返回 JSON：{text!r}")
    return json.loads(match.group(0))


def locate_target(target: str) -> PointPrediction:
    api_key = DEEPSEEK_API_KEY
    if not api_key:
        raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY")

    image_url, width, height = screenshot_data_url()
    prompt = f"""
你是桌面 GUI 定位器。请在截图中找到：{target}

截图的原始屏幕尺寸是 width={width}, height={height}。
坐标原点在左上角，x 向右增大，y 向下增大。
请返回目标内部一个适合鼠标点击的安全点，坐标必须基于上述原始尺寸，
不要返回边缘、按钮文字间隙或其他控件。

只返回一个 JSON 对象，不要解释：
{{"x": 0, "y": 0, "confidence": 0.0, "description": "目标说明"}}
""".strip()

    payload = {
        "model": MODEL,
        # 坐标定位不需要长推理；关闭 thinking 可避免较小的输出预算全部
        # 消耗在 reasoning_content，导致最终 content 为空。
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url, "detail": "original"},
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 1024,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API 请求失败（HTTP {exc.code}）：{body}") from exc

    if not result.get("choices"):
        raise RuntimeError(f"DeepSeek API 没有返回 choices：{result!r}")

    choice = result["choices"][0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if not content.strip():
        usage = result.get("usage") or {}
        reasoning = message.get("reasoning_content") or ""
        raise RuntimeError(
            "DeepSeek 返回了空 content；"
            f"finish_reason={choice.get('finish_reason')!r}, "
            f"completion_tokens={usage.get('completion_tokens')!r}, "
            f"reasoning_tokens="
            f"{(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')!r}, "
            f"reasoning_content_length={len(reasoning)}"
        )
    prediction = extract_json(content)
    point = PointPrediction(
        x=int(prediction["x"]),
        y=int(prediction["y"]),
        confidence=float(prediction.get("confidence", 0.0)),
        description=str(prediction.get("description", "")),
    )

    if not (0 <= point.x < width and 0 <= point.y < height):
        raise ValueError(f"模型返回的坐标越界：{point}，屏幕尺寸={width}x{height}")
    return point


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="百度主页中央的搜索输入框")
    parser.add_argument(
        "--click",
        action="store_true",
        help="点击模型返回的坐标；默认仅移动鼠标，便于人工检查",
    )
    parser.add_argument("--min-confidence", type=float, default=0.75)
    args = parser.parse_args()

    screen_size = pyautogui.size()
    print("屏幕尺寸：", screen_size)
    prediction = locate_target(args.target)
    print("模型定位结果：", prediction)

    if prediction.confidence < args.min_confidence:
        raise RuntimeError(
            f"置信度 {prediction.confidence:.2f} 低于阈值 {args.min_confidence:.2f}，取消操作"
        )

    pyautogui.moveTo(prediction.x, prediction.y, duration=0.8)
    if args.click:
        pyautogui.click()
        print("已点击：", (prediction.x, prediction.y))
    else:
        print("已移动鼠标但未点击；确认位置后可加 --click 重试。")


if __name__ == "__main__":
    main()
