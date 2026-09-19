"""网页视频查找与播放技能的变量提取。"""

from __future__ import annotations

import re
from typing import Any


PLATFORMS = (
    {
        "name": "哔哩哔哩",
        "aliases": ("哔哩哔哩", "bilibili", "B站"),
        "url": "https://www.bilibili.com",
    },
    {
        "name": "YouTube",
        "aliases": ("youtube", "油管"),
        "url": "https://www.youtube.com",
    },
    {
        "name": "腾讯视频",
        "aliases": ("腾讯视频",),
        "url": "https://v.qq.com",
    },
    {
        "name": "爱奇艺",
        "aliases": ("爱奇艺", "iqiyi"),
        "url": "https://www.iqiyi.com",
    },
    {
        "name": "优酷",
        "aliases": ("优酷", "youku"),
        "url": "https://www.youku.com",
    },
)


class WebVideoPlaybackSkill:
    name = "web-video-playback"

    def prepare(self, task: str) -> dict[str, Any]:
        platform = self._find_platform(task)
        return {
            "video_query": self._extract_video_query(task, platform),
            "requested_platform": platform["name"] if platform else "",
            "platform_url": platform["url"] if platform else "",
            "browser_app_name": "Edge",
        }

    @staticmethod
    def build_review(variables: dict[str, Any]) -> dict[str, Any]:
        video_query = str(variables.get("video_query", "")).strip()
        if not video_query:
            raise ValueError("没有从任务中解析出要播放的视频名称。")
        platform = str(variables.get("requested_platform", "")).strip()
        destination = platform or "搜索结果中的可靠视频网站"
        return {
            "risk": "medium",
            "summary": f"在{destination}中查找并播放“{video_query}”。",
            "warnings": [
                "搜索词会发送给浏览器搜索引擎或视频网站。",
                "视频开始播放后可能产生声音。",
                "遇到登录、验证码、付费或地区限制时会停止并等待人工处理。",
            ],
        }

    @staticmethod
    def _find_platform(task: str) -> dict[str, Any] | None:
        normalized = task.casefold()
        for platform in PLATFORMS:
            if any(alias.casefold() in normalized for alias in platform["aliases"]):
                return platform
        return None

    @staticmethod
    def _extract_video_query(
        task: str,
        platform: dict[str, Any] | None,
    ) -> str:
        value = task.strip()
        if platform:
            for alias in sorted(platform["aliases"], key=len, reverse=True):
                value = re.sub(
                    rf"(?:在|打开|用)?\s*{re.escape(alias)}\s*(?:上|里|中)?",
                    " ",
                    value,
                    flags=re.IGNORECASE,
                )
        value = re.sub(r"^(?:请|麻烦)?(?:帮我)?\s*", "", value)
        value = re.sub(
            r"(?:搜索并播放|搜索播放|找到并播放|找一下并播放|查找并播放|"
            r"搜索|查找|找一下|找到|播放一下|播放|观看一下|观看|看一下)",
            " ",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\b(?:please|help|me|use|search|find|and|play|watch|for|to|the|a|an)\b",
            " ",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"(?:这个|一下|给我)", " ", value)
        value = re.sub(
            r"(?:视频|影片|video|movie)\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", value).strip(" ，,。.")


def create_skill() -> WebVideoPlaybackSkill:
    return WebVideoPlaybackSkill()
