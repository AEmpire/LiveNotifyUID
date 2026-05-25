from __future__ import annotations

from typing import Any

from .types import Platform, LiveStatus


def platform_label(platform: Platform) -> str:
    if platform is Platform.BILI:
        return "B站"
    if platform is Platform.YOUTUBE:
        return "YouTube"
    return str(platform.value)


def _display_name(status: LiveStatus) -> str:
    return status.display_name or status.external_id


def _title(status: LiveStatus) -> str:
    return status.title or "正在直播"


def build_plain_text(status: LiveStatus) -> str:
    label = platform_label(status.platform)
    name_label = "主播" if status.platform is Platform.BILI else "频道"

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
        except (AttributeError, TypeError, ValueError):
            pass

    return await bot.send_to_channel(channel_id, build_plain_text(status))
