"""独立检查网页视频播放状态的智能体技能脚本。

支持从标准输入读取 ``agent-skill-script/v1`` JSON，也支持通过命令行参数直接运行；
标准输出始终只有一个 JSON 对象。
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
import time
from typing import Any, Callable
import urllib.error
import urllib.request
from uuid import uuid4

import pyautogui
from PIL import Image, ImageDraw


PROTOCOL = "agent-skill-script/v1"
DEFAULT_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
DEFAULT_SAMPLE_SECONDS = 1.5
STATES = (
    "playing",
    "paused",
    "loading",
    "video_page",
    "search_results",
    "site_home",
    "wrong_video",
    "blocked",
    "obscured",
    "not_visible",
    "unknown",
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


def _resize_for_comparison(image: Image.Image, max_width: int = 1280) -> Image.Image:
    if image.width <= max_width:
        return image.convert("RGB")
    height = max(1, round(image.height * max_width / image.width))
    return image.convert("RGB").resize(
        (max_width, height),
        Image.Resampling.LANCZOS,
    )


def build_comparison(before: Image.Image, after: Image.Image) -> Image.Image:
    """把前后截图并排，供一次视觉请求比较进度条和播放器画面。"""
    left = _resize_for_comparison(before)
    right = _resize_for_comparison(after)
    if right.size != left.size:
        right = right.resize(left.size, Image.Resampling.LANCZOS)
    label_height = 32
    comparison = Image.new(
        "RGB",
        (left.width * 2, left.height + label_height),
        "white",
    )
    comparison.paste(left, (0, label_height))
    comparison.paste(right, (left.width, label_height))
    draw = ImageDraw.Draw(comparison)
    draw.text((12, 10), "BEFORE", fill="black")
    draw.text((left.width + 12, 10), "AFTER", fill="black")
    draw.line((left.width, 0, left.width, comparison.height), fill="red", width=2)
    return comparison


def inspection_prompt(
    video_query: str,
    screen_size: tuple[int, int],
    sample_seconds: float,
) -> str:
    return f"""
你是网页视频播放状态检查器。目标视频：{video_query}。
原始屏幕尺寸：width={screen_size[0]}, height={screen_size[1]}。
输入图片左侧是 BEFORE，右侧是间隔 {sample_seconds:g} 秒后的 AFTER。

只根据可见界面证据判断：
1. 浏览器和可信视频网站是否可见，是否处于首页、搜索结果或视频详情页。
2. 页面标题或播放器附近标题是否与目标视频相符。
3. 是否显示播放器、播放按钮、暂停按钮或加载动画。
4. 前后两张图中，播放器画面是否变化，进度条或时间是否前进。
5. 是否有登录、验证码、付费、年龄确认、地区限制等阻断界面。
6. 是否被其他窗口遮挡，导致无法看清网站或播放器。

不要把广告播放当作目标视频播放。不要根据页面背景动画、鼠标闪烁或全屏其他区域变化
判断视频正在播放。只返回 JSON：
{{
  "browser_visible": true,
  "video_site_visible": true,
  "site_home_visible": false,
  "search_results_visible": false,
  "player_visible": true,
  "title_matches_query": true,
  "play_button_visible": false,
  "pause_button_visible": true,
  "loading_visible": false,
  "timeline_advanced": true,
  "player_frame_changed": true,
  "blocking_dialog_visible": false,
  "window_obscured": false,
  "evidence": ["简短描述实际看见的证据"]
}}
""".strip()


def inspect_video_playback_state(
    video_query: str,
    *,
    sample_seconds: float = DEFAULT_SAMPLE_SECONDS,
    artifact_dir: Path | None = None,
    screenshot: Callable[[], Image.Image] | None = None,
    ask_json: Callable[[Image.Image, str], dict[str, Any]] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    video_query = video_query.strip()
    if not video_query:
        raise ValueError("video_query 不能为空")
    if len(video_query) > 200:
        raise ValueError("video_query 不能超过 200 个字符")
    if not 0 <= sample_seconds <= 5:
        raise ValueError("sample_seconds 必须在 0 到 5 秒之间")

    take_screenshot = screenshot or pyautogui.screenshot
    wait = sleeper or time.sleep
    before = take_screenshot()
    if sample_seconds:
        wait(sample_seconds)
    after = take_screenshot()
    comparison = build_comparison(before, after)

    output_dir = artifact_dir or Path(
        os.environ.get("AGENT_SKILL_ARTIFACT_DIR")
        or Path(tempfile.gettempdir()) / "desktop-agent-skill-artifacts"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    operation_id = uuid4().hex[:10]
    before_path = output_dir / f"video_before_{operation_id}.png"
    after_path = output_dir / f"video_after_{operation_id}.png"
    comparison_path = output_dir / f"video_comparison_{operation_id}.png"
    before.save(before_path)
    after.save(after_path)
    comparison.save(comparison_path)

    raw = (ask_json or ask_vision_json)(
        comparison,
        inspection_prompt(video_query, before.size, sample_seconds),
    )
    indicators = {
        name: _as_bool(raw.get(name))
        for name in (
            "browser_visible",
            "video_site_visible",
            "site_home_visible",
            "search_results_visible",
            "player_visible",
            "title_matches_query",
            "play_button_visible",
            "pause_button_visible",
            "loading_visible",
            "timeline_advanced",
            "player_frame_changed",
            "blocking_dialog_visible",
            "window_obscured",
        )
    }

    if indicators["window_obscured"]:
        state = "obscured"
    elif indicators["blocking_dialog_visible"]:
        state = "blocked"
    elif not indicators["browser_visible"] or not indicators["video_site_visible"]:
        state = "not_visible"
    elif indicators["player_visible"] and not indicators["title_matches_query"]:
        state = "wrong_video"
    elif indicators["player_visible"] and indicators["loading_visible"]:
        state = "loading"
    elif indicators["player_visible"] and (
        indicators["timeline_advanced"]
        or (
            indicators["pause_button_visible"]
            and indicators["player_frame_changed"]
        )
    ):
        state = "playing"
    elif indicators["player_visible"] and indicators["play_button_visible"]:
        state = "paused"
    elif indicators["player_visible"]:
        state = "video_page"
    elif indicators["search_results_visible"]:
        state = "search_results"
    elif indicators["site_home_visible"]:
        state = "site_home"
    else:
        state = "unknown"

    evidence_value = raw.get("evidence") or []
    if isinstance(evidence_value, str):
        evidence = [evidence_value]
    elif isinstance(evidence_value, list):
        evidence = [str(item) for item in evidence_value[:6]]
    else:
        evidence = []
    recommended_actions = {
        "playing": "finish",
        "paused": "click_play_once_then_reinspect",
        "loading": "wait_then_reinspect_once",
        "video_page": "find_play_control_then_reinspect",
        "search_results": "open_best_matching_video",
        "site_home": "search_inside_video_site",
        "wrong_video": "return_to_results_once",
        "blocked": "stop_for_user_takeover",
        "obscured": "restore_browser_visibility",
        "not_visible": "locate_or_open_video_site",
        "unknown": "stop_and_report_ambiguous_state",
    }
    return {
        "ok": True,
        "protocol": PROTOCOL,
        "video_query": video_query,
        "state": state,
        "can_finish": state == "playing",
        "recommended_action": recommended_actions[state],
        "indicators": indicators,
        "evidence": evidence,
        "sample_seconds": sample_seconds,
        "images": {
            "before": str(before_path),
            "after": str(after_path),
            "comparison": str(comparison_path),
        },
    }


def _read_request(argv: list[str] | None) -> tuple[str, float, Path | None]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-query")
    parser.add_argument(
        "--sample-seconds",
        type=float,
        default=DEFAULT_SAMPLE_SECONDS,
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args(argv)
    if args.describe:
        print(
            json.dumps(
                {
                    "protocol": PROTOCOL,
                    "name": "inspect_video_playback_state",
                    "input": {
                        "video_query": "string",
                        "sample_seconds": "0.5..5",
                    },
                    "output_states": list(STATES),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(0)
    if args.video_query:
        return args.video_query, args.sample_seconds, args.artifact_dir

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        parser.error("需要 --video-query 或 stdin JSON")
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
    sample_seconds = float(
        arguments.get("sample_seconds", DEFAULT_SAMPLE_SECONDS)
    )
    return str(arguments.get("video_query") or ""), sample_seconds, artifact_dir


def main(argv: list[str] | None = None) -> int:
    try:
        video_query, sample_seconds, artifact_dir = _read_request(argv)
        result = inspect_video_playback_state(
            video_query,
            sample_seconds=sample_seconds,
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
