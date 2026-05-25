from datetime import datetime, timedelta, timezone

from LiveNotifyUID.database import LiveSubscription, SubscriptionRepository
from LiveNotifyUID.types import LiveState, Platform


def test_create_and_fetch_subscription(session):
    repo = SubscriptionRepository(session)

    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="12345",
        display_name="主播A",
    )
    fetched = repo.get(subscription.id)

    assert fetched is not None
    assert fetched.platform == Platform.BILI.value
    assert fetched.external_id == "12345"
    assert fetched.display_name == "主播A"
    assert fetched.enabled is True
    assert fetched.last_state == LiveState.UNKNOWN.value


def test_due_subscriptions_order_by_oldest_check(session):
    repo = SubscriptionRepository(session)
    first = repo.create_subscription(
        platform=Platform.BILI, external_id="1", display_name="A"
    )
    second = repo.create_subscription(
        platform=Platform.YOUTUBE, external_id="UC2", display_name="B"
    )

    now = datetime.now(timezone.utc)
    repo.mark_checked(
        first.id,
        checked_at=now - timedelta(minutes=20),
        state=LiveState.OFFLINE,
    )
    repo.mark_checked(
        second.id,
        checked_at=now - timedelta(minutes=5),
        state=LiveState.OFFLINE,
    )

    due = repo.list_due(limit=1, now=now, failure_backoff_minutes=15)

    assert [item.id for item in due] == [first.id]
