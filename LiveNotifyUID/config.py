from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def coerce_int(value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(slots=True)
class LiveNotifySettings:
    youtube_api_key: str = ""
    discord_channel_id: str = ""
    poll_interval_seconds: int = 300
    batch_size: int = 20
    max_concurrency: int = 5
    request_timeout_seconds: int = 10
    failure_backoff_minutes: int = 15
    embed_enabled: bool = True
    notify_on_startup_live: bool = False


def settings_from_mapping(data: dict[str, Any]) -> LiveNotifySettings:
    return LiveNotifySettings(
        youtube_api_key=str(data.get("youtube_api_key", "")),
        discord_channel_id=str(data.get("discord_channel_id", "")),
        poll_interval_seconds=coerce_int(
            data.get("poll_interval_seconds"), default=300, minimum=30
        ),
        batch_size=coerce_int(data.get("batch_size"), default=20, minimum=1),
        max_concurrency=coerce_int(data.get("max_concurrency"), default=5, minimum=1),
        request_timeout_seconds=coerce_int(
            data.get("request_timeout_seconds"), default=10, minimum=1
        ),
        failure_backoff_minutes=coerce_int(
            data.get("failure_backoff_minutes"), default=15, minimum=1
        ),
        embed_enabled=coerce_bool(data.get("embed_enabled"), default=True),
        notify_on_startup_live=coerce_bool(
            data.get("notify_on_startup_live"), default=False
        ),
    )


def get_settings() -> LiveNotifySettings:
    try:
        from gsuid_core.data_store import get_res_path
        from gsuid_core.utils.plugins_config.gs_config import StringConfig
        from gsuid_core.utils.plugins_config.models import (
            GSC,
            GsBoolConfig,
            GsIntConfig,
            GsStrConfig,
        )
    except ImportError:
        return LiveNotifySettings()

    config_default: dict[str, GSC] = {
        "youtube_api_key": GsStrConfig("YouTube API Key", "YouTube Data API key", ""),
        "discord_channel_id": GsStrConfig(
            "Discord Channel ID", "Target Discord channel ID", ""
        ),
        "poll_interval_seconds": GsIntConfig(
            "Poll Interval Seconds", "Scheduler interval", 300
        ),
        "batch_size": GsIntConfig(
            "Batch Size", "Subscriptions checked per scheduler tick", 20
        ),
        "max_concurrency": GsIntConfig(
            "Max Concurrency", "Concurrent provider checks", 5
        ),
        "request_timeout_seconds": GsIntConfig(
            "Request Timeout Seconds", "HTTP timeout", 10
        ),
        "failure_backoff_minutes": GsIntConfig(
            "Failure Backoff Minutes", "Retry delay for failing subscriptions", 15
        ),
        "embed_enabled": GsBoolConfig(
            "Embed Enabled", "Try Discord Embed-style messages first", True
        ),
        "notify_on_startup_live": GsBoolConfig(
            "Notify Startup Live", "Notify if first check finds a live stream", False
        ),
    }
    config_path = get_res_path("LiveNotifyUID") / "config.json"
    plugin_config = StringConfig("LiveNotifyUID", config_path, config_default)
    raw = {key: plugin_config.get_config(key).data for key in config_default}
    return settings_from_mapping(raw)
