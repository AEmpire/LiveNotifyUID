from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


class YouTubeProvider:
    ENDPOINT = "https://www.googleapis.com/youtube/v3/search"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    async def check_channel(self, external_id: str, timeout_seconds: float) -> LiveStatus:
        if not self.api_key:
            raise ProviderError("YouTube api key is required")

        params = {
            "part": "snippet",
            "channelId": external_id,
            "eventType": "live",
            "type": "video",
            "maxResults": "1",
            "key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(self.ENDPOINT, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"YouTube HTTP error: {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube request failed: {exc}") from exc

        items = payload.get("items") or []
        if not items:
            return LiveStatus(
                platform=Platform.YOUTUBE,
                external_id=external_id,
                state=LiveState.OFFLINE,
                raw_metadata=payload,
            )

        item = items[0]
        if not isinstance(item, dict):
            raise ProviderError("YouTube item is invalid")

        video_id = (item.get("id") or {}).get("videoId")
        if not video_id:
            raise ProviderError("YouTube live item missing videoId")

        snippet = item.get("snippet") or {}
        if not isinstance(snippet, dict):
            raise ProviderError("YouTube live item snippet is invalid")

        return LiveStatus(
            platform=Platform.YOUTUBE,
            external_id=external_id,
            state=LiveState.LIVE,
            live_id=str(video_id),
            title=_string_or_none(snippet.get("title")),
            display_name=_string_or_none(snippet.get("channelTitle")),
            room_url=f"https://www.youtube.com/watch?v={video_id}",
            cover_url=_thumbnail_url(snippet.get("thumbnails")),
            started_at=_parse_published_at(snippet.get("publishedAt")),
            raw_metadata=item,
        )


def _parse_published_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _thumbnail_url(thumbnails: Any) -> str | None:
    if not isinstance(thumbnails, dict):
        return None

    for key in ("high", "standard", "medium", "default"):
        thumbnail = thumbnails.get(key)
        if isinstance(thumbnail, dict) and thumbnail.get("url"):
            return str(thumbnail["url"])
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
