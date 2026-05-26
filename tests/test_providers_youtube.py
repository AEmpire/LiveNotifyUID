from datetime import datetime, timezone

import httpx
import pytest
import respx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.providers.youtube import (
    YouTubeProvider,
    extract_youtube_channel_id,
    extract_youtube_handle,
)
from LiveNotifyUID.types import LiveState, Platform


YOUTUBE_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"


def test_extract_youtube_channel_id_from_raw_id_and_channel_url():
    assert extract_youtube_channel_id("UCabc") == "UCabc"
    assert (
        extract_youtube_channel_id("https://www.youtube.com/channel/UCabc/live")
        == "UCabc"
    )


def test_extract_youtube_handle_from_raw_handle_and_handle_url():
    assert extract_youtube_handle("@UTANOch") == "@UTANOch"
    assert (
        extract_youtube_handle("https://www.youtube.com/@UTANOch/posts")
        == "@UTANOch"
    )


@pytest.mark.asyncio
@respx.mock
async def test_youtube_live_response():
    route = respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {"videoId": "video-1"},
                        "snippet": {
                            "title": "YT Live",
                            "channelTitle": "Channel A",
                            "publishedAt": "2026-05-25T09:30:00Z",
                            "thumbnails": {"high": {"url": "https://img.example/high.jpg"}},
                        },
                    }
                ]
            },
        )
    )

    provider = YouTubeProvider(api_key="key")
    status = await provider.check_channel("UCabc", timeout_seconds=10)

    params = route.calls.last.request.url.params
    assert params["part"] == "snippet"
    assert params["channelId"] == "UCabc"
    assert params["eventType"] == "live"
    assert params["type"] == "video"
    assert params["maxResults"] == "1"
    assert params["key"] == "key"
    assert status.platform is Platform.YOUTUBE
    assert status.state is LiveState.LIVE
    assert status.live_id == "video-1"
    assert status.room_url == "https://www.youtube.com/watch?v=video-1"
    assert status.started_at == datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_offline_response():
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json={"items": []}))

    status = await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE


@pytest.mark.asyncio
async def test_youtube_missing_api_key_raises_provider_error():
    with pytest.raises(ProviderError, match="api key"):
        await YouTubeProvider(api_key="").check_channel("UCabc", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_resolves_handle_reference_to_channel_id():
    route = respx.get(YOUTUBE_CHANNELS_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UCresolved",
                        "snippet": {"title": "Utano"},
                    }
                ]
            },
        )
    )

    resolved = await YouTubeProvider(api_key="key").resolve_channel_reference(
        "https://www.youtube.com/@UTANOch/posts",
        timeout_seconds=10,
    )

    params = route.calls.last.request.url.params
    assert params["part"] == "id,snippet"
    assert params["forHandle"] == "@UTANOch"
    assert params["key"] == "key"
    assert resolved.channel_id == "UCresolved"
    assert resolved.display_name == "Utano"


@pytest.mark.asyncio
async def test_youtube_resolve_channel_reference_keeps_channel_id_without_api_key():
    resolved = await YouTubeProvider(api_key="").resolve_channel_reference(
        "https://www.youtube.com/channel/UCabc",
        timeout_seconds=10,
    )

    assert resolved.channel_id == "UCabc"
    assert resolved.display_name is None


@pytest.mark.asyncio
async def test_youtube_resolve_handle_without_api_key_raises_provider_error():
    with pytest.raises(ProviderError, match="api key"):
        await YouTubeProvider(api_key="").resolve_channel_reference(
            "@UTANOch",
            timeout_seconds=10,
        )


@pytest.mark.asyncio
@respx.mock
async def test_youtube_http_error_raises_provider_error():
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(403, json={"error": "denied"}))

    with pytest.raises(ProviderError, match="HTTP"):
        await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_item_missing_video_id_raises_provider_error():
    respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"items": [{"id": {}, "snippet": {}}]})
    )

    with pytest.raises(ProviderError, match="videoId"):
        await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_list_payload_raises_provider_error():
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(ProviderError, match="payload"):
        await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("items", [{"0": {}}, "not-a-list"])
async def test_youtube_non_list_items_raises_provider_error(items):
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json={"items": items}))

    with pytest.raises(ProviderError, match="items"):
        await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_youtube_invalid_published_at_raises_provider_error():
    respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {"videoId": "video-1"},
                        "snippet": {"publishedAt": "not-a-date"},
                    }
                ]
            },
        )
    )

    with pytest.raises(ProviderError, match="publishedAt"):
        await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "item,error_match",
    [
        ({"id": "not-a-dict", "snippet": {}}, "id"),
        ({"id": {"videoId": "video-1"}, "snippet": "not-a-dict"}, "snippet"),
        (
            {
                "id": {"videoId": "video-1"},
                "snippet": {"thumbnails": "not-a-dict"},
            },
            "thumbnails",
        ),
        (
            {
                "id": {"videoId": "video-1"},
                "snippet": {"thumbnails": {"high": "not-a-dict"}},
            },
            "thumbnails",
        ),
    ],
)
async def test_youtube_malformed_live_item_structures_raise_provider_error(item, error_match):
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json={"items": [item]}))

    with pytest.raises(ProviderError, match=error_match):
        await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)
