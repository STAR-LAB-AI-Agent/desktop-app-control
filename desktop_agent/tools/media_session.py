"""读取和控制 Windows 媒体会话。"""
import asyncio
import re


def normalize(value):
    return re.sub(r"[\W_]+", "", value).casefold()


def matching_session(task, sessions):
    target = normalize(task)
    matches = [s for s in sessions if normalize(s.get("title", ""))
               and normalize(s["title"]) in target]
    # 有歧义就不以任意一个播放器的状态作为成功依据。
    return matches[0] if len(matches) == 1 else None


def _state_name(status, status_enum):
    if status == status_enum.PLAYING:
        return "playing"
    if status == status_enum.PAUSED:
        return "paused"
    return "unknown"


async def _session_infos():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    manager = await Manager.request_async()
    result = []
    for session in manager.get_sessions():
        media = await session.try_get_media_properties_async()
        status = session.get_playback_info().playback_status
        result.append((session, {"app": session.source_app_user_model_id,
                                 "title": media.title, "artist": media.artist,
                                 "state": _state_name(status, Status)}))
    return result


async def _read():
    return [info for _, info in await _session_infos()]


async def _resume(task):
    sessions = await _session_infos()
    infos = [info for _, info in sessions]
    target = normalize(task)
    indexes = [
        index for index, info in enumerate(infos)
        if normalize(info.get("title", "")) and normalize(info["title"]) in target
    ]
    if len(indexes) != 1:
        return {
            "ok": False,
            "state": "unknown",
            "command_sent": False,
            "sessions": infos,
            "error": "未找到唯一匹配的 Windows 媒体会话",
        }

    index = indexes[0]
    before = infos[index]
    if before["state"] == "playing":
        return {
            "ok": True,
            "state": "playing",
            "command_sent": False,
            "matched_session": before,
            "sessions": infos,
        }

    command_sent = bool(await sessions[index][0].try_play_async())
    await asyncio.sleep(0.8)
    after_infos = [info for _, info in await _session_infos()]
    after = matching_session(task, after_infos)
    state = after["state"] if after else "unknown"
    return {
        "ok": state == "playing",
        "state": state,
        "command_sent": command_sent,
        "matched_session": after,
        "sessions": after_infos,
    }


def read_media_sessions():
    try:
        return {"available": True, "sessions": asyncio.run(asyncio.wait_for(_read(), timeout=5))}
    except Exception as exc:
        return {"available": False, "sessions": [], "error": f"{type(exc).__name__}: {exc}"}


def resume_media_session(task):
    try:
        return asyncio.run(asyncio.wait_for(_resume(task), timeout=5))
    except Exception as exc:
        return {
            "ok": False,
            "state": "unknown",
            "command_sent": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
