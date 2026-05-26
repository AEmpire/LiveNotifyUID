from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "/root/gsuid_core/data/LiveNotifyUID/live_notify.db"
DEFAULT_PLUGIN_ROOT = "/root/gsuid_core/gsuid_core/plugins/LiveNotifyUID"


def extract_slash_command(options: Any) -> tuple[str, dict[str, Any]]:
    option_list = _as_list(options)
    if not option_list:
        return "help", {}

    subcommand = option_list[0]
    action = str(_get_value(subcommand, "name"))
    values: dict[str, Any] = {}
    for option in _as_list(_get_value(subcommand, "options", [])):
        name = str(_get_value(option, "name"))
        values[name] = _get_value(option, "value")
    return action, values


def build_command_text(action: str, values: dict[str, Any]) -> str:
    if action in {"status", "list", "help"}:
        return action

    if action == "add":
        platform = _required(values, "platform")
        target = _required(values, "target")
        name = str(values.get("name") or "").strip()
        if name:
            return f"add {platform} {target} {name}"
        return f"add {platform} {target}"

    if action in {"remove", "check", "enable", "disable"}:
        return f"{action} {_required(values, 'id')}"

    return "help"


async def run_live_notify_command(command_text: str) -> str:
    _add_live_notify_to_path()

    from sqlmodel import SQLModel, Session, create_engine

    from LiveNotifyUID.commands import execute_live_command, parse_live_command
    from LiveNotifyUID.config import settings_from_mapping
    from LiveNotifyUID.database import LiveSubscription
    from LiveNotifyUID.providers import BilibiliProvider, YouTubeProvider
    from LiveNotifyUID.types import Platform

    config = _load_live_notify_config()
    settings = settings_from_mapping(config)
    engine = create_engine(f"sqlite:///{_db_path()}")
    SQLModel.metadata.create_all(engine, tables=[LiveSubscription.__table__])

    with Session(engine) as session:
        return await execute_live_command(
            session,
            parse_live_command(command_text),
            settings,
            providers={
                Platform.BILI: BilibiliProvider(),
                Platform.YOUTUBE: YouTubeProvider(api_key=settings.youtube_api_key),
            },
        )


def _add_live_notify_to_path() -> None:
    plugin_root = os.getenv("LIVE_NOTIFY_PLUGIN_ROOT", DEFAULT_PLUGIN_ROOT)
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)


def _db_path() -> str:
    return os.getenv("LIVE_NOTIFY_DB_PATH", DEFAULT_DB_PATH)


def _load_live_notify_config() -> dict[str, Any]:
    config_path = Path(
        os.getenv(
            "LIVE_NOTIFY_CONFIG_PATH",
            "/root/gsuid_core/data/LiveNotifyUID/config.json",
        )
    )
    if not config_path.exists():
        return {}

    import json

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    config: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and "data" in value:
            config[key] = value["data"]
        else:
            config[key] = value
    return config


def _required(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing required option: {key}")
    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None or _is_unset(value):
        return []
    return list(value)


def _get_value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, default)
    return default if _is_unset(value) else value


def _is_unset(value: Any) -> bool:
    return value.__class__.__name__ == "UnsetType"


try:
    from nonebot.adapters.discord.api import (
        IntegerOption,
        OptionChoice,
        StringOption,
        SubCommandOption,
    )
    from nonebot.adapters.discord.commands import on_slash_command
    from nonebot.adapters.discord.event import InteractionCreateEvent
except ModuleNotFoundError:
    live = None
else:
    live = on_slash_command(
        name="live",
        description="Manage LiveNotifyUID live subscriptions",
        options=[
            SubCommandOption(name="status", description="Show LiveNotifyUID status"),
            SubCommandOption(name="list", description="List live subscriptions"),
            SubCommandOption(
                name="add",
                description="Add a Bilibili or YouTube live subscription",
                options=[
                    StringOption(
                        name="platform",
                        description="Live platform",
                        required=True,
                        choices=[
                            OptionChoice(name="bili", value="bili"),
                            OptionChoice(name="youtube", value="youtube"),
                        ],
                    ),
                    StringOption(
                        name="target",
                        description="Bilibili UID, YouTube channel ID, handle, or URL",
                        required=True,
                    ),
                    StringOption(
                        name="name",
                        description="Optional display name",
                        required=False,
                    ),
                ],
            ),
            SubCommandOption(
                name="remove",
                description="Remove a subscription",
                options=[
                    IntegerOption(name="id", description="Subscription ID", required=True)
                ],
            ),
            SubCommandOption(
                name="check",
                description="Check a subscription now",
                options=[
                    IntegerOption(name="id", description="Subscription ID", required=True)
                ],
            ),
            SubCommandOption(
                name="enable",
                description="Enable a subscription",
                options=[
                    IntegerOption(name="id", description="Subscription ID", required=True)
                ],
            ),
            SubCommandOption(
                name="disable",
                description="Disable a subscription",
                options=[
                    IntegerOption(name="id", description="Subscription ID", required=True)
                ],
            ),
        ],
    )

    @live.handle()
    async def handle_live_slash(event: InteractionCreateEvent) -> None:
        try:
            action, values = extract_slash_command(event.data.options)
            response = await run_live_notify_command(build_command_text(action, values))
        except Exception as exc:
            response = f"LiveNotifyUID 指令执行失败：{exc}"
        await event.send(response)
