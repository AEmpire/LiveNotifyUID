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
YOUTUBE_LIVE_HTML_URL = "https://www.youtube.com/channel/UCabc/live"


# Minimal HTML fixtures that mirror the markers we depend on in production.
# Keep them small but realistic so a YouTube format change shows up in tests.
#
# We empirically observed:
# - `hlsManifestUrl` ONLY appears when a channel is actively broadcasting.
# - `/channel/<id>/live` for offline channels still serves a watch-style page
#   populated from the most recent broadcast (with `"isLive":true` markers
#   from that ended video), which is why we can't rely on `isLive`.
def _live_html(video_id: str = "video-1", title: str = "YT Live") -> str:
    return f"""<!DOCTYPE html><html><head>
<link rel="canonical" href="https://www.youtube.com/watch?v={video_id}">
</head><body>
<script>var ytInitialPlayerResponse = {{"videoDetails":{{"videoId":"{video_id}","title":"{title}","isLive":true}},"streamingData":{{"hlsManifestUrl":"https://manifest.googlevideo.com/api/manifest/hls/..."}}}};</script>
</body></html>"""


def _offline_html_with_stale_live_metadata() -> str:
    # Mirrors the real-world failure mode: channel is offline but YouTube
    # still renders the most-recent (already-ended) broadcast's metadata,
    # complete with `"isLive":true` but WITHOUT hlsManifestUrl.
    return """<!DOCTYPE html><html><head>
<link rel="canonical" href="https://www.youtube.com/watch?v=ended-vid-1">
</head><body>
<script>var ytInitialPlayerResponse = {"playabilityStatus":{"status":"LIVE_STREAM_OFFLINE"},"videoDetails":{"videoId":"ended-vid-1","title":"Past Stream","isLive":true}};</script>
</body></html>"""


def _offline_html_bare_channel() -> str:
    return """<!DOCTYPE html><html><head>
<meta property="og:title" content="Channel A">
</head><body>
<script>var ytInitialPlayerResponse = {"videoDetails": {}};</script>
</body></html>"""


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
async def test_search_api_live_response():
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
    status = await provider._check_via_search_api("UCabc", timeout_seconds=10)

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
async def test_search_api_offline_response():
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json={"items": []}))

    status = await YouTubeProvider(api_key="key")._check_via_search_api(
        "UCabc", timeout_seconds=10
    )

    assert status.state is LiveState.OFFLINE


@pytest.mark.asyncio
async def test_search_api_missing_api_key_raises_provider_error():
    with pytest.raises(ProviderError, match="api key"):
        await YouTubeProvider(api_key="")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )


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
                        "snippet": {
                            "title": "Utano",
                            "thumbnails": {
                                "high": {"url": "https://yt3.example/avatar-high.jpg"}
                            },
                        },
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
    assert resolved.avatar_url == "https://yt3.example/avatar-high.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_youtube_resolves_uc_channel_id_via_channels_api_when_key_present():
    # When an api_key is configured we still hit the channels endpoint for UC
    # IDs so the caller can show display_name + avatar in /live add.
    route = respx.get(YOUTUBE_CHANNELS_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UCabc",
                        "snippet": {
                            "title": "Channel A",
                            "thumbnails": {
                                "high": {"url": "https://yt3.example/uc-avatar.jpg"}
                            },
                        },
                    }
                ]
            },
        )
    )

    resolved = await YouTubeProvider(api_key="key").resolve_channel_reference(
        "UCabc", timeout_seconds=10
    )

    params = route.calls.last.request.url.params
    assert params["id"] == "UCabc"
    assert params["part"] == "id,snippet"
    assert "forHandle" not in params
    assert resolved.channel_id == "UCabc"
    assert resolved.display_name == "Channel A"
    assert resolved.avatar_url == "https://yt3.example/uc-avatar.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_youtube_resolve_uc_with_key_raises_when_channel_not_found():
    respx.get(YOUTUBE_CHANNELS_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    with pytest.raises(ProviderError, match="UCghost"):
        await YouTubeProvider(api_key="key").resolve_channel_reference(
            "UCghost", timeout_seconds=10
        )


@pytest.mark.asyncio
async def test_youtube_resolve_channel_reference_keeps_channel_id_without_api_key():
    resolved = await YouTubeProvider(api_key="").resolve_channel_reference(
        "https://www.youtube.com/channel/UCabc",
        timeout_seconds=10,
    )

    assert resolved.channel_id == "UCabc"
    assert resolved.display_name is None
    assert resolved.avatar_url is None


@pytest.mark.asyncio
async def test_youtube_resolve_handle_without_api_key_raises_provider_error():
    with pytest.raises(ProviderError, match="api key"):
        await YouTubeProvider(api_key="").resolve_channel_reference(
            "@UTANOch",
            timeout_seconds=10,
        )


@pytest.mark.asyncio
@respx.mock
async def test_search_api_http_error_raises_provider_error_with_status_code():
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(403, json={"error": "denied"}))

    with pytest.raises(ProviderError, match="HTTP") as exc_info:
        await YouTubeProvider(api_key="key")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_search_api_item_missing_video_id_raises_provider_error():
    respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"items": [{"id": {}, "snippet": {}}]})
    )

    with pytest.raises(ProviderError, match="videoId"):
        await YouTubeProvider(api_key="key")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )


@pytest.mark.asyncio
@respx.mock
async def test_search_api_list_payload_raises_provider_error():
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(ProviderError, match="payload"):
        await YouTubeProvider(api_key="key")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("items", [{"0": {}}, "not-a-list"])
async def test_search_api_non_list_items_raises_provider_error(items):
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json={"items": items}))

    with pytest.raises(ProviderError, match="items"):
        await YouTubeProvider(api_key="key")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )


@pytest.mark.asyncio
@respx.mock
async def test_search_api_invalid_published_at_raises_provider_error():
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
        await YouTubeProvider(api_key="key")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )


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
async def test_search_api_malformed_live_item_structures_raise_provider_error(item, error_match):
    respx.get(YOUTUBE_ENDPOINT).mock(return_value=httpx.Response(200, json={"items": [item]}))

    with pytest.raises(ProviderError, match=error_match):
        await YouTubeProvider(api_key="key")._check_via_search_api(
            "UCabc", timeout_seconds=10
        )


# ---------------------------------------------------------------------------
# HTML scraping path tests (the new primary check_channel route, 0 quota)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_via_html_returns_live_with_canonical_video_id():
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(200, text=_live_html(video_id="vidLIVE", title="Tonight"))
    )

    provider = YouTubeProvider(api_key="")  # no api_key: HTML is the only path
    status = await provider.check_channel("UCabc", timeout_seconds=10)

    assert status.platform is Platform.YOUTUBE
    assert status.state is LiveState.LIVE
    assert status.live_id == "vidLIVE"
    assert status.title == "Tonight"
    assert status.room_url == "https://www.youtube.com/watch?v=vidLIVE"


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_via_html_returns_offline_on_bare_channel_page():
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(200, text=_offline_html_bare_channel())
    )

    status = await YouTubeProvider(api_key="").check_channel("UCabc", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE
    assert status.live_id is None


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_via_html_returns_offline_when_only_stale_live_metadata():
    # Critical regression guard: offline channels still render watch-style
    # pages with `"isLive":true` left over from the most recent broadcast.
    # Without hlsManifestUrl filtering, this would produce false-positive
    # live notifications on every poll.
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(
            200, text=_offline_html_with_stale_live_metadata()
        )
    )

    status = await YouTubeProvider(api_key="").check_channel("UCabc", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE
    assert status.live_id is None


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_via_html_decodes_unicode_title_from_video_details():
    # videoDetails.title is a JSON string literal -> may contain \uXXXX
    # escapes. Real-world example: Japanese VTuber titles use them heavily.
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(
            200,
            text=_live_html(video_id="abc", title="\\u30d5\\u30ea\\u30fc"),
        )
    )

    status = await YouTubeProvider(api_key="").check_channel("UCabc", timeout_seconds=10)

    assert status.title == "フリー"


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_html_429_propagates_status_code():
    # Even YouTube's free HTML endpoint can rate-limit on abusive clients.
    # Make sure the status_code is carried so the scheduler can alert.
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(return_value=httpx.Response(429, text=""))

    with pytest.raises(ProviderError) as exc_info:
        await YouTubeProvider(api_key="").check_channel("UCabc", timeout_seconds=10)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_falls_back_to_search_api_when_html_fails():
    # If the HTML format regresses (e.g. YouTube reorganises the page so the
    # live video id disappears from videoDetails AND canonical), the provider
    # should quietly degrade to search.list when an api_key is configured.
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(
            200,
            text='<html>hlsManifestUrl present but no videoId anywhere</html>',
        )
    )
    respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {"videoId": "fallback-vid"},
                        "snippet": {"title": "Fallback", "channelTitle": "Chan"},
                    }
                ]
            },
        )
    )

    status = await YouTubeProvider(api_key="key").check_channel(
        "UCabc", timeout_seconds=10
    )

    assert status.state is LiveState.LIVE
    assert status.live_id == "fallback-vid"


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_fallback_prefers_status_code_error_for_alerting():
    # HTML returns a non-actionable parsing error (no status_code); search.list
    # returns 403 quota exhausted (has status_code=403). The fallback path
    # should surface the API error so the scheduler can alert on quota.
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(
            200, text='<html>hlsManifestUrl present but no videoId anywhere</html>'
        )
    )
    respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(403, json={"error": "quota"})
    )

    with pytest.raises(ProviderError) as exc_info:
        await YouTubeProvider(api_key="key").check_channel(
            "UCabc", timeout_seconds=10
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_html_failure_raises_directly_when_no_api_key():
    # No api_key -> no fallback path -> raise the HTML error directly.
    respx.get(YOUTUBE_LIVE_HTML_URL).mock(return_value=httpx.Response(429, text=""))

    with pytest.raises(ProviderError) as exc_info:
        await YouTubeProvider(api_key="").check_channel("UCabc", timeout_seconds=10)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_html_http_429_does_not_fallback_even_with_api_key():
    # Critical: HTML rate-limit must NOT trigger a fallback to search.list,
    # because (a) the same network condition probably 429s search.list too,
    # (b) search.list costs 100 units even when it fails and would burn what
    # remains of an already-exhausted quota, and (c) we want the operator's
    # alert to correctly identify the HTML scraping path as the failure
    # source, not the API.
    html_route = respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(429, text="")
    )
    api_route = respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    with pytest.raises(ProviderError) as exc_info:
        await YouTubeProvider(api_key="key").check_channel(
            "UCabc", timeout_seconds=10
        )

    assert exc_info.value.status_code == 429
    assert "HTML" in str(exc_info.value)  # error message points at HTML path
    assert html_route.called
    assert not api_route.called  # ⬅ no quota spent


@pytest.mark.asyncio
@respx.mock
async def test_check_channel_html_http_500_does_not_fallback_either():
    # Same principle for upstream YouTube outages: don't waste an API call.
    html_route = respx.get(YOUTUBE_LIVE_HTML_URL).mock(
        return_value=httpx.Response(503, text="")
    )
    api_route = respx.get(YOUTUBE_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    with pytest.raises(ProviderError) as exc_info:
        await YouTubeProvider(api_key="key").check_channel(
            "UCabc", timeout_seconds=10
        )

    assert exc_info.value.status_code == 503
    assert html_route.called
    assert not api_route.called
