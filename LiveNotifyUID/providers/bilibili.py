from __future__ import annotations

from typing import Any

import httpx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


class BilibiliProvider:
    ENDPOINT = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"

    async def check_channel(self, external_id: str, timeout_seconds: float) -> LiveStatus:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(self.ENDPOINT, params={"uids[]": external_id})
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Bilibili HTTP error: {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Bilibili request failed: {exc}") from exc

        code = payload.get("code")
        if code != 0:
            message = payload.get("message") or payload.get("msg") or f"code {code}"
            raise ProviderError(f"Bilibili API error: {message}")

        data = payload.get("data") or {}
        if not isinstance(data, dict) or external_id not in data:
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
            raw_metadata=raw,
        )

    def _live_status(self, external_id: str, raw: dict[str, Any]) -> LiveStatus:
        room_id = raw.get("room_id")
        live_id = str(room_id) if room_id is not None else None
        room_url = f"https://live.bilibili.com/{live_id}" if live_id else None

        return LiveStatus(
            platform=Platform.BILI,
            external_id=external_id,
            state=LiveState.LIVE,
            live_id=live_id,
            title=_string_or_none(raw.get("title")),
            display_name=_string_or_none(raw.get("uname")),
            room_url=room_url,
            cover_url=_string_or_none(raw.get("cover_from_user") or raw.get("keyframe")),
            raw_metadata=raw,
        )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
