from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from LiveNotifyUID.database import SubscriptionRepository, to_naive_utc, utc_now
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


def test_list_due_filters_disabled_subscriptions(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="disabled",
        display_name="Disabled",
    )
    repo.set_enabled(subscription.id, False)

    due = repo.list_due(
        limit=10,
        now=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        failure_backoff_minutes=15,
    )

    assert due == []


def test_list_due_applies_failure_backoff(session):
    repo = SubscriptionRepository(session)
    recent = repo.create_subscription(
        platform=Platform.BILI,
        external_id="recent",
        display_name="Recent",
    )
    old = repo.create_subscription(
        platform=Platform.YOUTUBE,
        external_id="old",
        display_name="Old",
    )

    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    repo.mark_failure(
        recent.id,
        error="temporary",
        checked_at=now - timedelta(minutes=5),
    )
    repo.mark_failure(
        old.id,
        error="still old enough",
        checked_at=now - timedelta(minutes=20),
    )

    due = repo.list_due(limit=10, now=now, failure_backoff_minutes=15)

    assert [item.id for item in due] == [old.id]


def test_list_due_orders_unchecked_before_checked(session):
    repo = SubscriptionRepository(session)
    checked = repo.create_subscription(
        platform=Platform.BILI,
        external_id="checked",
        display_name="Checked",
    )
    unchecked = repo.create_subscription(
        platform=Platform.YOUTUBE,
        external_id="unchecked",
        display_name="Unchecked",
    )

    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    repo.mark_checked(
        checked.id,
        checked_at=now - timedelta(minutes=60),
        state=LiveState.OFFLINE,
    )

    due = repo.list_due(limit=10, now=now, failure_backoff_minutes=15)

    assert [item.id for item in due] == [unchecked.id, checked.id]


def test_mark_failure_records_error_and_increments_count(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="fail",
        display_name="Failing",
    )

    checked_at = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    failed = repo.mark_failure(
        subscription.id,
        error="timeout",
        checked_at=checked_at,
    )

    assert failed.failure_count == 1
    assert failed.last_error == "timeout"
    assert failed.last_checked_at == to_naive_utc(checked_at)
    assert failed.updated_at == to_naive_utc(checked_at)


def test_mark_notified_records_live_id_and_time(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.YOUTUBE,
        external_id="UCnotify",
        display_name="Notify",
    )

    notified_at = datetime(2026, 5, 25, 13, 0, tzinfo=timezone.utc)
    notified = repo.mark_notified(
        subscription.id,
        live_id="live-1",
        notified_at=notified_at,
    )

    assert notified.last_notified_live_id == "live-1"
    assert notified.last_notified_at == to_naive_utc(notified_at)
    assert notified.updated_at == to_naive_utc(notified_at)


def test_mark_checked_backfills_missing_display_name(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="12345",
        display_name=None,
    )

    checked = repo.mark_checked(
        subscription.id,
        checked_at=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        state=LiveState.OFFLINE,
        display_name="主播A",
    )

    assert checked.display_name == "主播A"


def test_mark_checked_keeps_custom_display_name(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="12345",
        display_name="我的备注",
    )

    checked = repo.mark_checked(
        subscription.id,
        checked_at=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
        state=LiveState.OFFLINE,
        display_name="接口名称",
    )

    assert checked.display_name == "我的备注"


def test_delete_removes_subscription_and_reports_missing(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="delete",
        display_name="Delete",
    )

    assert repo.delete(subscription.id) is True
    assert repo.get(subscription.id) is None
    assert repo.delete(subscription.id) is False


def test_duplicate_platform_external_id_is_rejected(session):
    repo = SubscriptionRepository(session)
    repo.create_subscription(
        platform=Platform.BILI,
        external_id="same",
        display_name="First",
    )

    with pytest.raises(IntegrityError):
        repo.create_subscription(
            platform=Platform.BILI,
            external_id="same",
            display_name="Duplicate",
        )


def test_same_external_id_can_exist_on_different_platforms(session):
    repo = SubscriptionRepository(session)

    bili = repo.create_subscription(
        platform=Platform.BILI,
        external_id="same-id",
        display_name="Bili",
    )
    youtube = repo.create_subscription(
        platform=Platform.YOUTUBE,
        external_id="same-id",
        display_name="YouTube",
    )

    assert [item.id for item in repo.list_all()] == [bili.id, youtube.id]


def test_datetime_helpers_keep_utc_now_aware_but_store_naive_utc(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="time",
        display_name="Time",
    )

    aware_utc = utc_now()
    assert aware_utc.tzinfo is timezone.utc

    checked_at = datetime(2026, 5, 25, 20, 30, tzinfo=timezone(timedelta(hours=8)))
    checked = repo.mark_checked(
        subscription.id,
        checked_at=checked_at,
        state=LiveState.LIVE,
        live_id="live-time",
        live_title="Time stream",
    )
    session.expire_all()
    fetched = repo.get(checked.id)

    assert fetched is not None
    assert fetched.last_checked_at == datetime(2026, 5, 25, 12, 30)
    assert fetched.last_checked_at.tzinfo is None
    assert fetched.updated_at == datetime(2026, 5, 25, 12, 30)
    assert fetched.updated_at.tzinfo is None


def test_naive_datetimes_are_treated_as_utc_for_storage(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(
        platform=Platform.BILI,
        external_id="naive",
        display_name="Naive",
    )

    checked_at = datetime(2026, 5, 25, 12, 30)
    checked = repo.mark_checked(
        subscription.id,
        checked_at=checked_at,
        state=LiveState.OFFLINE,
    )

    assert checked.last_checked_at == checked_at
    assert checked.updated_at == checked_at
