from __future__ import annotations

from typing import Any

import httpx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


class BilibiliProvider:
    ENDPOINT = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": "https://live.bilibili.com/",
    }

    async def check_channel(self, external_id: str, timeout_seconds: float) -> LiveStatus:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(
                    self.ENDPOINT,
                    params={"uids[]": external_id},
                    headers=self.HEADERS,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Bilibili HTTP error: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Bilibili request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("Bilibili response JSON is invalid") from exc

        if not isinstance(payload, dict):
            raise ProviderError("Bilibili response payload is invalid")

        code = payload.get("code")
        if code != 0:
            message = payload.get("message") or payload.get("msg") or f"code {code}"
            raise ProviderError(f"Bilibili API error: {message}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError("Bilibili response data is invalid")
        if external_id not in data:
            raise ProviderError(f"Bilibili UID not found: {external_id}")

        raw = data[external_id]
        if not isinstance(raw, dict):
            raise ProviderError(f"Bilibili UID data is invalid: {external_id}")

        live_status = raw.get("live_status")
        if live_status == 1 and raw.get("room_id"):
            return self._live_status(external_id, raw)

        return LiveStatus(
            platform=Platform.BILI,
            external_id=external_id,
            state=LiveState.OFFLINE,
            display_name=_string_or_none(raw.get("uname")),
            avatar_url=_force_https(_string_or_none(raw.get("face"))),
            raw_metadata=raw,
        )

    def _live_status(self, external_id: str, raw: dict[str, Any]) -> LiveStatus:
        room_id = raw.get("room_id")
        room_id_text = _string_or_none(room_id)
        live_id = _bilibili_live_id(room_id_text, raw)
        room_url = f"https://live.bilibili.com/{room_id_text}" if room_id_text else None

        return LiveStatus(
            platform=Platform.BILI,
            external_id=external_id,
            state=LiveState.LIVE,
            live_id=live_id,
            title=_string_or_none(raw.get("title")),
            display_name=_string_or_none(raw.get("uname")),
            room_url=room_url,
            cover_url=_string_or_none(raw.get("cover_from_user") or raw.get("keyframe")),
            avatar_url=_force_https(_string_or_none(raw.get("face"))),
            raw_metadata=raw,
        )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _force_https(url: str | None) -> str | None:
    # Bilibili 偶尔返回 http://i*.hdslb.com/... 的头像 URL；Discord embed thumbnail
    # / author icon 在某些客户端下会拒绝 http 资源，统一升级到 https（hdslb 支持）。
    if url is None:
        return None
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _bilibili_live_id(room_id: str | None, raw: dict[str, Any]) -> str | None:
    if room_id is None:
        return None

    for key in ("live_time", "live_id"):
        value = _string_or_none(raw.get(key))
        if value:
            return f"{room_id}:{value}"

    return room_id
