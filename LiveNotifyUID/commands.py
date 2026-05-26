from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from .config import LiveNotifySettings
from .database import LiveSubscription, SubscriptionRepository
from .providers.base import LiveProvider
from .types import LiveStatus, Platform

_live_notify_engine: Engine | None = None
_live_notify_engine_path: Path | None = None
LIVE_COMMAND_TRIGGER = ""


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


def normalize_live_handler_text(
    text: str | None,
    *,
    raw_text: str | None = None,
) -> str | None:
    commands = ("live", "/live")
    if raw_text is not None:
        stripped_raw = raw_text.strip()
        lowered_raw = stripped_raw.lower()
        for command in commands:
            if lowered_raw.startswith(command):
                if len(stripped_raw) == len(command):
                    break
                if not stripped_raw[len(command)].isspace():
                    return None
                break

    stripped = (text or "").strip()
    lowered = stripped.lower()

    for command in commands:
        if lowered == command:
            return ""
        if lowered.startswith(command):
            if len(stripped) > len(command) and stripped[len(command)].isspace():
                return stripped[len(command) :].strip()
            return None
    return stripped


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


def _get_live_notify_engine(get_res_path: Callable[[str], Path]) -> Engine:
    global _live_notify_engine
    global _live_notify_engine_path

    db_path = _live_notify_db_path(get_res_path)
    if _live_notify_engine is None or _live_notify_engine_path != db_path:
        _live_notify_engine = create_engine(f"sqlite:///{db_path}")
        _live_notify_engine_path = db_path
        SQLModel.metadata.create_all(
            _live_notify_engine,
            tables=[LiveSubscription.__table__],
        )
    return _live_notify_engine


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


def _should_swallow_optional_gscore_import_error(exc: ModuleNotFoundError) -> bool:
    return exc.name == "gsuid_core"


def build_command_response(
    session: Session,
    parsed: ParsedCommand,
    settings: LiveNotifySettings,
) -> str:
    if parsed.action in {"help", "invalid"}:
        return format_help()

    repo = SubscriptionRepository(session)

    if parsed.action == "add":
        if parsed.platform not in {Platform.BILI.value, Platform.YOUTUBE.value}:
            return "不支持的平台，请使用 bili 或 youtube。"
        if parsed.external_id is None:
            return format_help()

        try:
            subscription = repo.create_subscription(
                platform=Platform(parsed.platform),
                external_id=parsed.external_id,
                display_name=parsed.display_name,
            )
        except IntegrityError:
            session.rollback()
            return "该直播监听已存在"
        return (
            "已添加直播监听 "
            f"#{subscription.id}: {subscription.platform} {subscription.external_id}"
        )

    if parsed.action == "remove" and parsed.subscription_id is not None:
        removed = repo.delete(parsed.subscription_id)
        return "已删除直播监听" if removed else "未找到该直播监听"

    if parsed.action in {"enable", "disable"} and parsed.subscription_id is not None:
        try:
            repo.set_enabled(
                parsed.subscription_id,
                parsed.action == "enable",
            )
        except ValueError:
            return "未找到该直播监听"
        return "已启用直播监听" if parsed.action == "enable" else "已停用直播监听"

    if parsed.action == "check" and parsed.subscription_id is not None:
        row = repo.get(parsed.subscription_id)
        if row is None:
            return "未找到该直播监听"
        return _format_subscription_detail(row)

    if parsed.action == "list":
        rows = repo.list_all()
        if not rows:
            return "当前没有直播监听"
        return "\n".join(_format_subscription(row) for row in rows)

    if parsed.action == "status":
        rows = repo.list_all()
        enabled = sum(1 for row in rows if row.enabled)
        failed = sum(1 for row in rows if row.failure_count > 0)
        youtube = "已配置" if settings.youtube_api_key else "未配置"
        return (
            "直播监听状态："
            f"总数 {len(rows)}，启用 {enabled}，失败 {failed}，"
            f"YouTube API Key {youtube}"
        )

    return format_help()


async def execute_live_command(
    session: Session,
    parsed: ParsedCommand,
    settings: LiveNotifySettings,
    *,
    providers: Mapping[Platform, LiveProvider] | None = None,
    now: datetime | None = None,
) -> str:
    if parsed.action in {"help", "invalid"}:
        return format_help()

    repo = SubscriptionRepository(session)
    checked_at = now or datetime.now(timezone.utc)

    if parsed.action == "add":
        if parsed.platform not in {Platform.BILI.value, Platform.YOUTUBE.value}:
            return "不支持的平台，请使用 bili 或 youtube。"
        if parsed.external_id is None:
            return format_help()

        try:
            subscription = repo.create_subscription(
                platform=Platform(parsed.platform),
                external_id=parsed.external_id,
                display_name=parsed.display_name,
            )
        except IntegrityError:
            session.rollback()
            return "该直播监听已存在"

        response = (
            "已添加直播监听 "
            f"#{subscription.id}: {subscription.platform} {subscription.external_id}"
        )
        if providers is None:
            return response

        status, error = await _refresh_subscription_status(
            repo=repo,
            subscription=subscription,
            settings=settings,
            providers=providers,
            checked_at=checked_at,
        )
        if error is not None:
            return f"{response}\n初始检查失败：{error}"
        if status is None:
            return response
        return f"{response}\n初始状态：{status.state.value}"

    if parsed.action == "check" and parsed.subscription_id is not None:
        row = repo.get(parsed.subscription_id)
        if row is None:
            return "未找到该直播监听"

        if providers is not None:
            await _refresh_subscription_status(
                repo=repo,
                subscription=row,
                settings=settings,
                providers=providers,
                checked_at=checked_at,
            )
            row = repo.get(parsed.subscription_id)
            if row is None:
                return "未找到该直播监听"
        return _format_subscription_detail(row)

    return build_command_response(session, parsed, settings)


async def _refresh_subscription_status(
    *,
    repo: SubscriptionRepository,
    subscription: LiveSubscription,
    settings: LiveNotifySettings,
    providers: Mapping[Platform, LiveProvider],
    checked_at: datetime,
) -> tuple[LiveStatus | None, str | None]:
    try:
        platform = Platform(subscription.platform)
    except ValueError:
        error = f"unknown platform: {subscription.platform}"
        repo.mark_failure(subscription.id, error=error, checked_at=checked_at)
        return None, error

    provider = providers.get(platform)
    if provider is None:
        error = f"missing provider for platform: {platform.value}"
        repo.mark_failure(subscription.id, error=error, checked_at=checked_at)
        return None, error

    try:
        status = await provider.check_channel(
            subscription.external_id,
            timeout_seconds=settings.request_timeout_seconds,
        )
    except Exception as exc:
        error = str(exc)
        repo.mark_failure(subscription.id, error=error, checked_at=checked_at)
        return None, error

    repo.mark_checked(
        subscription.id,
        checked_at=checked_at,
        state=status.state,
        live_id=status.live_id,
        live_title=status.title,
        room_url=status.room_url,
    )
    return status, None


try:
    from gsuid_core.bot import Bot
    from gsuid_core.data_store import get_res_path
    from gsuid_core.models import Event
    from gsuid_core.sv import SV
except ModuleNotFoundError as exc:
    if not _should_swallow_optional_gscore_import_error(exc):
        raise
    Bot = None  # type: ignore[assignment]
    Event = None  # type: ignore[assignment]
    SV = None  # type: ignore[assignment]
    get_res_path = None  # type: ignore[assignment]


if SV is not None and get_res_path is not None:
    from .config import get_settings
    from .scheduler import build_default_providers

    live_sv = SV("直播监听管理", pm=6)

    def open_repo() -> Session:
        return Session(_get_live_notify_engine(get_res_path))

    @live_sv.on_command(LIVE_COMMAND_TRIGGER, block=True)
    async def handle_live_command(bot: Bot, ev: Event):
        normalized = normalize_live_handler_text(
            getattr(ev, "text", ""),
            raw_text=getattr(ev, "raw_text", None),
        )
        parsed = (
            ParsedCommand(action="invalid")
            if normalized is None
            else parse_live_command(normalized)
        )
        settings = get_settings()
        with open_repo() as session:
            response = await execute_live_command(
                session,
                parsed,
                settings,
                providers=build_default_providers(settings),
            )
        return await bot.send(response)
else:
    live_sv = None
