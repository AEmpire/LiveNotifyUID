import httpx
import pytest
import respx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.providers.bilibili import BilibiliProvider
from LiveNotifyUID.types import LiveState, Platform


BILIBILI_ENDPOINT = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_live_response():
    route = respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 1,
                        "room_id": 678,
                        "title": "Bili Live",
                        "uname": "主播A",
                        "cover_from_user": "https://cover.example/a.jpg",
                    }
                },
            },
        )
    )

    provider = BilibiliProvider()
    status = await provider.check_channel("12345", timeout_seconds=10)

    assert route.calls.last.request.url.params.get_list("uids[]") == ["12345"]
    assert status.platform is Platform.BILI
    assert status.state is LiveState.LIVE
    assert status.live_id == "678"
    assert status.room_url == "https://live.bilibili.com/678"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_live_response_uses_live_time_as_session_id():
    route = respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 1,
                        "room_id": 678,
                        "live_time": "2026-05-25 01:00:00",
                        "title": "Bili Live",
                        "uname": "主播A",
                    }
                },
            },
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.live_id == "678:2026-05-25 01:00:00"
    assert route.calls.last.request.headers["referer"] == "https://live.bilibili.com/"
    assert "Mozilla/" in route.calls.last.request.headers["user-agent"]


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_live_response_uses_keyframe_as_cover_fallback():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 1,
                        "room_id": 678,
                        "title": "Bili Live",
                        "uname": "主播A",
                        "keyframe": "https://cover.example/keyframe.jpg",
                    }
                },
            },
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.state is LiveState.LIVE
    assert status.cover_url == "https://cover.example/keyframe.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_offline_response():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "data": {"12345": {"live_status": 0, "uname": "主播A"}}},
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE
    assert status.display_name == "主播A"
    assert status.raw_metadata["live_status"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_live_status_without_room_id_returns_offline():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 1,
                        "title": "Bili Live",
                        "uname": "主播A",
                    }
                },
            },
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE
    assert status.live_id is None
    assert status.raw_metadata["live_status"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_api_code_error_raises_provider_error():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"code": -400, "message": "bad uid"})
    )

    with pytest.raises(ProviderError, match="bad uid"):
        await BilibiliProvider().check_channel("12345", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_uid_not_found_raises_provider_error():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {}})
    )

    with pytest.raises(ProviderError, match="12345"):
        await BilibiliProvider().check_channel("12345", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_list_payload_raises_provider_error():
    respx.get(BILIBILI_ENDPOINT).mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(ProviderError, match="payload"):
        await BilibiliProvider().check_channel("12345", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0},
        {"code": 0, "data": []},
        {"code": 0, "data": {"12345": []}},
    ],
)
async def test_bilibili_malformed_data_raises_provider_error(payload):
    respx.get(BILIBILI_ENDPOINT).mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(ProviderError):
        await BilibiliProvider().check_channel("12345", timeout_seconds=10)


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_offline_response_extracts_avatar_url_from_face():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 0,
                        "uname": "主播A",
                        "face": "https://i0.hdslb.com/bfs/face/abc.jpg",
                    }
                },
            },
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.avatar_url == "https://i0.hdslb.com/bfs/face/abc.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_live_response_extracts_avatar_url_from_face():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 1,
                        "room_id": 678,
                        "title": "Bili Live",
                        "uname": "主播A",
                        "face": "https://i0.hdslb.com/bfs/face/xyz.jpg",
                    }
                },
            },
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.state is LiveState.LIVE
    assert status.avatar_url == "https://i0.hdslb.com/bfs/face/xyz.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_avatar_url_is_upgraded_to_https():
    # Discord embed thumbnails may reject http; bilibili sometimes returns
    # face URLs over http even though hdslb supports https.
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 0,
                        "uname": "主播A",
                        "face": "http://i0.hdslb.com/bfs/face/abc.jpg",
                    }
                },
            },
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.avatar_url == "https://i0.hdslb.com/bfs/face/abc.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_avatar_url_is_none_when_face_missing():
    respx.get(BILIBILI_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "data": {"12345": {"live_status": 0, "uname": "主播A"}}},
        )
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.avatar_url is None
