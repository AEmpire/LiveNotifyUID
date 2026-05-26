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
from .notifier import UnsupportedRichMessageError, send_notification
from .providers import BilibiliProvider, LiveProvider, YouTubeProvider
from .state_machine import TransitionDecision, decide_transition
from .types import LiveState, LiveStatus, Platform

logger = logging.getLogger(__name__)

SendFunc = Callable[[LiveStatus], Awaitable[None]]
NOTIFICATION_FAILED_PREFIX = "notification failed:"


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
        repo.mark_failure(subscription.id, error=str(exc), checked_at=checked_at)
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


class GsCoreBotAdapter:
    def __init__(self, gss: Any) -> None:
        self.gss = gss

    async def send_to_channel(self, channel_id: str, message: Any) -> None:
        if not self.gss.active_bot:
            raise RuntimeError("no active bot connection")

        bot = next(iter(self.gss.active_bot.values()))
        try:
            await bot.target_send(
                message,
                "channel",
                str(channel_id),
                "",
                "",
                "",
                False,
                "",
            )
        except (TypeError, ValueError) as exc:
            if isinstance(message, dict):
                raise UnsupportedRichMessageError(str(exc)) from exc
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
