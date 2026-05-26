from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _should_swallow_optional_gscore_import_error(exc: ModuleNotFoundError) -> bool:
    return exc.name == "gsuid_core"


try:
    from gsuid_core.data_store import get_res_path
    from gsuid_core.utils.plugins_config.gs_config import StringConfig
    from gsuid_core.utils.plugins_config.models import (
        GSC,
        GsBoolConfig,
        GsIntConfig,
        GsStrConfig,
    )
except ModuleNotFoundError as exc:
    if _should_swallow_optional_gscore_import_error(exc):
        get_res_path = None  # type: ignore[assignment]
        StringConfig = None  # type: ignore[assignment]
        GSC = Any  # type: ignore[misc, assignment]
        GsBoolConfig = None  # type: ignore[assignment]
        GsIntConfig = None  # type: ignore[assignment]
        GsStrConfig = None  # type: ignore[assignment]
    else:
        raise


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


def coerce_str(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


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


if GsStrConfig is not None and GsIntConfig is not None and GsBoolConfig is not None:
    CONFIG_DEFAULT: dict[str, GSC] = {
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
else:
    CONFIG_DEFAULT = {
        "youtube_api_key": "",
        "discord_channel_id": "",
        "poll_interval_seconds": 300,
        "batch_size": 20,
        "max_concurrency": 5,
        "request_timeout_seconds": 10,
        "failure_backoff_minutes": 15,
        "embed_enabled": True,
        "notify_on_startup_live": False,
    }


def _build_plugin_config() -> Any | None:
    if StringConfig is None or get_res_path is None:
        return None
    config_path = get_res_path("LiveNotifyUID") / "config.json"
    return StringConfig("LiveNotifyUID", config_path, CONFIG_DEFAULT)


live_notify_config = _build_plugin_config()


def settings_from_mapping(data: dict[str, Any]) -> LiveNotifySettings:
    return LiveNotifySettings(
        youtube_api_key=coerce_str(data.get("youtube_api_key")),
        discord_channel_id=coerce_str(data.get("discord_channel_id")),
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
    if live_notify_config is None:
        return LiveNotifySettings()
    raw = {key: live_notify_config.get_config(key).data for key in CONFIG_DEFAULT}
    return settings_from_mapping(raw)
