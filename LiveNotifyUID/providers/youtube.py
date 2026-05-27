from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from LiveNotifyUID.providers.base import ProviderError
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


# YouTube Data API search.list costs 100 units/call -> 3 channels at 5-min
# polling burns 86,400 units/day, well over the 10,000 free quota. The HTML
# `/channel/<id>/live` endpoint is free and returns a usable signal IF you
# read the right marker:
#
#   * `/channel/<id>/live` does NOT cleanly 404 when the channel is offline.
#     It still serves a watch-style page populated with metadata from the
#     channel's most recent live video (or upcoming premier), which means
#     superficial markers like `"isLive":true` show up even for ended streams
#     and would produce false-positive notifications.
#   * `hlsManifestUrl` (the HLS playback manifest) is only embedded while a
#     stream is *actively broadcasting* — completed VODs/replays/upcoming
#     premiers don't need a live manifest. We empirically verified this
#     against an offline VTuber channel (no marker), an offline channel with
#     no upcoming events (no marker), and a 24/7 lofi live stream (marker
#     present). Use this as the canonical live-now check.
#
# Video id and title come from the embedded `videoDetails` block in
# `ytInitialPlayerResponse`; canonical <link> is kept as a fallback.
# search.list remains as a degraded path when HTML fails AND an api_key is
# configured, so a future HTML regression won't blind every subscription.
_LIVE_HTML_URL_TEMPLATE = "https://www.youtube.com/channel/{}/live"
_HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_HLS_MANIFEST_MARKER = "hlsManifestUrl"
_VIDEO_ID_FROM_DETAILS_RE = re.compile(
    r'"videoDetails":\{[^{}]*?"videoId":"([\w-]{11})"'
)
_VIDEO_ID_FROM_CANONICAL_RE = re.compile(
    r'<link[^>]*?rel="canonical"[^>]*?href="https://www\.youtube\.com/watch\?v=([\w-]+)"'
)
_TITLE_FROM_DETAILS_RE = re.compile(
    r'"videoDetails":\{[^{}]*?"title":"((?:[^"\\]|\\.)*)"'
)
_OG_TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]+)"')


class YouTubeProvider:
    ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
    CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
    LIVE_HTML_URL_TEMPLATE = _LIVE_HTML_URL_TEMPLATE

    def __init__(self, api_key: str | None) -> None:
        self.api_key = api_key

    async def resolve_channel_reference(
        self, reference: str, timeout_seconds: float
    ) -> ResolvedYouTubeChannel:
        channel_id = extract_youtube_channel_id(reference)
        handle = extract_youtube_handle(reference) if channel_id is None else None

        if channel_id is None and handle is None:
            raise ProviderError("Unsupported YouTube channel reference")

        # No api_key 时维持旧契约：UC short-circuit（拿不到 display_name/头像但
        # 至少 add 能成功），handle 抛错。
        if not self.api_key:
            if channel_id is not None:
                return ResolvedYouTubeChannel(
                    channel_id=channel_id, display_name=None, avatar_url=None
                )
            raise ProviderError("YouTube api key is required to resolve handles")

        params: dict[str, str] = {"part": "id,snippet", "key": self.api_key}
        if channel_id is not None:
            params["id"] = channel_id
            not_found_msg = f"YouTube channel not found: {channel_id}"
        else:
            params["forHandle"] = handle  # type: ignore[assignment]
            not_found_msg = f"YouTube handle not found: {handle}"

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
            raise ProviderError(not_found_msg)

        item = items[0]
        if not isinstance(item, dict):
            raise ProviderError("YouTube channel item is invalid")

        resolved_channel_id = item.get("id") or channel_id
        if not resolved_channel_id:
            raise ProviderError("YouTube channel item missing id")

        snippet = item.get("snippet") or {}
        if not isinstance(snippet, dict):
            raise ProviderError("YouTube channel item snippet is invalid")

        return ResolvedYouTubeChannel(
            channel_id=str(resolved_channel_id),
            display_name=_string_or_none(snippet.get("title")),
            avatar_url=_thumbnail_url(snippet.get("thumbnails")),
        )

    async def check_channel(self, external_id: str, timeout_seconds: float) -> LiveStatus:
        try:
            return await self._check_via_html(external_id, timeout_seconds)
        except ProviderError as html_exc:
            if not self.api_key:
                raise
            # Important: only fall back to search.list when HTML returned a
            # parseable response that we couldn't decode (likely a YouTube
            # layout regression). DO NOT fall back on HTTP-level failures
            # (4xx/5xx or network drops carry a status_code). Reasons:
            #   1. search.list costs 100 units/call. If the operator's quota
            #      is already exhausted, every fallback wastes nothing and
            #      surfaces a misleading "YouTube HTTP error: 429" that
            #      blames the API instead of the original transient HTML
            #      failure.
            #   2. The same network condition that 429'd HTML is very likely
            #      to 429 search.list too. Fallback adds latency without
            #      improving the outcome.
            #   3. We want the operator to see "YouTube HTML HTTP error: 429"
            #      so the alert correctly points at the scraping path.
            if getattr(html_exc, "status_code", None) is not None:
                raise
            try:
                return await self._check_via_search_api(external_id, timeout_seconds)
            except ProviderError as api_exc:
                if getattr(api_exc, "status_code", None) is not None:
                    raise api_exc
                raise html_exc

    async def _check_via_html(
        self, external_id: str, timeout_seconds: float
    ) -> LiveStatus:
        url = self.LIVE_HTML_URL_TEMPLATE.format(external_id)
        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds, follow_redirects=True
            ) as client:
                response = await client.get(url, headers=_HTML_HEADERS)
                response.raise_for_status()
                html_text = response.text
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"YouTube HTML HTTP error: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube HTML request failed: {exc}") from exc

        if _HLS_MANIFEST_MARKER not in html_text:
            # Most reliable offline signal: no HLS manifest = no active live.
            # This filters out offline channels whose /live URL still renders
            # the most-recent-broadcast metadata, and upcoming-premier pages
            # that don't have a live HLS stream yet.
            return LiveStatus(
                platform=Platform.YOUTUBE,
                external_id=external_id,
                state=LiveState.OFFLINE,
            )

        video_id = _extract_live_video_id(html_text)
        if video_id is None:
            raise ProviderError(
                "YouTube HTML indicates live but live video id is missing"
            )

        return LiveStatus(
            platform=Platform.YOUTUBE,
            external_id=external_id,
            state=LiveState.LIVE,
            live_id=str(video_id),
            title=_extract_live_title(html_text),
            room_url=f"https://www.youtube.com/watch?v={video_id}",
        )

    async def _check_via_search_api(
        self, external_id: str, timeout_seconds: float
    ) -> LiveStatus:
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
            raise ProviderError(
                f"YouTube HTTP error: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
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


def _extract_live_video_id(html_text: str) -> str | None:
    # Prefer videoDetails (always present in a watch-style page) and fall
    # back to the canonical <link> if the player payload format ever shifts.
    match = _VIDEO_ID_FROM_DETAILS_RE.search(html_text)
    if match:
        return match.group(1)
    match = _VIDEO_ID_FROM_CANONICAL_RE.search(html_text)
    if match:
        return match.group(1)
    return None


def _extract_live_title(html_text: str) -> str | None:
    match = _TITLE_FROM_DETAILS_RE.search(html_text)
    if match:
        # videoDetails.title is a JSON-encoded string literal; decode escape
        # sequences (\uXXXX, \", \\, etc.) via json.loads.
        return _decode_json_string_literal(match.group(1))
    match = _OG_TITLE_RE.search(html_text)
    if match:
        return _html.unescape(match.group(1))
    return None


def _decode_json_string_literal(value: str) -> str:
    import json

    try:
        return json.loads(f'"{value}"')
    except (json.JSONDecodeError, ValueError):
        return value


@dataclass(frozen=True, slots=True)
class ResolvedYouTubeChannel:
    channel_id: str
    display_name: str | None = None
    avatar_url: str | None = None


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
