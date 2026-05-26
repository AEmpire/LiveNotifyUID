from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from .database import LiveSubscription, SubscriptionRepository
from .types import Platform


@dataclass(slots=True)
class ParsedCommand:
    action: str
    platform: str | None = None
    external_id: str | None = None
    display_name: str | None = None
    subscription_id: int | None = None


def parse_live_command(text: str) -> ParsedCommand:
    parts = text.strip().split()
    if not parts:
        return ParsedCommand(action="help")

    action = parts[0].lower()
    if action == "add" and len(parts) >= 3:
        display_name = " ".join(parts[3:]) or None
        return ParsedCommand(
            action="add",
            platform=parts[1].lower(),
            external_id=parts[2],
            display_name=display_name,
        )

    if action in {"remove", "enable", "disable", "check"}:
        if len(parts) == 2 and parts[1].isdigit():
            return ParsedCommand(action=action, subscription_id=int(parts[1]))
        return ParsedCommand(action="invalid")

    if action in {"list", "status", "help"} and len(parts) == 1:
        return ParsedCommand(action=action)

    return ParsedCommand(action="invalid")


def format_help() -> str:
    return "\n".join(
        [
            "/live add bili <uid> [display_name]",
            "/live add youtube <channel_id> [display_name]",
            "/live remove <id>",
            "/live list",
            "/live enable <id>",
            "/live disable <id>",
            "/live check <id>",
            "/live status",
        ]
    )


def _live_notify_db_path(get_res_path: Callable[[str], Path]) -> Path:
    resource_dir = Path(get_res_path("LiveNotifyUID"))
    resource_dir.mkdir(parents=True, exist_ok=True)
    return resource_dir / "live_notify.db"


def _format_subscription(row: LiveSubscription) -> str:
    name = row.display_name or row.external_id
    enabled = "启用" if row.enabled else "停用"
    failure = f"，失败 {row.failure_count}" if row.failure_count else ""
    return f"#{row.id} {row.platform} {name} {enabled}，状态 {row.last_state}{failure}"


def _format_subscription_detail(row: LiveSubscription) -> str:
    lines = [
        f"直播监听 #{row.id}",
        f"平台：{row.platform}",
        f"目标：{row.display_name or row.external_id}",
        f"启用：{'是' if row.enabled else '否'}",
        f"状态：{row.last_state}",
    ]
    if row.last_live_title:
        lines.append(f"最近直播：{row.last_live_title}")
    if row.last_checked_at:
        lines.append(f"上次检查：{row.last_checked_at}")
    if row.last_error:
        lines.append(f"错误：{row.last_error}")
    return "\n".join(lines)


try:
    from gsuid_core.bot import Bot
    from gsuid_core.data_store import get_res_path
    from gsuid_core.models import Event
    from gsuid_core.sv import SV
except ModuleNotFoundError as exc:
    if exc.name and exc.name.split(".")[0] != "gsuid_core":
        raise
    Bot = None  # type: ignore[assignment]
    Event = None  # type: ignore[assignment]
    SV = None  # type: ignore[assignment]
    get_res_path = None  # type: ignore[assignment]


if SV is not None and get_res_path is not None:
    from .config import get_settings

    live_sv = SV("直播监听管理", pm=3)

    def open_repo() -> Session:
        db_path = _live_notify_db_path(get_res_path)
        engine = create_engine(f"sqlite:///{db_path}")
        SQLModel.metadata.create_all(engine, tables=[LiveSubscription.__table__])
        return Session(engine)

    @live_sv.on_command("live", block=True)
    async def handle_live_command(bot: Bot, ev: Event):
        parsed = parse_live_command(getattr(ev, "text", ""))
        if parsed.action in {"help", "invalid"}:
            return await bot.send(format_help())

        with open_repo() as session:
            repo = SubscriptionRepository(session)

            if parsed.action == "add":
                if parsed.platform not in {Platform.BILI.value, Platform.YOUTUBE.value}:
                    return await bot.send("不支持的平台，请使用 bili 或 youtube。")
                if parsed.external_id is None:
                    return await bot.send(format_help())

                try:
                    subscription = repo.create_subscription(
                        platform=Platform(parsed.platform),
                        external_id=parsed.external_id,
                        display_name=parsed.display_name,
                    )
                except IntegrityError:
                    return await bot.send("该直播监听已存在")
                return await bot.send(
                    "已添加直播监听 "
                    f"#{subscription.id}: {subscription.platform} "
                    f"{subscription.external_id}"
                )

            if parsed.action == "remove" and parsed.subscription_id is not None:
                removed = repo.delete(parsed.subscription_id)
                return await bot.send("已删除直播监听" if removed else "未找到该直播监听")

            if (
                parsed.action in {"enable", "disable"}
                and parsed.subscription_id is not None
            ):
                try:
                    repo.set_enabled(
                        parsed.subscription_id,
                        parsed.action == "enable",
                    )
                except ValueError:
                    return await bot.send("未找到该直播监听")
                return await bot.send(
                    "已启用直播监听" if parsed.action == "enable" else "已停用直播监听"
                )

            if parsed.action == "check" and parsed.subscription_id is not None:
                row = repo.get(parsed.subscription_id)
                if row is None:
                    return await bot.send("未找到该直播监听")
                return await bot.send(_format_subscription_detail(row))

            if parsed.action == "list":
                rows = repo.list_all()
                if not rows:
                    return await bot.send("当前没有直播监听")
                return await bot.send(
                    "\n".join(_format_subscription(row) for row in rows)
                )

            if parsed.action == "status":
                rows = repo.list_all()
                enabled = sum(1 for row in rows if row.enabled)
                failed = sum(1 for row in rows if row.failure_count > 0)
                settings = get_settings()
                youtube = "已配置" if settings.youtube_api_key else "未配置"
                return await bot.send(
                    "直播监听状态："
                    f"总数 {len(rows)}，启用 {enabled}，失败 {failed}，"
                    f"YouTube API Key {youtube}"
                )

        return await bot.send(format_help())
else:
    live_sv = None
