from __future__ import annotations

from typing import Any

from .types import Platform, LiveStatus


class UnsupportedRichMessageError(Exception):
    """Raised by bot adapters that cannot send rich notification payloads."""


def _platform_value(platform: Platform | str) -> str:
    if isinstance(platform, Platform):
        return platform.value
    return str(platform)


def platform_label(platform: Platform | str) -> str:
    platform_value = _platform_value(platform)
    if platform_value == Platform.BILI.value:
        return "B站"
    if platform_value == Platform.YOUTUBE.value:
        return "YouTube"
    return platform_value


def _uses_bili_name_label(platform: Platform | str) -> bool:
    return _platform_value(platform) == Platform.BILI.value


def _display_name(status: LiveStatus) -> str:
    return status.display_name or status.external_id


def _title(status: LiveStatus) -> str:
    return status.title or "正在直播"


def build_plain_text(status: LiveStatus) -> str:
    label = platform_label(status.platform)
    name_label = "主播" if _uses_bili_name_label(status.platform) else "频道"

    lines = [
        f"【{label}直播开播】",
        f"{name_label}：{_display_name(status)}",
        f"标题：{_title(status)}",
    ]
    if status.room_url:
        lines.append(f"链接：{status.room_url}")

    return "\n".join(lines)


def build_embed_payload(status: LiveStatus) -> dict[str, Any]:
    name = _display_name(status)
    payload: dict[str, Any] = {
        "title": f"{name} 开播了",
        "description": _title(status),
        "fields": [
            {"name": "平台", "value": platform_label(status.platform), "inline": True},
            {"name": "名称", "value": name, "inline": True},
            {"name": "ID", "value": status.external_id, "inline": True},
        ],
        "footer": {"text": "LiveNotifyUID"},
    }

    if status.room_url:
        payload["url"] = status.room_url
    if status.cover_url:
        payload["image"] = {"url": status.cover_url}
    if status.started_at:
        payload["fields"].append(
            {
                "name": "开播时间",
                "value": status.started_at.isoformat(),
                "inline": False,
            }
        )

    return payload


async def send_notification(
    bot: Any,
    channel_id: str,
    status: LiveStatus,
    embed_enabled: bool,
) -> Any:
    if embed_enabled:
        try:
            return await bot.send_to_channel(channel_id, build_embed_payload(status))
        except UnsupportedRichMessageError:
            pass
        except TypeError as exc:
            if exc.args != ("rich message unsupported",):
                raise

    return await bot.send_to_channel(channel_id, build_plain_text(status))
