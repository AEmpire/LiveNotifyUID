from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "/root/gsuid_core/data/LiveNotifyUID/live_notify.db"
DEFAULT_PLUGIN_ROOT = "/root/gsuid_core/gsuid_core/plugins/LiveNotifyUID"

# Platform display metadata. Logo URLs use Google's s2 favicon service which
# returns PNG (Discord embeds reject .ico) and is reliably reachable from
# Discord's CDN validation servers.
PLATFORM_META: dict[str, dict[str, Any]] = {
    "bili": {
        "name": "Bilibili",
        "emoji": "📺",
        "color": 0xFB7299,
        "logo": "https://www.google.com/s2/favicons?domain=bilibili.com&sz=64",
        "channel_url_template": "https://space.bilibili.com/{}",
    },
    "youtube": {
        "name": "YouTube",
        "emoji": "▶️",
        "color": 0xFF0000,
        "logo": "https://www.google.com/s2/favicons?domain=youtube.com&sz=64",
        "channel_url_template": "https://www.youtube.com/channel/{}",
    },
}

# Order is intentional: bili first, youtube second; same order on Discord.
PLATFORM_ORDER: tuple[str, ...] = ("bili", "youtube")

# Status text: only LIVE gets a colored emoji (it's the eye-catcher you want);
# offline/unknown use plain text so Discord's emoji renderer doesn't blow them
# up into giant grey circles next to every offline subscription.
STATE_BADGE: dict[str, str] = {
    "live": "🔴 **LIVE**",
    "offline": "离线",
    "unknown": "未知",
}

# Discord embed field.value hard limit is 1024; we truncate live titles to keep
# the rendered field well under that even with link markdown overhead.
_LIVE_TITLE_MAX = 80

# Discord embed allows up to 25 fields per embed. We keep 24 real fields and
# reserve the last slot for an "and N more" marker to keep the API call valid.
_MAX_FIELDS_PER_EMBED = 25
_MAX_REAL_FIELDS = _MAX_FIELDS_PER_EMBED - 1


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


def fetch_live_subscriptions() -> list[Any]:
    """Read all subscriptions; mirrors run_live_notify_command engine setup."""
    _add_live_notify_to_path()

    from sqlmodel import SQLModel, Session, create_engine

    from LiveNotifyUID.database import LiveSubscription, SubscriptionRepository

    engine = create_engine(f"sqlite:///{_db_path()}")
    SQLModel.metadata.create_all(engine, tables=[LiveSubscription.__table__])

    with Session(engine) as session:
        return SubscriptionRepository(session).list_all()


async def run_live_add_with_details(parsed_text: str) -> Any:
    """Execute /live add and return AddSubscriptionResult.

    Mirrors run_live_notify_command's engine + providers setup so the slash
    handler can render an embed instead of a flat string.
    """
    _add_live_notify_to_path()

    from sqlmodel import SQLModel, Session, create_engine

    from LiveNotifyUID.commands import (
        add_subscription_with_details,
        parse_live_command,
    )
    from LiveNotifyUID.config import settings_from_mapping
    from LiveNotifyUID.database import LiveSubscription
    from LiveNotifyUID.providers import BilibiliProvider, YouTubeProvider
    from LiveNotifyUID.types import Platform

    config = _load_live_notify_config()
    settings = settings_from_mapping(config)
    engine = create_engine(f"sqlite:///{_db_path()}")
    SQLModel.metadata.create_all(engine, tables=[LiveSubscription.__table__])

    with Session(engine) as session:
        return await add_subscription_with_details(
            session,
            parse_live_command(parsed_text),
            settings,
            providers={
                Platform.BILI: BilibiliProvider(),
                Platform.YOUTUBE: YouTubeProvider(api_key=settings.youtube_api_key),
            },
        )


def build_live_list_payload(subscriptions: list[Any]) -> list[dict[str, Any]]:
    """Group subscriptions by platform and produce one embed-shaped dict each.

    Pure / nonebot-agnostic so it can be unit tested without the discord stack.
    Returned dicts map 1:1 onto nonebot.adapters.discord.api.Embed fields, so
    rendering is a thin translation step in the handler.
    """
    grouped: dict[str, list[Any]] = {key: [] for key in PLATFORM_ORDER}
    for sub in subscriptions:
        platform = getattr(sub, "platform", None)
        if platform in grouped:
            grouped[platform].append(sub)

    payloads: list[dict[str, Any]] = []
    for platform_key in PLATFORM_ORDER:
        rows = grouped[platform_key]
        if not rows:
            continue

        # Sort: live first, enabled before disabled, then by id for stability.
        rows = sorted(
            rows,
            key=lambda r: (
                0 if getattr(r, "last_state", "") == "live" else 1,
                0 if getattr(r, "enabled", True) else 1,
                getattr(r, "id", 0) or 0,
            ),
        )

        meta = PLATFORM_META[platform_key]
        fields: list[dict[str, Any]] = []
        live_count = sum(1 for r in rows if getattr(r, "last_state", "") == "live")
        visible_rows = (
            rows[:_MAX_REAL_FIELDS] if len(rows) > _MAX_FIELDS_PER_EMBED else rows
        )
        for sub in visible_rows:
            state = getattr(sub, "last_state", "unknown")
            badge = STATE_BADGE.get(state, STATE_BADGE["unknown"])
            enabled_mark = "" if getattr(sub, "enabled", True) else " · ⏸ 已停用"
            display = (
                getattr(sub, "display_name", None) or getattr(sub, "external_id", "")
            )
            external_id = getattr(sub, "external_id", "")
            channel_url = meta["channel_url_template"].format(external_id)

            # Compact layout: status + channel link share one line. Live items get
            # a second line for the stream title; failures get an optional third.
            header = f"{badge} · [频道主页]({channel_url}){enabled_mark}"
            value_lines = [header]

            live_title = getattr(sub, "last_live_title", None)
            if state == "live" and live_title:
                clipped = live_title[:_LIVE_TITLE_MAX]
                if len(live_title) > _LIVE_TITLE_MAX:
                    clipped += "…"
                room_url = getattr(sub, "room_url", None) or channel_url
                value_lines.append(f"🎬 [{clipped}]({room_url})")

            failure_count = getattr(sub, "failure_count", 0) or 0
            if failure_count:
                last_error = getattr(sub, "last_error", None)
                err_hint = f"：{last_error}" if last_error else ""
                value_lines.append(f"⚠️ 失败 {failure_count} 次{err_hint}"[:200])

            fields.append(
                {
                    "name": f"#{getattr(sub, 'id', '?')} · {display}",
                    "value": "\n".join(value_lines),
                    "inline": False,
                }
            )

        if len(rows) > _MAX_FIELDS_PER_EMBED:
            remaining = len(rows) - _MAX_REAL_FIELDS
            fields.append(
                {
                    "name": f"... 还有 {remaining} 个未显示",
                    "value": "用 /live check <id> 查看具体订阅详情",
                    "inline": False,
                }
            )

        payloads.append(
            {
                "platform_key": platform_key,
                "title": f"{meta['emoji']} {meta['name']} 订阅 ({len(rows)})",
                "description": (
                    f"🔴 直播中 **{live_count}** · 📋 总数 **{len(rows)}**"
                ),
                "color": meta["color"],
                "author_name": meta["name"],
                "logo_url": meta["logo"],
                "fields": fields,
            }
        )

    return payloads


def build_live_add_payload(result: Any) -> dict[str, Any]:
    """Build embed dict for /live add response (pure, nonebot-agnostic).

    Accepts an AddSubscriptionResult-shaped object (duck-typed for easy testing
    with SimpleNamespace). Always returns a dict so the handler can hand it to
    _payload_to_embed unconditionally.
    """
    error_message = getattr(result, "error_message", None)
    subscription = getattr(result, "subscription", None)
    if subscription is None:
        # Validation / resolver / duplicate failure: render a minimal red embed
        # with the error message instead of swallowing it as a tiny string reply.
        return {
            "platform_key": "error",
            "title": "❌ 添加失败",
            "description": error_message or "未知错误",
            "color": 0xED4245,  # Discord 默认 red
            "author_name": "LiveNotifyUID",
            "logo_url": None,
            "fields": [],
        }

    platform_key = str(getattr(subscription, "platform", ""))
    meta = PLATFORM_META.get(
        platform_key,
        {
            "name": platform_key.title() or "Platform",
            "emoji": "🎬",
            "color": 0x5865F2,
            "logo": None,
            "channel_url_template": "{}",
        },
    )
    sub_id = getattr(subscription, "id", "?")
    external_id = getattr(subscription, "external_id", "")
    display_name = (
        getattr(subscription, "display_name", None) or external_id or "未知频道"
    )
    channel_url = meta["channel_url_template"].format(external_id) if external_id else None
    avatar_url = getattr(result, "avatar_url", None)

    status = getattr(result, "status", None)
    initial_state = (
        getattr(getattr(status, "state", None), "value", None)
        or getattr(subscription, "last_state", None)
        or "unknown"
    )
    badge = STATE_BADGE.get(initial_state, STATE_BADGE["unknown"])

    fields: list[dict[str, Any]] = [
        {"name": "频道", "value": f"**{display_name}**", "inline": True},
        {"name": "ID", "value": f"`{external_id}`", "inline": True},
        {"name": "初始状态", "value": badge, "inline": True},
    ]
    if channel_url:
        # Use a short label as the link text. Putting the full URL inside the
        # markdown link text causes Discord to soft-wrap the rendered field
        # mid-link (`[https://...](https://...)` -> the closing `]` and the
        # opening `(` end up on different visual lines), which breaks the
        # markdown parser and shows the raw `[...](...)` chars to the user.
        fields.append(
            {
                "name": "🔗 主页",
                "value": f"[{meta['name']} 频道页]({channel_url})",
                "inline": False,
            }
        )

    initial_check_error = getattr(result, "initial_check_error", None)
    if initial_check_error:
        fields.append(
            {
                "name": "⚠️ 初始检查失败",
                "value": str(initial_check_error)[:1000],
                "inline": False,
            }
        )

    live_title = getattr(status, "title", None) if status else None
    if initial_state == "live" and live_title:
        room_url = getattr(status, "room_url", None) or channel_url or ""
        clipped = live_title[:_LIVE_TITLE_MAX]
        if len(live_title) > _LIVE_TITLE_MAX:
            clipped += "…"
        if room_url:
            fields.append(
                {"name": "🎬 正在播", "value": f"[{clipped}]({room_url})", "inline": False}
            )
        else:
            fields.append({"name": "🎬 正在播", "value": clipped, "inline": False})

    return {
        "platform_key": platform_key,
        "title": f"✅ 已添加 {meta['emoji']} {meta['name']} 监听 #{sub_id}",
        "description": f"{badge} · 平台：{meta['name']}",
        "color": meta["color"],
        "author_name": meta["name"],
        "logo_url": avatar_url or meta.get("logo"),
        "thumbnail_url": avatar_url,
        "fields": fields,
    }


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
    from nonebot.adapters.discord import Message, MessageSegment
    from nonebot.adapters.discord.api import (
        Embed,
        EmbedAuthor,
        EmbedField,
        EmbedFooter,
        EmbedThumbnail,
        IntegerOption,
        OptionChoice,
        StringOption,
        SubCommandOption,
    )
    from nonebot.adapters.discord.commands import on_slash_command
    from nonebot.adapters.discord.event import InteractionCreateEvent
    from nonebot.log import logger as _nb_logger
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

    def _payload_to_embed(payload: dict[str, Any]) -> Embed:
        # Thumbnail is opt-in via payload["thumbnail_url"]. /live list omits it
        # (author.icon_url already shows the platform logo and a per-card
        # thumbnail would duplicate it); /live add includes the channel avatar.
        kwargs: dict[str, Any] = {
            "title": payload["title"],
            "description": payload["description"],
            "color": payload["color"],
            "author": EmbedAuthor(
                name=payload["author_name"], icon_url=payload.get("logo_url")
            ),
            "fields": [
                EmbedField(
                    name=field["name"],
                    value=field["value"],
                    inline=field.get("inline", False),
                )
                for field in payload["fields"]
            ],
            "footer": EmbedFooter(text="LiveNotifyUID · /live check <id> 查看详情"),
        }
        thumbnail_url = payload.get("thumbnail_url")
        if thumbnail_url:
            kwargs["thumbnail"] = EmbedThumbnail(url=thumbnail_url)
        return Embed(**kwargs)

    def _build_live_list_message(subscriptions: list[Any]) -> Message | None:
        embeds = [_payload_to_embed(p) for p in build_live_list_payload(subscriptions)]
        if not embeds:
            return None
        return Message([MessageSegment.embed(e) for e in embeds])

    def _format_user_visible_error(exc: BaseException) -> str:
        # NetWorkError.__str__ hides the underlying httpx/json reason; surface
        # __cause__ chain so users can copy a meaningful message back to us.
        parts: list[str] = [repr(exc)]
        cause = exc.__cause__ or exc.__context__
        seen: set[int] = {id(exc)}
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            parts.append(repr(cause))
            cause = cause.__cause__ or cause.__context__
        joined = " <- ".join(parts)
        # Discord message hard limit is 2000 chars; keep room for the prefix.
        return f"LiveNotifyUID 指令执行失败：{joined}"[:1900]

    def _build_add_message(result: Any) -> Message:
        embed = _payload_to_embed(build_live_add_payload(result))
        return Message([MessageSegment.embed(embed)])

    @live.handle()
    async def handle_live_slash(event: InteractionCreateEvent) -> None:
        # Discord 要求 3 秒内首次响应，否则 token 失效报 "该应用程序未响应"。
        # 业务逻辑可能涉及数据库 + 远程 API（YouTube/Bilibili），可能 >3s，
        # 因此先发 deferred 响应锁定 15 分钟处理窗口，再用 edit_response 回填结果。
        await live.send_deferred_response()
        action = "<unknown>"
        try:
            action, values = extract_slash_command(event.data.options)
            if action == "list":
                subscriptions = fetch_live_subscriptions()
                message = _build_live_list_message(subscriptions)
                if message is None:
                    await live.edit_response("当前没有直播监听")
                    return
                await live.edit_response(message)
                return
            if action == "add":
                result = await run_live_add_with_details(
                    build_command_text(action, values)
                )
                await live.edit_response(_build_add_message(result))
                return
            response = await run_live_notify_command(build_command_text(action, values))
        except Exception as exc:
            _nb_logger.opt(exception=exc).error(
                f"LiveNotifyUID slash handler failed (action={action})"
            )
            response = _format_user_visible_error(exc)
        await live.edit_response(response)
