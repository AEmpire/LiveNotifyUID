from datetime import datetime, timezone

import pytest

from LiveNotifyUID.notifier import (
    UnsupportedRichMessageError,
    build_embed_payload,
    build_plain_text,
    platform_label,
    send_notification,
)
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


def test_build_plain_text_bilibili():
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        title="标题",
        display_name="主播",
        room_url="https://live.bilibili.com/1",
    )

    text = build_plain_text(status)

    assert "【B站直播开播】" in text
    assert "主播：主播" in text
    assert "链接：https://live.bilibili.com/1" in text


def test_build_plain_text_youtube_uses_channel_label():
    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        title="Live",
        display_name="Channel",
    )

    text = build_plain_text(status)

    assert "【YouTube直播开播】" in text
    assert "频道：Channel" in text
    assert "主播：" not in text


def test_build_plain_text_accepts_raw_string_platform():
    status = LiveStatus(
        platform="bili",
        external_id="123",
        state=LiveState.LIVE,
        title="Live",
        display_name="主播",
    )

    text = build_plain_text(status)

    assert "【B站直播开播】" in text
    assert "主播：主播" in text


def test_platform_label_accepts_raw_and_unknown_values():
    assert platform_label("youtube") == "YouTube"
    assert platform_label("bili") == "B站"
    assert platform_label("twitch") == "twitch"


def test_build_embed_payload_contains_discord_fields():
    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        live_id="video-1",
        title="YT Live",
        display_name="Channel",
        room_url="https://www.youtube.com/watch?v=video-1",
        cover_url="https://img.example/cover.jpg",
    )

    payload = build_embed_payload(status)

    assert payload["title"] == "Channel 开播了"
    assert payload["url"] == "https://www.youtube.com/watch?v=video-1"
    assert payload["image"]["url"] == "https://img.example/cover.jpg"


def test_build_embed_payload_without_cover_omits_image():
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        title="Live",
        display_name="主播",
    )

    payload = build_embed_payload(status)

    assert "image" not in payload


def test_build_embed_payload_includes_started_at_field():
    started_at = datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc)
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        title="Live",
        started_at=started_at,
    )

    payload = build_embed_payload(status)

    assert {
        "name": "开播时间",
        "value": "2026-05-25T10:30:00+00:00",
        "inline": False,
    } in payload["fields"]


@pytest.mark.asyncio
async def test_send_notification_falls_back_to_text():
    calls = []

    class Bot:
        async def send_to_channel(self, channel_id, message):
            calls.append((channel_id, message))
            if isinstance(message, dict):
                raise TypeError("rich message unsupported")

    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        title="Live",
    )

    await send_notification(Bot(), channel_id="123", status=status, embed_enabled=True)

    assert len(calls) == 2
    assert calls[-1][0] == "123"
    assert isinstance(calls[-1][1], str)


@pytest.mark.asyncio
async def test_send_notification_falls_back_for_unsupported_rich_error():
    calls = []

    class Bot:
        async def send_to_channel(self, channel_id, message):
            calls.append((channel_id, message))
            if isinstance(message, dict):
                raise UnsupportedRichMessageError("adapter cannot send embeds")

    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        title="Live",
    )

    await send_notification(Bot(), channel_id="123", status=status, embed_enabled=True)

    assert len(calls) == 2
    assert isinstance(calls[-1][1], str)


@pytest.mark.asyncio
async def test_send_notification_propagates_unrelated_send_failure():
    class Bot:
        async def send_to_channel(self, channel_id, message):
            raise TypeError("channel_id must be int")

    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        title="Live",
    )

    with pytest.raises(TypeError, match="channel_id must be int"):
        await send_notification(Bot(), channel_id="123", status=status, embed_enabled=True)


@pytest.mark.asyncio
async def test_send_notification_embed_disabled_sends_text_only():
    calls = []

    class Bot:
        async def send_to_channel(self, channel_id, message):
            calls.append((channel_id, message))

    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        title="Live",
    )

    await send_notification(Bot(), channel_id="456", status=status, embed_enabled=False)

    assert len(calls) == 1
    assert calls[0][0] == "456"
    assert isinstance(calls[0][1], str)
