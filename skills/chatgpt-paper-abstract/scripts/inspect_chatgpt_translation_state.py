"""Portable Agent Skill script for inspecting ChatGPT translation state.

Input: an ``agent-skill-script/v1`` JSON object on stdin, or
``--expected-segment`` for direct shell use. Output is one JSON object on stdout.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable
import urllib.error
import urllib.request
from uuid import uuid4

import pyautogui
from PIL import Image


PROTOCOL = "agent-skill-script/v1"
DEFAULT_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
SEGMENTS = (
    "Abstract",
    "Section 1",
    "Section 2",
    "Section 3",
    "Section 4",
    "Section 5",
)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _image_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("视觉 API 没有返回 JSON")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("视觉 API 返回值必须是 JSON 对象")
    return value


def ask_vision_json(image: Image.Image, prompt: str) -> dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")
    payload = {
        "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL),
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
        os.environ.get("DEEPSEEK_API_URL", DEFAULT_API_URL),
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
        raise RuntimeError(f"视觉 API 请求失败（HTTP {exc.code}）：{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"视觉 API 连接失败：{exc.reason}") from exc

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("视觉 API 没有返回 choices")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("视觉 API 返回空 content")
    return _extract_json(content)


def inspection_prompt(expected_segment: str, image_size: tuple[int, int]) -> str:
    return f"""
你是 ChatGPT 桌面版论文翻译状态检查器。当前应检查：{expected_segment}。
截图尺寸：width={image_size[0]}, height={image_size[1]}。

只识别以下可见 UI 证据，不评价译文长度，也不要猜测论文内容是否完整：
1. ChatGPT 主界面和对话区域是否可见。
2. 是否有微信等其他窗口遮住 ChatGPT 的对话或输入区域。
3. 输入框右下角是否显示“停止生成”的方形按钮；它出现即表示 generating。
4. 输入框右下角是否恢复为发送箭头。
5. 最新一条助手回答下方是否出现复制、点赞、重新生成等回答操作按钮。

不要使用画面变化率、正文长短、滚动位置或等待时长作为证据。
如果关键区域被其他窗口遮挡，conversation_obscured 必须为 true。
只返回 JSON：
{{
  "chatgpt_visible": true,
  "conversation_obscured": false,
  "stop_button_visible": false,
  "send_button_visible": true,
  "latest_response_actions_visible": true,
  "evidence": ["简短描述实际看见的 UI 证据"]
}}
""".strip()


def inspect_translation_state(
    expected_segment: str,
    *,
    artifact_dir: Path | None = None,
    screenshot: Callable[[], Image.Image] | None = None,
    ask_json: Callable[[Image.Image, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if expected_segment not in SEGMENTS:
        raise ValueError(f"不支持的论文分段：{expected_segment}")

    image = (screenshot or pyautogui.screenshot)()
    output_dir = artifact_dir or Path(
        os.environ.get("AGENT_SKILL_ARTIFACT_DIR")
        or Path(tempfile.gettempdir()) / "desktop-agent-skill-artifacts"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_segment = re.sub(r"[^A-Za-z0-9]+", "_", expected_segment).strip("_").lower()
    image_path = output_dir / f"chatgpt_{safe_segment}_{uuid4().hex[:10]}.png"
    image.save(image_path)

    raw = (ask_json or ask_vision_json)(
        image,
        inspection_prompt(expected_segment, image.size),
    )
    indicators = {
        "chatgpt_visible": _as_bool(raw.get("chatgpt_visible")),
        "conversation_obscured": _as_bool(raw.get("conversation_obscured")),
        "stop_button_visible": _as_bool(raw.get("stop_button_visible")),
        "send_button_visible": _as_bool(raw.get("send_button_visible")),
        "latest_response_actions_visible": _as_bool(
            raw.get("latest_response_actions_visible")
        ),
    }
    if not indicators["chatgpt_visible"]:
        state = "not_visible"
    elif indicators["conversation_obscured"]:
        state = "obscured"
    elif indicators["stop_button_visible"]:
        state = "generating"
    elif (
        indicators["send_button_visible"]
        and indicators["latest_response_actions_visible"]
    ):
        state = "complete"
    else:
        state = "unknown"

    evidence_value = raw.get("evidence") or []
    if isinstance(evidence_value, str):
        evidence = [evidence_value]
    elif isinstance(evidence_value, list):
        evidence = [str(item) for item in evidence_value[:5]]
    else:
        evidence = []
    recommended_actions = {
        "generating": "wait_then_inspect_once_more",
        "complete": "advance_to_next_segment",
        "obscured": "wait_for_chatgpt_to_be_visible",
        "not_visible": "restore_chatgpt_visibility",
        "unknown": "stop_and_report_ambiguous_state",
    }
    return {
        "ok": True,
        "protocol": PROTOCOL,
        "expected_segment": expected_segment,
        "state": state,
        "can_advance": state == "complete",
        "recommended_action": recommended_actions[state],
        "indicators": indicators,
        "evidence": evidence,
        "inspection_image": str(image_path),
        "screen_changed_used": False,
    }


def _read_request(argv: list[str] | None) -> tuple[str, Path | None]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-segment", choices=SEGMENTS)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args(argv)
    if args.describe:
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "name": "inspect_chatgpt_translation_state",
                    "input": {"expected_segment": list(SEGMENTS)},
                    "output_states": [
                        "generating",
                        "complete",
                        "obscured",
                        "not_visible",
                        "unknown",
                    ],
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(0)
    if args.expected_segment:
        return args.expected_segment, args.artifact_dir

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        parser.error("需要 --expected-segment 或 stdin JSON")
    request = json.loads(raw_input)
    if not isinstance(request, dict):
        raise ValueError("stdin 必须是 JSON 对象")
    if request.get("protocol") not in (None, PROTOCOL):
        raise ValueError(f"不支持的协议：{request.get('protocol')!r}")
    arguments = request.get("arguments", request)
    context = request.get("context") or {}
    if not isinstance(arguments, dict) or not isinstance(context, dict):
        raise ValueError("arguments 和 context 必须是 JSON 对象")
    artifact_value = context.get("artifact_dir")
    artifact_dir = Path(str(artifact_value)) if artifact_value else args.artifact_dir
    return str(arguments.get("expected_segment") or ""), artifact_dir


def main(argv: list[str] | None = None) -> int:
    try:
        expected_segment, artifact_dir = _read_request(argv)
        result = inspect_translation_state(
            expected_segment,
            artifact_dir=artifact_dir,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "protocol": PROTOCOL,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
