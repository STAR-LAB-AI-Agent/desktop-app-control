"""视觉定位：把桌面截图转换为可点击的屏幕坐标。"""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable

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
        max_retries: int = 2,
        retry_backoff: float = 1.0,
        cancel_check: Callable[[], None] | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.api_url = api_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.cancel_check = cancel_check

    def set_cancel_check(self, cancel_check: Callable[[], None] | None) -> None:
        self.cancel_check = cancel_check

    def locate(self, image: Image.Image, target: str) -> PointPrediction:
        width, height = image.size
        prompt = f"""
你是桌面 GUI 定位器。请在截图中找到：{target}
截图原始尺寸为 width={width}, height={height}；原点在左上角，x 向右，y 向下。
截图可能叠加带编号的等分网格辅助线。可以用网格判断目标区域，但网格仅供参考，
最终仍须返回相对于整张原始截图的绝对像素坐标。
返回目标内部适合鼠标点击的安全点，坐标必须对应原始截图，不要选边缘。
严格匹配目标描述，目标不可见时返回 confidence=0，不得用其他歌曲或相似元素替代。
输出必须是完整有效的 JSON 对象，以右花括号结束；description 保持简短。
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
        return self._request_json(
            [
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
            ]
        )

    def ask_text_json(self, prompt: str) -> dict[str, Any]:
        """向模型发送纯文本请求，并取得一个 JSON 对象。"""
        return self._request_json([{"role": "user", "content": prompt}])

    def _request_json(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY")

        payload = {
            "model": self.model,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "messages": messages,
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
        result = None
        for attempt in range(self.max_retries + 1):
            self._check_cancelled()
            try:
                result = self._open_json_interruptibly(request)
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                # 429 和 5xx 属于短暂服务端问题，可以有限重试；其他
                # 4xx 通常是请求或权限错误，立即返回，避免重复消耗配额。
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise RuntimeError(f"模型 API 请求失败（HTTP {exc.code}）：{body}") from exc
            except (urllib.error.URLError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError) as exc:
                if not _is_retryable_network_error(exc) or attempt >= self.max_retries:
                    reason = getattr(exc, "reason", exc)
                    raise RuntimeError(f"模型 API 连接失败：{reason}") from exc
            self._sleep_before_retry(self.retry_backoff * (attempt + 1))

        if result is None:
            raise RuntimeError("模型 API 未返回结果")

        if not result.get("choices"):
            raise RuntimeError("模型 API 没有返回 choices")
        choice = result["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            usage = result.get("usage") or {}
            raise RuntimeError(
                "模型 API 返回空 content；"
                f"finish_reason={choice.get('finish_reason')!r}, "
                f"completion_tokens={usage.get('completion_tokens')!r}"
            )

        return _extract_json(content)

    def _open_json_interruptibly(
        self,
        request: urllib.request.Request,
    ) -> dict[str, Any]:
        """在后台等待 HTTP 响应，让 Esc 可在网络请求期间立即取消。"""
        outcomes: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def request_worker() -> None:
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    outcomes.put((True, json.load(response)))
            except BaseException as exc:
                outcomes.put((False, exc))

        threading.Thread(
            target=request_worker,
            name="desktop-agent-api-request",
            daemon=True,
        ).start()
        while True:
            self._check_cancelled()
            try:
                ok, value = outcomes.get(timeout=0.05)
            except queue.Empty:
                continue
            if ok:
                return value
            raise value

    def _check_cancelled(self) -> None:
        if self.cancel_check is not None:
            self.cancel_check()

    def _sleep_before_retry(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))


def _is_retryable_network_error(exc: BaseException) -> bool:
    """识别连接被重置、超时等短暂网络错误，不重试参数和权限错误。"""
    values = [exc, getattr(exc, "reason", None)]
    for value in values:
        if isinstance(value, (ConnectionResetError, ConnectionAbortedError, TimeoutError, TimeoutError)):
            return True
        if isinstance(value, OSError) and getattr(value, "winerror", None) in {
            10053, 10054, 10060, 11001,
        }:
            return True
        text = str(value).lower()
        if "connection reset" in text or "timed out" in text or "10054" in text:
            return True
    return False
