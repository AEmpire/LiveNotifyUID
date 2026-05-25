from datetime import datetime, timezone

import httpx
import pytest
import respx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.providers.youtube import YouTubeProvider
from LiveNotifyUID.types import LiveState, Platform


YOUTUBE_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"


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
