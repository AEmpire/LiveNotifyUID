from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone

from .config import LiveNotifySettings
from .database import LiveSubscription, SubscriptionRepository
from .providers import BilibiliProvider, LiveProvider, YouTubeProvider
from .state_machine import TransitionDecision, decide_transition
from .types import LiveState, LiveStatus, Platform

logger = logging.getLogger(__name__)

SendFunc = Callable[[LiveStatus], Awaitable[None]]


def build_default_providers(
    settings: LiveNotifySettings,
) -> dict[Platform, LiveProvider]:
    return {
        Platform.BILI: BilibiliProvider(),
        Platform.YOUTUBE: YouTubeProvider(api_key=settings.youtube_api_key),
    }


async def run_poll_once(
    *,
    repo: SubscriptionRepository,
    settings: LiveNotifySettings,
    providers: Mapping[Platform, LiveProvider],
    send: SendFunc,
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
    repo.mark_checked(
        subscription.id,
        checked_at=checked_at,
        state=status.state,
        live_id=status.live_id,
        live_title=status.title,
        room_url=status.room_url,
    )

    if decision is not TransitionDecision.NOTIFY or status.live_id is None:
        return

    try:
        await send(status)
    except Exception as exc:
        logger.exception("live notification failed")
        repo.mark_failure(
            subscription.id,
            error=f"notification failed: {exc}",
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


try:
    from gsuid_core.sv import SV
except (ImportError, ModuleNotFoundError) as exc:
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        missing_root = exc.name.split(".")[0]
        if missing_root != "gsuid_core":
            raise
    SV = None  # type: ignore[assignment]


if SV is not None:
    live_notify_scheduler = SV("LiveNotifyUIDScheduler")
else:
    live_notify_scheduler = None
