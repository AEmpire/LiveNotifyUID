from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


class YouTubeProvider:
    ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
    CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    async def resolve_channel_reference(
        self, reference: str, timeout_seconds: float
    ) -> ResolvedYouTubeChannel:
        channel_id = extract_youtube_channel_id(reference)
        if channel_id is not None:
            return ResolvedYouTubeChannel(channel_id=channel_id, display_name=None)

        handle = extract_youtube_handle(reference)
        if handle is None:
            raise ProviderError("Unsupported YouTube channel reference")
        if not self.api_key:
            raise ProviderError("YouTube api key is required to resolve handles")

        params = {
            "part": "id,snippet",
            "forHandle": handle,
            "key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(self.CHANNELS_ENDPOINT, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"YouTube HTTP error: {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("YouTube response JSON is invalid") from exc

        if not isinstance(payload, dict):
            raise ProviderError("YouTube response payload is invalid")

        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ProviderError("YouTube response items is invalid")
        if not items:
            raise ProviderError(f"YouTube handle not found: {handle}")

        item = items[0]
        if not isinstance(item, dict):
            raise ProviderError("YouTube channel item is invalid")

        channel_id = item.get("id")
        if not channel_id:
            raise ProviderError("YouTube channel item missing id")

        snippet = item.get("snippet") or {}
        if not isinstance(snippet, dict):
            raise ProviderError("YouTube channel item snippet is invalid")

        return ResolvedYouTubeChannel(
            channel_id=str(channel_id),
            display_name=_string_or_none(snippet.get("title")),
        )

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
        except ValueError as exc:
            raise ProviderError("YouTube response JSON is invalid") from exc

        if not isinstance(payload, dict):
            raise ProviderError("YouTube response payload is invalid")

        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ProviderError("YouTube response items is invalid")
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

        item_id = item.get("id") or {}
        if not isinstance(item_id, dict):
            raise ProviderError("YouTube live item id is invalid")

        video_id = item_id.get("videoId")
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
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderError("YouTube live item publishedAt is invalid") from exc


def _thumbnail_url(thumbnails: Any) -> str | None:
    if thumbnails is None:
        return None
    if not isinstance(thumbnails, dict):
        raise ProviderError("YouTube live item thumbnails is invalid")

    for key in ("high", "standard", "medium", "default"):
        thumbnail = thumbnails.get(key)
        if thumbnail is None:
            continue
        if not isinstance(thumbnail, dict):
            raise ProviderError("YouTube live item thumbnails is invalid")
        if thumbnail.get("url"):
            return str(thumbnail["url"])
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True, slots=True)
class ResolvedYouTubeChannel:
    channel_id: str
    display_name: str | None = None


def extract_youtube_channel_id(reference: str) -> str | None:
    value = reference.strip()
    if not value:
        return None
    if value.startswith("UC"):
        return value

    parsed = _parse_youtube_url(value)
    if parsed is None:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "channel" and parts[1].startswith("UC"):
        return parts[1]
    return None


def extract_youtube_handle(reference: str) -> str | None:
    value = reference.strip()
    if not value:
        return None
    if value.startswith("@") and "/" not in value:
        return value

    parsed = _parse_youtube_url(value)
    if parsed is None:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0].startswith("@"):
        return parts[0]
    return None


def _parse_youtube_url(value: str):
    parsed = urlparse(value)
    if not parsed.scheme and "youtube.com" in value:
        parsed = urlparse(f"https://{value}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"youtube.com", "m.youtube.com"}:
        return None
    return parsed
