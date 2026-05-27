#!/usr/bin/env python3
"""Force check + send live notification for one subscription (VPS one-off)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_DB = "/root/gsuid_core/data/LiveNotifyUID/live_notify.db"
DEFAULT_CONFIG = "/root/gsuid_core/data/LiveNotifyUID/config.json"
DEFAULT_PLUGIN_ROOT = "/root/gsuid_core/gsuid_core/plugins/LiveNotifyUID"


class DiscordHttpBotAdapter:
    def __init__(self, token: str) -> None:
        self.token = token

    async def send_to_channel(self, channel_id: str, message: Any) -> None:
        payload: dict[str, Any]
        if isinstance(message, dict):
            payload = {"embeds": [message]}
        else:
            payload = {"content": str(message)}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {self.token}"},
                json=payload,
            )
            response.raise_for_status()


def _load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_token(config: dict[str, Any]) -> str:
    for key in ("discord_bot_token", "bot_token", "DISCORD_BOT_TOKEN"):
        value = config.get(key) or os.environ.get(key)
        if value:
            return str(value)
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        return token
    raise RuntimeError(
        "Discord bot token not found. Set DISCORD_BOT_TOKEN or add discord_bot_token to config.json"
    )


async def main() -> int:
    subscription_id = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    db_path = os.environ.get("LIVE_NOTIFY_DB_PATH", DEFAULT_DB)
    config_path = os.environ.get("LIVE_NOTIFY_CONFIG_PATH", DEFAULT_CONFIG)
    plugin_root = os.environ.get("LIVE_NOTIFY_PLUGIN_ROOT", DEFAULT_PLUGIN_ROOT)

    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)

    from LiveNotifyUID.config import settings_from_mapping
    from LiveNotifyUID.database import LiveSubscription, SubscriptionRepository
    from LiveNotifyUID.notifier import send_notification
    from LiveNotifyUID.providers import BilibiliProvider, YouTubeProvider
    from LiveNotifyUID.scheduler import force_notify_subscription
    from LiveNotifyUID.types import Platform

    config = _load_config(config_path)
    settings = settings_from_mapping(config)
    token = _resolve_token(config)
    if not settings.discord_channel_id:
        raise RuntimeError("discord_channel_id is empty in LiveNotifyUID config")

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine, tables=[LiveSubscription.__table__])
    bot = DiscordHttpBotAdapter(token)
    providers = {
        Platform.BILI: BilibiliProvider(),
        Platform.YOUTUBE: YouTubeProvider(api_key=settings.youtube_api_key),
    }

    with Session(engine) as session:
        repo = SubscriptionRepository(session)
        before = repo.get(subscription_id)
        if before is None:
            print(f"RESULT: not_found subscription #{subscription_id}")
            return 1

        print(
            "BEFORE:",
            f"id={before.id}",
            f"name={before.display_name}",
            f"state={before.last_state}",
            f"live_id={before.last_live_id}",
            f"notified={before.last_notified_live_id}",
            sep=" ",
        )

        message = await force_notify_subscription(
            repo,
            subscription_id,
            settings,
            providers,
            lambda status: send_notification(
                bot,
                channel_id=settings.discord_channel_id,
                status=status,
                embed_enabled=settings.embed_enabled,
            ),
            checked_at=datetime.now(timezone.utc),
        )
        after = repo.get(subscription_id)
        print("ACTION:", message)
        if after is not None:
            print(
                "AFTER:",
                f"id={after.id}",
                f"state={after.last_state}",
                f"live_id={after.last_live_id}",
                f"notified={after.last_notified_live_id}",
                f"notified_at={after.last_notified_at}",
                f"failure_count={after.failure_count}",
                f"last_error={after.last_error}",
                sep=" ",
            )
        print("RESULT:", message)
        return 0 if "已发送" in message else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
