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
