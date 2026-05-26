from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest

from LiveNotifyUID.config import LiveNotifySettings
from LiveNotifyUID.database import SubscriptionRepository
from LiveNotifyUID.notifier import UnsupportedRichMessageError
from LiveNotifyUID.scheduler import GsCoreBotAdapter, run_poll_once
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


def test_scheduler_imports_without_gscore():
    scheduler = importlib.import_module("LiveNotifyUID.scheduler")

    assert scheduler.poll_from_gscore is not None
    assert scheduler.live_notify_scheduler_registered is False


class FakeProvider:
    def __init__(self, status: LiveStatus):
        self.status = status

    async def check_channel(
        self, external_id: str, *, timeout_seconds: float
    ) -> LiveStatus:
        return self.status


class QueueProvider:
    def __init__(self, statuses: list[LiveStatus]):
        self.statuses = statuses

    async def check_channel(
        self, external_id: str, *, timeout_seconds: float
    ) -> LiveStatus:
        return self.statuses.pop(0)


class FakeNotifier:
    def __init__(self):
        self.sent: list[LiveStatus] = []

    async def send(self, status: LiveStatus) -> None:
        self.sent.append(status)


async def async_noop(status: LiveStatus) -> None:
    return None


@pytest.mark.asyncio
async def test_gscore_bot_adapter_translates_rich_payload_type_error():
    class Bot:
        async def target_send(self, *args):
            raise TypeError("rich message unsupported")

    class Gss:
        active_bot = {"bot": Bot()}

    adapter = GsCoreBotAdapter(Gss())

    with pytest.raises(UnsupportedRichMessageError):
        await adapter.send_to_channel("discord", {"title": "Live"})


@pytest.mark.asyncio
async def test_gscore_bot_adapter_propagates_text_type_error():
    class Bot:
        async def target_send(self, *args):
            raise TypeError("send failed")

    class Gss:
        active_bot = {"bot": Bot()}

    adapter = GsCoreBotAdapter(Gss())

    with pytest.raises(TypeError, match="send failed"):
        await adapter.send_to_channel("discord", "plain text")


@pytest.mark.asyncio
async def test_run_poll_once_accepts_positional_core_arguments(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.OFFLINE,
    )

    await run_poll_once(
        repo,
        LiveNotifySettings(),
        {Platform.BILI: FakeProvider(status)},
        FakeNotifier().send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert updated.last_state == LiveState.OFFLINE.value


@pytest.mark.asyncio
async def test_run_poll_once_notifies_offline_to_live(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    repo.mark_checked(
        subscription.id,
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        state=LiveState.OFFLINE,
    )
    notifier = FakeNotifier()
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="1",
        title="Live",
    )

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=notifier.send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert len(notifier.sent) == 1
    assert updated.last_state == LiveState.LIVE.value
    assert updated.last_live_id == "1"
    assert updated.last_live_title == "Live"
    assert updated.last_notified_live_id == "1"


@pytest.mark.asyncio
async def test_run_poll_once_notifies_second_bilibili_session_in_same_room(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    first_live = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="678:2026-05-25 01:00:00",
        title="First Live",
    )
    offline = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.OFFLINE,
    )
    second_live = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="678:2026-05-26 01:00:00",
        title="Second Live",
    )
    notifier = FakeNotifier()
    provider = QueueProvider([first_live, offline, second_live])
    settings = LiveNotifySettings(discord_channel_id="discord")
    first_run_at = datetime(2026, 5, 25, 1, tzinfo=timezone.utc)

    repo.mark_checked(
        subscription.id,
        checked_at=first_run_at - timedelta(minutes=1),
        state=LiveState.OFFLINE,
    )
    await run_poll_once(
        repo=repo,
        settings=settings,
        providers={Platform.BILI: provider},
        send=notifier.send,
        now=first_run_at,
    )
    await run_poll_once(
        repo=repo,
        settings=settings,
        providers={Platform.BILI: provider},
        send=notifier.send,
        now=first_run_at + timedelta(minutes=1),
    )
    await run_poll_once(
        repo=repo,
        settings=settings,
        providers={Platform.BILI: provider},
        send=notifier.send,
        now=first_run_at + timedelta(minutes=2),
    )

    updated = repo.get(subscription.id)
    assert [status.live_id for status in notifier.sent] == [
        "678:2026-05-25 01:00:00",
        "678:2026-05-26 01:00:00",
    ]
    assert updated.last_notified_live_id == "678:2026-05-26 01:00:00"


@pytest.mark.asyncio
async def test_run_poll_once_isolates_provider_failure(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.YOUTUBE, external_id="UC1", display_name="Channel"
    )

    class BrokenProvider:
        async def check_channel(self, external_id: str, *, timeout_seconds: float):
            raise RuntimeError("provider down")

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.YOUTUBE: BrokenProvider()},
        send=async_noop,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert updated.failure_count == 1
    assert "provider down" in updated.last_error


@pytest.mark.asyncio
async def test_run_poll_once_does_not_notify_unknown_to_live_by_default(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    notifier = FakeNotifier()
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="1",
    )

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=notifier.send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert notifier.sent == []
    assert updated.last_state == LiveState.LIVE.value
    assert updated.last_notified_live_id is None


@pytest.mark.asyncio
async def test_run_poll_once_keeps_startup_suppressed_live_silent_on_second_poll(
    session,
):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="startup-live",
    )
    notifier = FakeNotifier()
    first_run_at = datetime(2026, 5, 25, 1, tzinfo=timezone.utc)

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=notifier.send,
        now=first_run_at,
    )
    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=notifier.send,
        now=first_run_at + timedelta(minutes=1),
    )

    updated = repo.get(subscription.id)
    assert notifier.sent == []
    assert updated.last_state == LiveState.LIVE.value
    assert updated.last_live_id == "startup-live"
    assert updated.last_notified_live_id is None


@pytest.mark.asyncio
async def test_run_poll_once_notification_failure_records_error_without_marking_notified(
    session,
):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    repo.mark_checked(
        subscription.id,
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        state=LiveState.OFFLINE,
    )
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="1",
    )

    async def broken_send(status: LiveStatus) -> None:
        raise RuntimeError("discord down")

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=broken_send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert updated.last_state == LiveState.LIVE.value
    assert updated.last_notified_live_id is None
    assert updated.failure_count == 1
    assert "notification failed: discord down" in updated.last_error


@pytest.mark.asyncio
async def test_run_poll_once_retries_unnotified_live_after_notification_failure(
    session,
):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI, external_id="123", display_name="主播"
    )
    repo.mark_checked(
        subscription.id,
        checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        state=LiveState.OFFLINE,
    )
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        live_id="same-live",
    )

    async def broken_send(status: LiveStatus) -> None:
        raise RuntimeError("discord down")

    first_run_at = datetime(2026, 5, 25, 1, tzinfo=timezone.utc)
    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=broken_send,
        now=first_run_at,
    )

    notifier = FakeNotifier()
    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(
            discord_channel_id="discord", failure_backoff_minutes=1
        ),
        providers={Platform.BILI: FakeProvider(status)},
        send=notifier.send,
        now=first_run_at + timedelta(minutes=2),
    )

    updated = repo.get(subscription.id)
    assert len(notifier.sent) == 1
    assert updated.last_notified_live_id == "same-live"
    assert updated.failure_count == 0
    assert updated.last_error is None


@pytest.mark.asyncio
async def test_run_poll_once_honors_max_concurrency(session):
    repo = SubscriptionRepository(session)
    for index in range(5):
        repo.create_subscription(
            platform=Platform.BILI,
            external_id=str(index),
            display_name=f"主播 {index}",
        )

    class TrackingProvider:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def check_channel(
            self, external_id: str, *, timeout_seconds: float
        ) -> LiveStatus:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return LiveStatus(
                platform=Platform.BILI,
                external_id=external_id,
                state=LiveState.OFFLINE,
            )

    provider = TrackingProvider()

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(max_concurrency=2, batch_size=5),
        providers={Platform.BILI: provider},
        send=FakeNotifier().send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    assert provider.max_active == 2


@pytest.mark.asyncio
async def test_run_poll_once_missing_provider_marks_failure(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.YOUTUBE, external_id="UC1", display_name="Channel"
    )

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={},
        send=FakeNotifier().send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert updated.failure_count == 1
    assert "missing provider" in updated.last_error


@pytest.mark.asyncio
async def test_run_poll_once_respects_due_batch_limit(session):
    repo = SubscriptionRepository(session)
    now = datetime(2026, 5, 25, 1, tzinfo=timezone.utc)
    subscriptions = [
        repo.create_subscription(
            platform=Platform.BILI,
            external_id=str(index),
            display_name=f"主播 {index}",
        )
        for index in range(3)
    ]
    for subscription in subscriptions:
        repo.mark_checked(
            subscription.id,
            checked_at=now - timedelta(hours=1),
            state=LiveState.OFFLINE,
        )

    class EchoProvider:
        def __init__(self):
            self.checked: list[str] = []

        async def check_channel(
            self, external_id: str, *, timeout_seconds: float
        ) -> LiveStatus:
            self.checked.append(external_id)
            return LiveStatus(
                platform=Platform.BILI,
                external_id=external_id,
                state=LiveState.OFFLINE,
            )

    provider = EchoProvider()

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(batch_size=2),
        providers={Platform.BILI: provider},
        send=FakeNotifier().send,
        now=now,
    )

    assert provider.checked == ["0", "1"]
