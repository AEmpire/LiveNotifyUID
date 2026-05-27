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
    avatar_url: str | None = None
    started_at: datetime | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
