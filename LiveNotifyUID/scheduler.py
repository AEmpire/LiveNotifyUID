from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, create_engine

from .config import LiveNotifySettings, get_settings
from .database import LiveSubscription, SubscriptionRepository
from .notifier import UnsupportedRichMessageError, platform_label, send_notification
from .providers import BilibiliProvider, LiveProvider, YouTubeProvider
from .providers.base import ProviderError
from .state_machine import TransitionDecision, decide_transition
from .types import LiveState, LiveStatus, Platform

logger = logging.getLogger(__name__)

SendFunc = Callable[[LiveStatus], Awaitable[None]]
AlertFunc = Callable[[LiveSubscription, BaseException], Awaitable[None]]
NOTIFICATION_FAILED_PREFIX = "notification failed:"
# Status codes that we want to alert the user about (rate limiting / quota
# exhaustion / auth problems). Generic 5xx and transient network errors are
# considered noise and only surface in last_error.
ALERT_STATUS_CODES = frozenset({401, 403, 429})


def build_default_providers(
    settings: LiveNotifySettings,
) -> dict[Platform, LiveProvider]:
    return {
        Platform.BILI: BilibiliProvider(),
        Platform.YOUTUBE: YouTubeProvider(api_key=settings.youtube_api_key),
    }


async def run_poll_once(
    repo: SubscriptionRepository,
    settings: LiveNotifySettings,
    providers: Mapping[Platform, LiveProvider],
    send: SendFunc,
    *,
    now: datetime | None = None,
    alert_send: AlertFunc | None = None,
) -> None:
    current_time = now or datetime.now(timezone.utc)
    due = repo.list_due(
        limit=settings.batch_size,
        now=current_time,
        failure_backoff_minutes=settings.failure_backoff_minutes,
    )
    semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def check_one(subscription: LiveSubscription) -> None:
        async with semaphore:
            await _check_subscription(
                repo=repo,
                settings=settings,
                providers=providers,
                send=send,
                subscription=subscription,
                checked_at=current_time,
                alert_send=alert_send,
            )

    await asyncio.gather(*(check_one(subscription) for subscription in due))


async def _check_subscription(
    *,
    repo: SubscriptionRepository,
    settings: LiveNotifySettings,
    providers: Mapping[Platform, LiveProvider],
    send: SendFunc,
    subscription: LiveSubscription,
    checked_at: datetime,
    alert_send: AlertFunc | None = None,
) -> None:
    try:
        platform = Platform(subscription.platform)
    except ValueError:
        repo.mark_failure(
            subscription.id,
            error=f"unknown platform: {subscription.platform}",
            checked_at=checked_at,
        )
        return

    provider = providers.get(platform)
    if provider is None:
        repo.mark_failure(
            subscription.id,
            error=f"missing provider for platform: {platform.value}",
            checked_at=checked_at,
        )
        return

    try:
        status = await provider.check_channel(
            subscription.external_id,
            timeout_seconds=settings.request_timeout_seconds,
        )
    except Exception as exc:
        logger.exception("live provider check failed")
        # Snapshot the failure_count BEFORE mark_failure increments it. We
        # alert only when transitioning from healthy (0) -> failing on an
        # actionable status code (429/403/401), so the channel doesn't
        # spam alerts every 5 minutes while the quota is exhausted.
        was_healthy = subscription.failure_count == 0
        repo.mark_failure(subscription.id, error=str(exc), checked_at=checked_at)
        if was_healthy and alert_send is not None and _should_alert(exc):
            try:
                await alert_send(subscription, exc)
            except Exception:
                logger.exception("live alert send failed")
        return

    previous_state = _live_state(subscription.last_state)
    decision = decide_transition(
        previous_state=previous_state,
        last_notified_live_id=subscription.last_notified_live_id,
        current=status,
        notify_on_startup_live=settings.notify_on_startup_live,
    )
    should_notify = decision is TransitionDecision.NOTIFY or _should_retry_unnotified_live(
        previous_state=previous_state,
        last_notified_live_id=subscription.last_notified_live_id,
        last_live_id=subscription.last_live_id,
        last_error=subscription.last_error,
        current=status,
    )
    repo.mark_checked(
        subscription.id,
        checked_at=checked_at,
        state=status.state,
        live_id=status.live_id,
        live_title=status.title,
        display_name=status.display_name,
        room_url=status.room_url,
    )

    if not should_notify or status.live_id is None:
        return

    try:
        await send(status)
    except Exception as exc:
        logger.exception("live notification failed")
        repo.mark_failure(
            subscription.id,
            error=f"{NOTIFICATION_FAILED_PREFIX} {exc}",
            checked_at=checked_at,
        )
        return

    repo.mark_notified(
        subscription.id,
        live_id=status.live_id,
        notified_at=checked_at,
    )


def _live_state(value: str) -> LiveState:
    try:
        return LiveState(value)
    except ValueError:
        return LiveState.UNKNOWN


def _should_alert(exc: BaseException) -> bool:
    """Return True if the failure deserves a user-visible alert.

    Only acts on ProviderError instances that carry an explicit
    status_code in ALERT_STATUS_CODES (401/403/429) — i.e. auth, quota,
    or rate-limit problems the operator needs to act on. Transient
    network errors / parsing errors stay silent in last_error.
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code in ALERT_STATUS_CODES:
        return True
    return False


def build_alert_text(subscription: LiveSubscription, exc: BaseException) -> str:
    """Format a human-readable alert for rate-limit / quota failures."""
    try:
        platform_name = platform_label(Platform(subscription.platform))
    except ValueError:
        platform_name = subscription.platform
    display = subscription.display_name or subscription.external_id
    status_code = getattr(exc, "status_code", None)
    reason_hint = ""
    if status_code == 429:
        reason_hint = "（请求过于频繁，建议降低轮询频率或更换 API key）"
    elif status_code == 403:
        reason_hint = "（API key 配额耗尽或权限被拒，请检查 quota / key 状态）"
    elif status_code == 401:
        reason_hint = "（API key 无效或已过期）"

    lines = [
        "⚠️【LiveNotifyUID 警报】",
        f"平台：{platform_name}",
        f"订阅：#{subscription.id} {display}",
        f"错误：HTTP {status_code} - {exc}" if status_code else f"错误：{exc}",
    ]
    if reason_hint:
        lines.append(f"说明：{reason_hint}")
    lines.append("注：同一订阅在恢复前只会报警一次。")
    return "\n".join(lines)


def _should_retry_unnotified_live(
    *,
    previous_state: LiveState,
    last_notified_live_id: str | None,
    last_live_id: str | None,
    last_error: str | None,
    current: LiveStatus,
) -> bool:
    return (
        previous_state is LiveState.LIVE
        and current.state is LiveState.LIVE
        and current.live_id is not None
        and current.live_id == last_live_id
        and current.live_id != last_notified_live_id
        and last_error is not None
        and last_error.startswith(NOTIFICATION_FAILED_PREFIX)
    )


async def force_notify_subscription(
    repo: SubscriptionRepository,
    subscription_id: int,
    settings: LiveNotifySettings,
    providers: Mapping[Platform, LiveProvider],
    send: SendFunc,
    *,
    checked_at: datetime | None = None,
) -> str:
    """Check one subscription now and send a live notification if applicable.

    Unlike the scheduled poll, this bypasses the state machine and notifies
    whenever the channel is currently live and this live_id has not been
    notified yet — including unknown -> live cases that normal polling skips.
    """
    current_time = checked_at or datetime.now(timezone.utc)
    subscription = repo.get(subscription_id)
    if subscription is None:
        return "未找到该直播监听"
    if not subscription.enabled:
        return f"#{subscription_id} 已停用，未发送通知"

    try:
        platform = Platform(subscription.platform)
    except ValueError:
        error = f"unknown platform: {subscription.platform}"
        repo.mark_failure(subscription.id, error=error, checked_at=current_time)
        return f"检查失败：{error}"

    provider = providers.get(platform)
    if provider is None:
        error = f"missing provider for platform: {platform.value}"
        repo.mark_failure(subscription.id, error=error, checked_at=current_time)
        return f"检查失败：{error}"

    try:
        status = await provider.check_channel(
            subscription.external_id,
            timeout_seconds=settings.request_timeout_seconds,
        )
    except Exception as exc:
        logger.exception("live provider check failed during force notify")
        repo.mark_failure(subscription.id, error=str(exc), checked_at=current_time)
        return f"检查失败：{exc}"

    repo.mark_checked(
        subscription.id,
        checked_at=current_time,
        state=status.state,
        live_id=status.live_id,
        live_title=status.title,
        display_name=status.display_name,
        room_url=status.room_url,
    )

    if status.state is not LiveState.LIVE:
        return f"#{subscription_id} 当前未开播（{status.state.value}），未发送通知"
    if status.live_id is None:
        return f"#{subscription_id} 正在直播但缺少 live_id，未发送通知"
    if status.live_id == subscription.last_notified_live_id:
        return f"#{subscription_id} 本场直播已通知过（live_id={status.live_id}）"

    display = subscription.display_name or subscription.external_id
    try:
        await send(status)
    except Exception as exc:
        logger.exception("live notification failed during force notify")
        repo.mark_failure(
            subscription.id,
            error=f"{NOTIFICATION_FAILED_PREFIX} {exc}",
            checked_at=current_time,
        )
        return f"#{subscription_id} {display} 检查成功但通知发送失败：{exc}"

    repo.mark_notified(
        subscription.id,
        live_id=status.live_id,
        notified_at=current_time,
    )
    title = status.title or "正在直播"
    return f"已发送 #{subscription_id} {display} 的开播通知：{title}"


class GsCoreBotAdapter:
    def __init__(self, gss: Any) -> None:
        self.gss = gss

    async def send_to_channel(self, channel_id: str, message: Any) -> None:
        if not self.gss.active_bot:
            raise RuntimeError("no active bot connection")
        if isinstance(message, dict):
            raise UnsupportedRichMessageError("rich message unsupported")

        bot = next(iter(self.gss.active_bot.values()))
        try:
            await bot.target_send(
                message,
                "group",
                str(channel_id),
                "discord",
                "",
                "",
                False,
                "",
                str(channel_id),
            )
        except Exception:
            raise


def _live_notify_db_path(get_res_path: Callable[[str], Path]) -> Path:
    resource_dir = Path(get_res_path("LiveNotifyUID"))
    resource_dir.mkdir(parents=True, exist_ok=True)
    return resource_dir / "live_notify.db"


async def poll_from_gscore() -> None:
    try:
        from gsuid_core.data_store import get_res_path
        from gsuid_core.gss import gss
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".")[0] == "gsuid_core":
            raise RuntimeError("GsCore is required for poll_from_gscore") from exc
        raise

    settings = get_settings()
    db_path = _live_notify_db_path(get_res_path)
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine, tables=[LiveSubscription.__table__])

    with Session(engine) as session:
        repo = SubscriptionRepository(session)
        bot = GsCoreBotAdapter(gss)

        async def alert_send(
            subscription: LiveSubscription, exc: BaseException
        ) -> None:
            # Plain text avoids the dict-payload incompatibility we just
            # patched in GsCoreBotAdapter, so alerts always go through even
            # when rich embeds aren't supported by the active bot platform.
            await bot.send_to_channel(
                settings.discord_channel_id,
                build_alert_text(subscription, exc),
            )

        await run_poll_once(
            repo,
            settings,
            build_default_providers(settings),
            lambda status: send_notification(
                bot,
                channel_id=settings.discord_channel_id,
                status=status,
                embed_enabled=settings.embed_enabled,
            ),
            alert_send=alert_send,
        )


try:
    from gsuid_core.aps import scheduler
    from gsuid_core.server import on_core_start
except ModuleNotFoundError as exc:
    if exc.name and exc.name.split(".")[0] != "gsuid_core":
        raise
    scheduler = None  # type: ignore[assignment]
    on_core_start = None  # type: ignore[assignment]


if scheduler is not None and on_core_start is not None:

    @on_core_start
    async def start_live_notify_scheduler() -> None:
        settings = get_settings()
        scheduler.add_job(
            poll_from_gscore,
            trigger="interval",
            seconds=settings.poll_interval_seconds,
            id="LiveNotifyUID.poll",
            replace_existing=True,
        )

    live_notify_scheduler_registered = True
else:
    # GsCore is absent under local unit tests; the core polling API remains usable.
    live_notify_scheduler_registered = False
