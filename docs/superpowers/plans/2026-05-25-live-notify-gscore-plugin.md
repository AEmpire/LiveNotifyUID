# Live Notify GsCore Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GsCore plugin that monitors configured Bilibili and YouTube channels and sends one Discord notification when a monitored channel starts a live stream.

**Architecture:** Create a small `LiveNotifyUID` GsCore plugin package with a testable core: normalized provider outputs, SQLModel persistence, a transition state machine, and notification rendering. Keep GsCore-specific code in thin adapters for plugin registration, configuration, scheduling, bot commands, and Discord message delivery.

**Tech Stack:** Python 3.11+, GsCore plugin APIs (`Plugins`, `SV`, config, scheduler, web console), `httpx`, `sqlmodel`, `pytest`, `pytest-asyncio`, `respx`.

---

## References

- Approved design spec: `docs/superpowers/specs/2026-05-25-live-notify-plugin-design.md`
- GsCore plugin docs: https://docs.sayu-bot.com/CodePlugins/CookBook.html
- GsCore startup/plugin docs: https://docs.sayu-bot.com/CodePlugins/Start.html

## File Structure

- Create: `pyproject.toml` - package metadata, runtime dependencies, test dependencies, pytest config.
- Create: `README.md` - installation, configuration, commands, and deployment notes.
- Create: `LiveNotifyUID/__init__.py` - GsCore plugin registration.
- Create: `LiveNotifyUID/config.py` - plugin configuration defaults and typed access helpers.
- Create: `LiveNotifyUID/types.py` - platform/state enums and normalized provider dataclasses.
- Create: `LiveNotifyUID/database.py` - SQLModel subscription model, repository helpers, and web-console mapping.
- Create: `LiveNotifyUID/providers/__init__.py` - provider exports.
- Create: `LiveNotifyUID/providers/base.py` - provider protocol and provider errors.
- Create: `LiveNotifyUID/providers/bilibili.py` - Bilibili UID live-status provider.
- Create: `LiveNotifyUID/providers/youtube.py` - YouTube Data API channel live-status provider.
- Create: `LiveNotifyUID/state_machine.py` - transition decision logic.
- Create: `LiveNotifyUID/notifier.py` - Discord Embed payload builder, plain-text fallback, and send wrapper.
- Create: `LiveNotifyUID/scheduler.py` - batch polling job, concurrency limits, failure backoff, startup registration.
- Create: `LiveNotifyUID/commands.py` - `/live` command handler and command parsing.
- Create: `tests/conftest.py` - async pytest fixtures and test database fixture.
- Create: `tests/test_types.py` - enum and `LiveStatus` tests.
- Create: `tests/test_state_machine.py` - transition and retry tests.
- Create: `tests/test_database.py` - repository persistence tests.
- Create: `tests/test_providers_bilibili.py` - mocked Bilibili API tests.
- Create: `tests/test_providers_youtube.py` - mocked YouTube API tests.
- Create: `tests/test_notifier.py` - message rendering and fallback tests.
- Create: `tests/test_scheduler.py` - batch selection, concurrency, and error isolation tests.
- Create: `tests/test_commands.py` - command parser and command behavior tests.

## Implementation Notes

- Keep all pure business logic independent of live GsCore objects so tests can run locally.
- Use Channel ID for YouTube first-version input; handle resolution is explicitly deferred by the spec.
- Use Bilibili UID for first-version input.
- The repository root should be cloned into GsCore as `gsuid_core/plugins/LiveNotifyUID`; the Python package directory is also `LiveNotifyUID`.
- Rich Discord delivery may differ by adapter. Implement `notifier.send_notification()` to try rich payload first, catch unsupported-rich-message errors, then send plain text.

### Task 1: Project Scaffold And Domain Types

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `LiveNotifyUID/__init__.py`
- Create: `LiveNotifyUID/types.py`
- Test: `tests/test_types.py`

- [ ] **Step 1: Write failing domain tests**

```python
# tests/test_types.py
from datetime import datetime, timezone

from LiveNotifyUID.types import LiveState, LiveStatus, Platform


def test_live_status_defaults_are_safe():
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="12345",
        state=LiveState.OFFLINE,
    )

    assert status.live_id is None
    assert status.title is None
    assert status.display_name is None
    assert status.room_url is None
    assert status.cover_url is None
    assert status.started_at is None
    assert status.raw_metadata == {}


def test_live_status_accepts_live_metadata():
    started_at = datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc)
    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UCabc",
        state=LiveState.LIVE,
        live_id="video-1",
        title="Morning stream",
        display_name="Channel A",
        room_url="https://www.youtube.com/watch?v=video-1",
        cover_url="https://img.example/cover.jpg",
        started_at=started_at,
        raw_metadata={"source": "youtube"},
    )

    assert status.state is LiveState.LIVE
    assert status.live_id == "video-1"
    assert status.raw_metadata["source"] == "youtube"
```

- [ ] **Step 2: Run the failing tests**

Run: `pytest tests/test_types.py -v`

Expected: fails with `ModuleNotFoundError: No module named 'LiveNotifyUID'`.

- [ ] **Step 3: Add package metadata and domain types**

```toml
# pyproject.toml
[project]
name = "LiveNotifyUID"
version = "0.1.0"
description = "GsCore plugin for Bilibili and YouTube live notifications"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "sqlmodel>=0.0.21",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "pytest-asyncio>=0.23",
  "respx>=0.21",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

```markdown
<!-- README.md -->
# LiveNotifyUID

GsCore plugin for Bilibili and YouTube live notifications.

## Install

Clone this repository into `gsuid_core/plugins/LiveNotifyUID`, install the runtime dependencies in the GsCore environment, then restart GsCore.

## Configure

Set `youtube_api_key`, `discord_channel_id`, polling options, and notification options in the plugin config.

## Commands

- `/live add bili <uid> [display_name]`
- `/live add youtube <channel_id> [display_name]`
- `/live remove <id>`
- `/live list`
- `/live enable <id>`
- `/live disable <id>`
- `/live check <id>`
- `/live status`
```

```python
# LiveNotifyUID/__init__.py
from gsuid_core.sv import Plugins

Plugins(
    name="LiveNotifyUID",
    pm=3,
    force_prefix=["live"],
    allow_empty_prefix=False,
    alias=["livenotify", "直播监听"],
)

try:
    from . import commands as commands  # noqa: F401
    from . import scheduler as scheduler  # noqa: F401
except ImportError:
    # Local unit tests can import the package without a full GsCore runtime.
    pass
```

```python
# LiveNotifyUID/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Platform(str, Enum):
    BILI = "bili"
    YOUTUBE = "youtube"


class LiveState(str, Enum):
    UNKNOWN = "unknown"
    OFFLINE = "offline"
    LIVE = "live"


@dataclass(slots=True)
class LiveStatus:
    platform: Platform
    external_id: str
    state: LiveState
    live_id: str | None = None
    title: str | None = None
    display_name: str | None = None
    room_url: str | None = None
    cover_url: str | None = None
    started_at: datetime | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_types.py -v`

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md LiveNotifyUID/__init__.py LiveNotifyUID/types.py tests/test_types.py
git commit -m "feat: scaffold live notify plugin"
```

### Task 2: Configuration Helpers

**Files:**
- Create: `LiveNotifyUID/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

```python
# tests/test_config.py
from LiveNotifyUID.config import LiveNotifySettings, coerce_int


def test_settings_use_spec_defaults():
    settings = LiveNotifySettings()

    assert settings.youtube_api_key == ""
    assert settings.discord_channel_id == ""
    assert settings.poll_interval_seconds == 300
    assert settings.batch_size == 20
    assert settings.max_concurrency == 5
    assert settings.request_timeout_seconds == 10
    assert settings.failure_backoff_minutes == 15
    assert settings.embed_enabled is True
    assert settings.notify_on_startup_live is False


def test_coerce_int_clamps_bad_values_to_default():
    assert coerce_int("12", default=5, minimum=1) == 12
    assert coerce_int("0", default=5, minimum=1) == 5
    assert coerce_int("abc", default=5, minimum=1) == 5
```

- [ ] **Step 2: Run the failing tests**

Run: `pytest tests/test_config.py -v`

Expected: fails because `LiveNotifyUID.config` does not exist.

- [ ] **Step 3: Add configuration module**

```python
# LiveNotifyUID/config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def coerce_int(value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(slots=True)
class LiveNotifySettings:
    youtube_api_key: str = ""
    discord_channel_id: str = ""
    poll_interval_seconds: int = 300
    batch_size: int = 20
    max_concurrency: int = 5
    request_timeout_seconds: int = 10
    failure_backoff_minutes: int = 15
    embed_enabled: bool = True
    notify_on_startup_live: bool = False


def settings_from_mapping(data: dict[str, Any]) -> LiveNotifySettings:
    return LiveNotifySettings(
        youtube_api_key=str(data.get("youtube_api_key", "")),
        discord_channel_id=str(data.get("discord_channel_id", "")),
        poll_interval_seconds=coerce_int(data.get("poll_interval_seconds"), default=300, minimum=30),
        batch_size=coerce_int(data.get("batch_size"), default=20, minimum=1),
        max_concurrency=coerce_int(data.get("max_concurrency"), default=5, minimum=1),
        request_timeout_seconds=coerce_int(data.get("request_timeout_seconds"), default=10, minimum=1),
        failure_backoff_minutes=coerce_int(data.get("failure_backoff_minutes"), default=15, minimum=1),
        embed_enabled=coerce_bool(data.get("embed_enabled"), default=True),
        notify_on_startup_live=coerce_bool(data.get("notify_on_startup_live"), default=False),
    )


def get_settings() -> LiveNotifySettings:
    try:
        from gsuid_core.data_store import get_res_path
        from gsuid_core.utils.plugins_config.gs_config import StringConfig
        from gsuid_core.utils.plugins_config.models import GSC, GsBoolConfig, GsIntConfig, GsStrConfig
    except ImportError:
        return LiveNotifySettings()

    config_default: dict[str, GSC] = {
        "youtube_api_key": GsStrConfig("YouTube API Key", "YouTube Data API key", ""),
        "discord_channel_id": GsStrConfig("Discord Channel ID", "Target Discord channel ID", ""),
        "poll_interval_seconds": GsIntConfig("Poll Interval Seconds", "Scheduler interval", 300),
        "batch_size": GsIntConfig("Batch Size", "Subscriptions checked per scheduler tick", 20),
        "max_concurrency": GsIntConfig("Max Concurrency", "Concurrent provider checks", 5),
        "request_timeout_seconds": GsIntConfig("Request Timeout Seconds", "HTTP timeout", 10),
        "failure_backoff_minutes": GsIntConfig("Failure Backoff Minutes", "Retry delay for failing subscriptions", 15),
        "embed_enabled": GsBoolConfig("Embed Enabled", "Try Discord Embed-style messages first", True),
        "notify_on_startup_live": GsBoolConfig("Notify Startup Live", "Notify if first check finds a live stream", False),
    }
    config_path = get_res_path("LiveNotifyUID") / "config.json"
    plugin_config = StringConfig("LiveNotifyUID", config_path, config_default)
    raw = {key: plugin_config.get_config(key).data for key in config_default}
    return settings_from_mapping(raw)
```

- [ ] **Step 4: Run the config tests**

Run: `pytest tests/test_config.py -v`

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/config.py tests/test_config.py
git commit -m "feat: add live notify configuration"
```

### Task 3: Persistence Repository

**Files:**
- Create: `LiveNotifyUID/database.py`
- Test: `tests/conftest.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write failing repository tests**

```python
# tests/conftest.py
import pytest
from sqlmodel import Session, SQLModel, create_engine

from LiveNotifyUID.database import LiveSubscription


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
```

```python
# tests/test_database.py
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
    first = repo.create_subscription(platform=Platform.BILI, external_id="1", display_name="A")
    second = repo.create_subscription(platform=Platform.YOUTUBE, external_id="UC2", display_name="B")

    now = datetime.now(timezone.utc)
    repo.mark_checked(first.id, checked_at=now - timedelta(minutes=20), state=LiveState.OFFLINE)
    repo.mark_checked(second.id, checked_at=now - timedelta(minutes=5), state=LiveState.OFFLINE)

    due = repo.list_due(limit=1, now=now, failure_backoff_minutes=15)

    assert [item.id for item in due] == [first.id]
```

- [ ] **Step 2: Run the failing repository tests**

Run: `pytest tests/test_database.py -v`

Expected: fails because `LiveNotifyUID.database` does not exist.

- [ ] **Step 3: Add SQLModel repository**

```python
# LiveNotifyUID/database.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlmodel import Field, Session, SQLModel, select

from .types import LiveState, Platform


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveSubscription(SQLModel, table=True):
    __tablename__ = "live_subscriptions"

    id: int | None = Field(default=None, primary_key=True)
    platform: str = Field(index=True)
    external_id: str = Field(index=True)
    display_name: str | None = None
    room_url: str | None = None
    enabled: bool = True
    last_state: str = Field(default=LiveState.UNKNOWN.value, index=True)
    last_live_id: str | None = None
    last_live_title: str | None = None
    last_notified_live_id: str | None = None
    last_checked_at: datetime | None = None
    last_notified_at: datetime | None = None
    failure_count: int = 0
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SubscriptionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_subscription(self, *, platform: Platform, external_id: str, display_name: str | None) -> LiveSubscription:
        subscription = LiveSubscription(
            platform=platform.value,
            external_id=external_id,
            display_name=display_name,
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

    def list_due(self, *, limit: int, now: datetime, failure_backoff_minutes: int) -> list[LiveSubscription]:
        earliest_failed_check = now - timedelta(minutes=failure_backoff_minutes)
        statement = (
            select(LiveSubscription)
            .where(LiveSubscription.enabled == True)  # noqa: E712
            .where(
                (LiveSubscription.failure_count == 0)
                | (LiveSubscription.last_checked_at == None)  # noqa: E711
                | (LiveSubscription.last_checked_at <= earliest_failed_check)
            )
            .order_by(LiveSubscription.last_checked_at.is_(None).desc(), LiveSubscription.last_checked_at)
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
        subscription.last_checked_at = checked_at
        subscription.last_state = state.value
        subscription.last_live_id = live_id
        subscription.last_live_title = live_title
        subscription.room_url = room_url or subscription.room_url
        subscription.failure_count = 0
        subscription.last_error = None
        subscription.updated_at = checked_at
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def mark_notified(self, subscription_id: int | None, *, live_id: str, notified_at: datetime) -> LiveSubscription:
        subscription = self._require(subscription_id)
        subscription.last_notified_live_id = live_id
        subscription.last_notified_at = notified_at
        subscription.updated_at = notified_at
        self.session.add(subscription)
        self.session.commit()
        self.session.refresh(subscription)
        return subscription

    def mark_failure(self, subscription_id: int | None, *, error: str, checked_at: datetime) -> LiveSubscription:
        subscription = self._require(subscription_id)
        subscription.failure_count += 1
        subscription.last_error = error
        subscription.last_checked_at = checked_at
        subscription.updated_at = checked_at
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
        subscription.updated_at = utc_now()
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

    @site.register_admin
    class LiveSubscriptionAdmin(GsAdminModel):
        pk_name = "id"
        page_schema = PageSchema(label="直播监听订阅", icon="fa fa-bell")
        model = LiveSubscription
except ImportError:
    pass
```

- [ ] **Step 4: Run repository tests**

Run: `pytest tests/test_database.py -v`

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/database.py tests/conftest.py tests/test_database.py
git commit -m "feat: add subscription repository"
```

### Task 4: State Machine

**Files:**
- Create: `LiveNotifyUID/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: Write failing state machine tests**

```python
# tests/test_state_machine.py
from LiveNotifyUID.state_machine import TransitionDecision, decide_transition
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


def live(live_id="live-1"):
    return LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        live_id=live_id,
        title="Stream",
        room_url=f"https://www.youtube.com/watch?v={live_id}",
    )


def test_unknown_to_live_does_not_notify_by_default():
    decision = decide_transition(
        previous_state=LiveState.UNKNOWN,
        last_notified_live_id=None,
        current=live(),
        notify_on_startup_live=False,
    )

    assert decision is TransitionDecision.RECORD_ONLY


def test_offline_to_live_notifies():
    decision = decide_transition(
        previous_state=LiveState.OFFLINE,
        last_notified_live_id=None,
        current=live(),
        notify_on_startup_live=False,
    )

    assert decision is TransitionDecision.NOTIFY


def test_live_to_live_with_same_live_id_does_not_notify():
    decision = decide_transition(
        previous_state=LiveState.LIVE,
        last_notified_live_id="live-1",
        current=live("live-1"),
        notify_on_startup_live=False,
    )

    assert decision is TransitionDecision.RECORD_ONLY


def test_notification_failure_can_retry_same_live():
    decision = decide_transition(
        previous_state=LiveState.OFFLINE,
        last_notified_live_id=None,
        current=live("live-2"),
        notify_on_startup_live=True,
    )

    assert decision is TransitionDecision.NOTIFY
```

- [ ] **Step 2: Run the failing state machine tests**

Run: `pytest tests/test_state_machine.py -v`

Expected: fails because `LiveNotifyUID.state_machine` does not exist.

- [ ] **Step 3: Add state machine**

```python
# LiveNotifyUID/state_machine.py
from __future__ import annotations

from enum import Enum

from .types import LiveState, LiveStatus


class TransitionDecision(str, Enum):
    RECORD_ONLY = "record_only"
    NOTIFY = "notify"


def decide_transition(
    *,
    previous_state: LiveState,
    last_notified_live_id: str | None,
    current: LiveStatus,
    notify_on_startup_live: bool,
) -> TransitionDecision:
    if current.state is not LiveState.LIVE:
        return TransitionDecision.RECORD_ONLY

    if current.live_id and current.live_id == last_notified_live_id:
        return TransitionDecision.RECORD_ONLY

    if previous_state is LiveState.UNKNOWN:
        return TransitionDecision.NOTIFY if notify_on_startup_live else TransitionDecision.RECORD_ONLY

    if previous_state is LiveState.OFFLINE:
        return TransitionDecision.NOTIFY

    return TransitionDecision.RECORD_ONLY
```

- [ ] **Step 4: Run state machine tests**

Run: `pytest tests/test_state_machine.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/state_machine.py tests/test_state_machine.py
git commit -m "feat: add live transition state machine"
```

### Task 5: Platform Providers

**Files:**
- Create: `LiveNotifyUID/providers/__init__.py`
- Create: `LiveNotifyUID/providers/base.py`
- Create: `LiveNotifyUID/providers/bilibili.py`
- Create: `LiveNotifyUID/providers/youtube.py`
- Test: `tests/test_providers_bilibili.py`
- Test: `tests/test_providers_youtube.py`

- [ ] **Step 1: Write failing provider tests**

```python
# tests/test_providers_bilibili.py
import httpx
import pytest
import respx

from LiveNotifyUID.providers.bilibili import BilibiliProvider
from LiveNotifyUID.types import LiveState, Platform


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_live_response():
    respx.get("https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "12345": {
                        "live_status": 1,
                        "room_id": 678,
                        "title": "Bili Live",
                        "uname": "主播A",
                        "cover_from_user": "https://cover.example/a.jpg",
                    }
                },
            },
        )
    )

    provider = BilibiliProvider()
    status = await provider.check_channel("12345", timeout_seconds=10)

    assert status.platform is Platform.BILI
    assert status.state is LiveState.LIVE
    assert status.live_id == "678"
    assert status.room_url == "https://live.bilibili.com/678"


@pytest.mark.asyncio
@respx.mock
async def test_bilibili_offline_response():
    respx.get("https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"12345": {"live_status": 0, "uname": "主播A"}}})
    )

    status = await BilibiliProvider().check_channel("12345", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE
    assert status.display_name == "主播A"
```

```python
# tests/test_providers_youtube.py
import httpx
import pytest
import respx

from LiveNotifyUID.providers.youtube import YouTubeProvider
from LiveNotifyUID.types import LiveState, Platform


@pytest.mark.asyncio
@respx.mock
async def test_youtube_live_response():
    respx.get("https://www.googleapis.com/youtube/v3/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {"videoId": "video-1"},
                        "snippet": {
                            "title": "YT Live",
                            "channelTitle": "Channel A",
                            "publishedAt": "2026-05-25T09:30:00Z",
                            "thumbnails": {"high": {"url": "https://img.example/high.jpg"}},
                        },
                    }
                ]
            },
        )
    )

    provider = YouTubeProvider(api_key="key")
    status = await provider.check_channel("UCabc", timeout_seconds=10)

    assert status.platform is Platform.YOUTUBE
    assert status.state is LiveState.LIVE
    assert status.live_id == "video-1"
    assert status.room_url == "https://www.youtube.com/watch?v=video-1"


@pytest.mark.asyncio
@respx.mock
async def test_youtube_offline_response():
    respx.get("https://www.googleapis.com/youtube/v3/search").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    status = await YouTubeProvider(api_key="key").check_channel("UCabc", timeout_seconds=10)

    assert status.state is LiveState.OFFLINE
```

- [ ] **Step 2: Run failing provider tests**

Run: `pytest tests/test_providers_bilibili.py tests/test_providers_youtube.py -v`

Expected: fails because provider modules do not exist.

- [ ] **Step 3: Add providers**

```python
# LiveNotifyUID/providers/base.py
from __future__ import annotations

from typing import Protocol

from LiveNotifyUID.types import LiveStatus


class ProviderError(RuntimeError):
    pass


class LiveProvider(Protocol):
    async def check_channel(self, external_id: str, *, timeout_seconds: int) -> LiveStatus:
        ...
```

```python
# LiveNotifyUID/providers/bilibili.py
from __future__ import annotations

import httpx

from LiveNotifyUID.types import LiveState, LiveStatus, Platform

from .base import ProviderError


class BilibiliProvider:
    endpoint = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"

    async def check_channel(self, external_id: str, *, timeout_seconds: int) -> LiveStatus:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(self.endpoint, params={"uids[]": external_id})
        if response.status_code >= 400:
            raise ProviderError(f"Bilibili HTTP {response.status_code}")
        payload = response.json()
        if payload.get("code") != 0:
            raise ProviderError(f"Bilibili API code {payload.get('code')}")
        data = payload.get("data", {}).get(external_id)
        if not isinstance(data, dict):
            raise ProviderError(f"Bilibili UID not found: {external_id}")

        display_name = data.get("uname")
        live_status = data.get("live_status")
        room_id = data.get("room_id")
        if live_status == 1 and room_id:
            room_id_text = str(room_id)
            return LiveStatus(
                platform=Platform.BILI,
                external_id=external_id,
                state=LiveState.LIVE,
                live_id=room_id_text,
                title=data.get("title"),
                display_name=display_name,
                room_url=f"https://live.bilibili.com/{room_id_text}",
                cover_url=data.get("cover_from_user") or data.get("keyframe"),
                raw_metadata=data,
            )
        return LiveStatus(
            platform=Platform.BILI,
            external_id=external_id,
            state=LiveState.OFFLINE,
            display_name=display_name,
            raw_metadata=data,
        )
```

```python
# LiveNotifyUID/providers/youtube.py
from __future__ import annotations

from datetime import datetime

import httpx

from LiveNotifyUID.types import LiveState, LiveStatus, Platform

from .base import ProviderError


class YouTubeProvider:
    endpoint = "https://www.googleapis.com/youtube/v3/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def check_channel(self, external_id: str, *, timeout_seconds: int) -> LiveStatus:
        if not self.api_key:
            raise ProviderError("YouTube API key is missing")
        params = {
            "part": "snippet",
            "channelId": external_id,
            "eventType": "live",
            "type": "video",
            "maxResults": 1,
            "key": self.api_key,
        }
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(self.endpoint, params=params)
        if response.status_code >= 400:
            raise ProviderError(f"YouTube HTTP {response.status_code}")
        payload = response.json()
        items = payload.get("items") or []
        if not items:
            return LiveStatus(platform=Platform.YOUTUBE, external_id=external_id, state=LiveState.OFFLINE, raw_metadata=payload)

        item = items[0]
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            raise ProviderError("YouTube live item missing videoId")
        published_at = snippet.get("publishedAt")
        started_at = datetime.fromisoformat(published_at.replace("Z", "+00:00")) if published_at else None
        thumbnails = snippet.get("thumbnails", {})
        cover_url = (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")
        return LiveStatus(
            platform=Platform.YOUTUBE,
            external_id=external_id,
            state=LiveState.LIVE,
            live_id=video_id,
            title=snippet.get("title"),
            display_name=snippet.get("channelTitle"),
            room_url=f"https://www.youtube.com/watch?v={video_id}",
            cover_url=cover_url,
            started_at=started_at,
            raw_metadata=item,
        )
```

```python
# LiveNotifyUID/providers/__init__.py
from .base import LiveProvider, ProviderError
from .bilibili import BilibiliProvider
from .youtube import YouTubeProvider

__all__ = ["BilibiliProvider", "LiveProvider", "ProviderError", "YouTubeProvider"]
```

- [ ] **Step 4: Run provider tests**

Run: `pytest tests/test_providers_bilibili.py tests/test_providers_youtube.py -v`

Expected: all provider tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/providers tests/test_providers_bilibili.py tests/test_providers_youtube.py
git commit -m "feat: add live status providers"
```

### Task 6: Notification Rendering And Sending

**Files:**
- Create: `LiveNotifyUID/notifier.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: Write failing notifier tests**

```python
# tests/test_notifier.py
import pytest

from LiveNotifyUID.notifier import build_embed_payload, build_plain_text, send_notification
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


def test_build_plain_text_bilibili():
    status = LiveStatus(
        platform=Platform.BILI,
        external_id="123",
        state=LiveState.LIVE,
        title="标题",
        display_name="主播",
        room_url="https://live.bilibili.com/1",
    )

    text = build_plain_text(status)

    assert "【B站直播开播】" in text
    assert "主播：主播" in text
    assert "链接：https://live.bilibili.com/1" in text


def test_build_embed_payload_contains_discord_fields():
    status = LiveStatus(
        platform=Platform.YOUTUBE,
        external_id="UC1",
        state=LiveState.LIVE,
        live_id="video-1",
        title="YT Live",
        display_name="Channel",
        room_url="https://www.youtube.com/watch?v=video-1",
        cover_url="https://img.example/cover.jpg",
    )

    payload = build_embed_payload(status)

    assert payload["title"] == "Channel 开播了"
    assert payload["url"] == "https://www.youtube.com/watch?v=video-1"
    assert payload["image"]["url"] == "https://img.example/cover.jpg"


@pytest.mark.asyncio
async def test_send_notification_falls_back_to_text():
    calls = []

    class Bot:
        async def send_to_channel(self, channel_id, message):
            calls.append((channel_id, message))
            if isinstance(message, dict):
                raise TypeError("rich message unsupported")

    status = LiveStatus(platform=Platform.YOUTUBE, external_id="UC1", state=LiveState.LIVE, title="Live")

    await send_notification(Bot(), channel_id="123", status=status, embed_enabled=True)

    assert len(calls) == 2
    assert calls[-1][0] == "123"
    assert isinstance(calls[-1][1], str)
```

- [ ] **Step 2: Run failing notifier tests**

Run: `pytest tests/test_notifier.py -v`

Expected: fails because `LiveNotifyUID.notifier` does not exist.

- [ ] **Step 3: Add notifier**

```python
# LiveNotifyUID/notifier.py
from __future__ import annotations

from typing import Any

from .types import LiveStatus, Platform


def platform_label(platform: Platform) -> str:
    return "B站" if platform is Platform.BILI else "YouTube"


def build_plain_text(status: LiveStatus) -> str:
    label = platform_label(status.platform)
    name_key = "主播" if status.platform is Platform.BILI else "频道"
    name = status.display_name or status.external_id
    title = status.title or "直播开始"
    url = status.room_url or ""
    return f"【{label}直播开播】\n{name_key}：{name}\n标题：{title}\n链接：{url}".strip()


def build_embed_payload(status: LiveStatus) -> dict[str, Any]:
    name = status.display_name or status.external_id
    payload: dict[str, Any] = {
        "title": f"{name} 开播了",
        "description": status.title or "直播开始",
        "url": status.room_url,
        "fields": [
            {"name": "平台", "value": platform_label(status.platform), "inline": True},
            {"name": "频道/主播", "value": name, "inline": True},
            {"name": "频道/直播间 ID", "value": status.external_id, "inline": True},
        ],
        "footer": {"text": "LiveNotifyUID"},
    }
    if status.cover_url:
        payload["image"] = {"url": status.cover_url}
    if status.started_at:
        payload["fields"].append({"name": "开播时间", "value": status.started_at.isoformat(), "inline": True})
    return payload


async def send_notification(bot: Any, *, channel_id: str, status: LiveStatus, embed_enabled: bool) -> None:
    if embed_enabled:
        try:
            await bot.send_to_channel(channel_id, build_embed_payload(status))
            return
        except (AttributeError, TypeError, ValueError):
            pass
    await bot.send_to_channel(channel_id, build_plain_text(status))
```

- [ ] **Step 4: Run notifier tests**

Run: `pytest tests/test_notifier.py -v`

Expected: all notifier tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/notifier.py tests/test_notifier.py
git commit -m "feat: add live notification rendering"
```

### Task 7: Scheduler Batch Processing

**Files:**
- Create: `LiveNotifyUID/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler tests**

```python
# tests/test_scheduler.py
from datetime import datetime, timezone

import pytest

from LiveNotifyUID.config import LiveNotifySettings
from LiveNotifyUID.database import SubscriptionRepository
from LiveNotifyUID.scheduler import run_poll_once
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


class FakeProvider:
    def __init__(self, status):
        self.status = status

    async def check_channel(self, external_id, *, timeout_seconds):
        return self.status


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, status):
        self.sent.append(status)


@pytest.mark.asyncio
async def test_run_poll_once_notifies_offline_to_live(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(platform=Platform.BILI, external_id="123", display_name="主播")
    repo.mark_checked(subscription.id, checked_at=datetime(2026, 5, 25, tzinfo=timezone.utc), state=LiveState.OFFLINE)
    notifier = FakeNotifier()
    status = LiveStatus(platform=Platform.BILI, external_id="123", state=LiveState.LIVE, live_id="1", title="Live")

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.BILI: FakeProvider(status)},
        send=notifier.send,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert len(notifier.sent) == 1
    assert updated.last_notified_live_id == "1"


@pytest.mark.asyncio
async def test_run_poll_once_isolates_provider_failure(session):
    repo = SubscriptionRepository(session)
    subscription = repo.create_subscription(platform=Platform.YOUTUBE, external_id="UC1", display_name="Channel")

    class BrokenProvider:
        async def check_channel(self, external_id, *, timeout_seconds):
            raise RuntimeError("provider down")

    await run_poll_once(
        repo=repo,
        settings=LiveNotifySettings(discord_channel_id="discord"),
        providers={Platform.YOUTUBE: BrokenProvider()},
        send=lambda status: None,
        now=datetime(2026, 5, 25, 1, tzinfo=timezone.utc),
    )

    updated = repo.get(subscription.id)
    assert updated.failure_count == 1
    assert "provider down" in updated.last_error
```

- [ ] **Step 2: Run failing scheduler tests**

Run: `pytest tests/test_scheduler.py -v`

Expected: fails because `run_poll_once` does not exist.

- [ ] **Step 3: Add scheduler logic**

```python
# LiveNotifyUID/scheduler.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from .config import LiveNotifySettings, get_settings
from .database import SubscriptionRepository, utc_now
from .providers import BilibiliProvider, ProviderError, YouTubeProvider
from .state_machine import TransitionDecision, decide_transition
from .types import LiveState, LiveStatus, Platform

SendFunc = Callable[[LiveStatus], Awaitable[None]]


async def run_poll_once(
    *,
    repo: SubscriptionRepository,
    settings: LiveNotifySettings,
    providers: Mapping[Platform, object],
    send: SendFunc,
    now: datetime | None = None,
) -> None:
    current_time = now or utc_now()
    due = repo.list_due(limit=settings.batch_size, now=current_time, failure_backoff_minutes=settings.failure_backoff_minutes)
    semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def check_one(subscription):
        async with semaphore:
            platform = Platform(subscription.platform)
            provider = providers[platform]
            try:
                status = await provider.check_channel(subscription.external_id, timeout_seconds=settings.request_timeout_seconds)
            except Exception as exc:
                repo.mark_failure(subscription.id, error=str(exc), checked_at=current_time)
                return

            previous_state = LiveState(subscription.last_state)
            decision = decide_transition(
                previous_state=previous_state,
                last_notified_live_id=subscription.last_notified_live_id,
                current=status,
                notify_on_startup_live=settings.notify_on_startup_live,
            )
            repo.mark_checked(
                subscription.id,
                checked_at=current_time,
                state=status.state,
                live_id=status.live_id,
                live_title=status.title,
                room_url=status.room_url,
            )
            if decision is TransitionDecision.NOTIFY and status.live_id:
                try:
                    await send(status)
                except Exception as exc:
                    repo.mark_failure(subscription.id, error=f"notification failed: {exc}", checked_at=current_time)
                    return
                repo.mark_notified(subscription.id, live_id=status.live_id, notified_at=current_time)

    await asyncio.gather(*(check_one(subscription) for subscription in due))


def build_default_providers(settings: LiveNotifySettings):
    return {
        Platform.BILI: BilibiliProvider(),
        Platform.YOUTUBE: YouTubeProvider(api_key=settings.youtube_api_key),
    }


try:
    from gsuid_core.aps import scheduler
    from gsuid_core.gss import gss
    from gsuid_core.server import on_core_start
    from sqlmodel import Session, create_engine

    from .notifier import send_notification

    @on_core_start
    async def start_live_notify_scheduler():
        settings = get_settings()
        scheduler.add_job(
            poll_from_gscore,
            "interval",
            seconds=settings.poll_interval_seconds,
            id="LiveNotifyUID.poll",
            replace_existing=True,
        )

    async def poll_from_gscore():
        settings = get_settings()
        engine = create_engine("sqlite:///gsuid_core/data/LiveNotifyUID/live_notify.db")
        with Session(engine) as session:
            repo = SubscriptionRepository(session)

            class BotAdapter:
                async def send_to_channel(self, channel_id, message):
                    if not gss.active_bot:
                        raise RuntimeError("no active bot connection")
                    first_key = next(iter(gss.active_bot))
                    bot = gss.active_bot[first_key]
                    await bot.target_send(
                        message,
                        "channel",
                        channel_id,
                        "",
                        "",
                        "",
                        False,
                        "",
                    )

            await run_poll_once(
                repo=repo,
                settings=settings,
                providers=build_default_providers(settings),
                send=lambda status: send_notification(
                    BotAdapter(),
                    channel_id=settings.discord_channel_id,
                    status=status,
                    embed_enabled=settings.embed_enabled,
                ),
            )
except ImportError:
    pass
```

- [ ] **Step 4: Run scheduler tests**

Run: `pytest tests/test_scheduler.py -v`

Expected: all scheduler tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/scheduler.py tests/test_scheduler.py
git commit -m "feat: add live polling scheduler"
```

### Task 8: Command Parser And GsCore Commands

**Files:**
- Create: `LiveNotifyUID/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write failing command tests**

```python
# tests/test_commands.py
from LiveNotifyUID.commands import parse_live_command


def test_parse_add_bilibili_command():
    parsed = parse_live_command("add bili 12345 主播A")

    assert parsed.action == "add"
    assert parsed.platform == "bili"
    assert parsed.external_id == "12345"
    assert parsed.display_name == "主播A"


def test_parse_remove_command():
    parsed = parse_live_command("remove 12")

    assert parsed.action == "remove"
    assert parsed.subscription_id == 12


def test_parse_list_command():
    parsed = parse_live_command("list")

    assert parsed.action == "list"
```

- [ ] **Step 2: Run failing command tests**

Run: `pytest tests/test_commands.py -v`

Expected: fails because `LiveNotifyUID.commands` does not exist.

- [ ] **Step 3: Add parser and GsCore command handler**

```python
# LiveNotifyUID/commands.py
from __future__ import annotations

from dataclasses import dataclass

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
        display_name = " ".join(parts[3:]) if len(parts) > 3 else None
        return ParsedCommand(action="add", platform=parts[1].lower(), external_id=parts[2], display_name=display_name)
    if action in {"remove", "enable", "disable", "check"} and len(parts) == 2 and parts[1].isdigit():
        return ParsedCommand(action=action, subscription_id=int(parts[1]))
    if action in {"list", "status", "help"}:
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


try:
    from gsuid_core.bot import Bot
    from gsuid_core.models import Event
    from gsuid_core.sv import SV
    from sqlmodel import Session, create_engine

    from .config import get_settings
    from .database import SubscriptionRepository

    live_sv = SV("直播监听管理", pm=3)

    def open_repo():
        engine = create_engine("sqlite:///gsuid_core/data/LiveNotifyUID/live_notify.db")
        return Session(engine)

    @live_sv.on_command("live", block=True)
    async def handle_live_command(bot: Bot, ev: Event):
        parsed = parse_live_command(ev.text)
        with open_repo() as session:
            repo = SubscriptionRepository(session)
            if parsed.action == "add" and parsed.platform in {Platform.BILI.value, Platform.YOUTUBE.value} and parsed.external_id:
                subscription = repo.create_subscription(
                    platform=Platform(parsed.platform),
                    external_id=parsed.external_id,
                    display_name=parsed.display_name,
                )
                return await bot.send(f"已添加直播监听 #{subscription.id}: {subscription.platform} {subscription.external_id}")
            if parsed.action == "remove" and parsed.subscription_id:
                removed = repo.delete(parsed.subscription_id)
                return await bot.send("已删除直播监听" if removed else "未找到该直播监听")
            if parsed.action == "enable" and parsed.subscription_id:
                repo.set_enabled(parsed.subscription_id, True)
                return await bot.send("已启用直播监听")
            if parsed.action == "disable" and parsed.subscription_id:
                repo.set_enabled(parsed.subscription_id, False)
                return await bot.send("已停用直播监听")
            if parsed.action == "list":
                rows = repo.list_all()
                if not rows:
                    return await bot.send("当前没有直播监听")
                lines = [
                    f"#{row.id} {row.platform} {row.display_name or row.external_id} enabled={row.enabled} state={row.last_state} failures={row.failure_count}"
                    for row in rows
                ]
                return await bot.send("\n".join(lines))
            if parsed.action == "status":
                rows = repo.list_all()
                enabled = sum(1 for row in rows if row.enabled)
                failed = sum(1 for row in rows if row.failure_count > 0)
                settings = get_settings()
                youtube = "已配置" if settings.youtube_api_key else "未配置"
                return await bot.send(f"直播监听状态：总数 {len(rows)}，启用 {enabled}，失败 {failed}，YouTube API Key {youtube}")
        return await bot.send(format_help())
except ImportError:
    pass
```

- [ ] **Step 4: Run command tests**

Run: `pytest tests/test_commands.py -v`

Expected: all command parser tests pass.

- [ ] **Step 5: Commit**

```bash
git add LiveNotifyUID/commands.py tests/test_commands.py
git commit -m "feat: add live management commands"
```

### Task 9: Full Verification And Documentation Polish

**Files:**
- Modify: `README.md`
- Modify: any source file whose tests expose a gap.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 2: Run import smoke checks**

Run:

```bash
python - <<'PY'
import LiveNotifyUID
from LiveNotifyUID.config import LiveNotifySettings
from LiveNotifyUID.types import LiveState, Platform

print(LiveNotifySettings().poll_interval_seconds)
print(Platform.BILI.value, LiveState.UNKNOWN.value)
PY
```

Expected:

```text
300
bili unknown
```

- [ ] **Step 3: Update README with deployment details**

```markdown
<!-- README.md additions -->
## VPS Deployment

1. Clone this repository as `gsuid_core/plugins/LiveNotifyUID`.
2. Install dependencies in the same Python environment used by GsCore:
   `pip install httpx sqlmodel`
3. Restart GsCore.
4. Set `youtube_api_key` and `discord_channel_id` in the LiveNotifyUID config.
5. Add subscriptions with `/live add bili <uid>` or `/live add youtube <channel_id>`.

## Notification Behavior

The plugin only sends a notification on `offline -> live`. On first startup, already-live channels are recorded without notification unless `notify_on_startup_live` is enabled.

## First-Version Limits

- YouTube input is Channel ID.
- Bilibili input is UID.
- One Discord target channel is configured globally.
- Offline notifications and repeated reminders are not sent.
```

- [ ] **Step 4: Re-run full tests**

Run: `pytest -v`

Expected: all tests pass after documentation and source polish.

- [ ] **Step 5: Commit**

```bash
git add README.md LiveNotifyUID tests
git commit -m "docs: document live notify deployment"
```

## Self-Review

Spec coverage:

- Bilibili UID checks are covered by Task 5.
- YouTube Channel ID checks through YouTube Data API are covered by Task 5.
- Single configured Discord channel is covered by Tasks 2, 6, and 7.
- Config and command management are covered by Tasks 2 and 8.
- Open-live-only notification and restart-safe state are covered by Tasks 3, 4, and 7.
- Embed-style notification with text fallback is covered by Task 6.
- Admin-only command restriction is covered by Task 1 plugin registration `pm=3` and Task 8 service registration `SV("直播监听管理", pm=3)`.
- Medium-scale batch polling is covered by Task 7.

Plan consistency:

- `LiveStatus`, `LiveState`, and `Platform` are introduced before downstream tasks use them.
- Repository methods used by scheduler and commands are introduced in Task 3.
- Provider names used by scheduler are introduced in Task 5.
- Notification functions used by scheduler are introduced in Task 6.

Execution checkpoints:

- Each task ends with tests and a commit.
- The final task runs the full suite and import smoke checks.
