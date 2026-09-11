"""视觉定位：把桌面截图转换为可点击的屏幕坐标。"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from PIL import Image


DEFAULT_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"


@dataclass(frozen=True)
class PointPrediction:
    x: int
    y: int
    confidence: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _image_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"模型没有返回 JSON：{text!r}")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("模型返回值必须是 JSON 对象")
    return value


class DeepSeekVisionLocator:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = DEFAULT_API_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 90,
    ) -> None:
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.api_url = api_url
        self.model = model
        self.timeout = timeout

    def locate(self, image: Image.Image, target: str) -> PointPrediction:
        width, height = image.size
        prompt = f"""
你是桌面 GUI 定位器。请在截图中找到：{target}
截图原始尺寸为 width={width}, height={height}；原点在左上角，x 向右，y 向下。
截图可能叠加带编号的等分网格辅助线。可以用网格判断目标区域，但网格仅供参考，
最终仍须返回相对于整张原始截图的绝对像素坐标。
返回目标内部适合鼠标点击的安全点，坐标必须对应原始截图，不要选边缘。
只返回 JSON：
{{"x": 0, "y": 0, "confidence": 0.0, "description": "目标说明"}}
""".strip()
        raw = self.ask_json(image, prompt)
        prediction = PointPrediction(
            x=int(raw["x"]),
            y=int(raw["y"]),
            confidence=float(raw.get("confidence", 0)),
            description=str(raw.get("description", "")),
        )
        if not (0 <= prediction.x < width and 0 <= prediction.y < height):
            raise ValueError(
                f"模型坐标越界：({prediction.x}, {prediction.y})，截图={width}x{height}"
            )
        return prediction

    def ask_json(self, image: Image.Image, prompt: str) -> dict[str, Any]:
        """向视觉模型提问，并取得一个 JSON 对象。"""
        if not self._api_key:
            raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY")

        payload = {
            "model": self.model,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _image_data_url(image),
                                "detail": "original",
                            },
                        },
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 1024,
        }
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"视觉 API 请求失败（HTTP {exc.code}）：{body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"视觉 API 连接失败：{exc.reason}") from exc

        if not result.get("choices"):
            raise RuntimeError("视觉 API 没有返回 choices")
        choice = result["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            usage = result.get("usage") or {}
            raise RuntimeError(
                "视觉 API 返回空 content；"
                f"finish_reason={choice.get('finish_reason')!r}, "
                f"completion_tokens={usage.get('completion_tokens')!r}"
            )

        return _extract_json(content)
