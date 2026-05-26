from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import UniqueConstraint, case
from sqlmodel import Field, Session, SQLModel, select

from .types import LiveState, Platform


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_naive_utc(value: datetime) -> datetime:
    """Normalize aware or naive-UTC datetimes for portable DB storage."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def naive_utc_now() -> datetime:
    return to_naive_utc(utc_now())


class LiveSubscription(SQLModel, table=True):
    __tablename__ = "live_subscriptions"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_live_subscription_target"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    platform: str
    external_id: str
    display_name: str | None = None
    room_url: str | None = None
    enabled: bool = True
    last_state: str = Field(default=LiveState.UNKNOWN.value)
    last_live_id: str | None = None
    last_live_title: str | None = None
    last_notified_live_id: str | None = None
    last_checked_at: datetime | None = None
    last_notified_at: datetime | None = None
    failure_count: int = 0
    last_error: str | None = None
    created_at: datetime = Field(default_factory=naive_utc_now)
    updated_at: datetime = Field(default_factory=naive_utc_now)


class SubscriptionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_subscription(
        self,
        *,
        platform: Platform,
        external_id: str,
        display_name: str | None,
        room_url: str | None = None,
    ) -> LiveSubscription:
        subscription = LiveSubscription(
            platform=platform.value,
            external_id=external_id,
            display_name=display_name,
            room_url=room_url,
        )
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def get(self, subscription_id: int | None) -> LiveSubscription | None:
        if subscription_id is None:
            return None
        return self.session.get(LiveSubscription, subscription_id)

    def list_all(self) -> list[LiveSubscription]:
        statement = select(LiveSubscription).order_by(LiveSubscription.id)
        return list(self.session.exec(statement))

    def list_due(
        self,
        *,
        limit: int,
        now: datetime,
        failure_backoff_minutes: int,
    ) -> list[LiveSubscription]:
        normalized_now = to_naive_utc(now)
        earliest_failed_check = normalized_now - timedelta(
            minutes=failure_backoff_minutes
        )
        unchecked_first = case(
            (LiveSubscription.last_checked_at.is_(None), 0),
            else_=1,
        )
        statement = (
            select(LiveSubscription)
            .where(LiveSubscription.enabled == True)  # noqa: E712
            .where(
                (LiveSubscription.failure_count == 0)
                | (LiveSubscription.last_checked_at.is_(None))
                | (LiveSubscription.last_checked_at <= earliest_failed_check)
            )
            .order_by(
                unchecked_first,
                LiveSubscription.last_checked_at,
                LiveSubscription.id,
            )
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def mark_checked(
        self,
        subscription_id: int | None,
        *,
        checked_at: datetime,
        state: LiveState,
        live_id: str | None = None,
        live_title: str | None = None,
        room_url: str | None = None,
    ) -> LiveSubscription:
        subscription = self._require(subscription_id)
        normalized_checked_at = to_naive_utc(checked_at)
        subscription.last_checked_at = normalized_checked_at
        subscription.last_state = state.value
        subscription.last_live_id = live_id
        subscription.last_live_title = live_title
        if room_url is not None:
            subscription.room_url = room_url
        subscription.failure_count = 0
        subscription.last_error = None
        subscription.updated_at = normalized_checked_at
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def mark_notified(
        self,
        subscription_id: int | None,
        *,
        live_id: str,
        notified_at: datetime,
    ) -> LiveSubscription:
        subscription = self._require(subscription_id)
        normalized_notified_at = to_naive_utc(notified_at)
        subscription.last_notified_live_id = live_id
        subscription.last_notified_at = normalized_notified_at
        subscription.updated_at = normalized_notified_at
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def mark_failure(
        self,
        subscription_id: int | None,
        *,
        error: str,
        checked_at: datetime,
    ) -> LiveSubscription:
        subscription = self._require(subscription_id)
        normalized_checked_at = to_naive_utc(checked_at)
        subscription.failure_count += 1
        subscription.last_error = error
        subscription.last_checked_at = normalized_checked_at
        subscription.updated_at = normalized_checked_at
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def delete(self, subscription_id: int) -> bool:
        subscription = self.get(subscription_id)
        if subscription is None:
            return False
        self.session.delete(subscription)
        self.session.commit()
        return True

    def set_enabled(self, subscription_id: int, enabled: bool) -> LiveSubscription:
        subscription = self._require(subscription_id)
        subscription.enabled = enabled
        subscription.updated_at = naive_utc_now()
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def _require(self, subscription_id: int | None) -> LiveSubscription:
        subscription = self.get(subscription_id)
        if subscription is None:
            raise ValueError(f"subscription not found: {subscription_id}")
        return subscription


try:
    from gsuid_core.webconsole.mount_app import GsAdminModel, PageSchema, site
except ModuleNotFoundError as exc:
    if exc.name and exc.name.split(".")[0] == "gsuid_core":
        pass
    else:
        raise
else:

    @site.register_admin
    class LiveSubscriptionAdmin(GsAdminModel):
        pk_name = "id"
        page_schema = PageSchema(label="直播监听订阅", icon="fa fa-bell")
        model = LiveSubscription
