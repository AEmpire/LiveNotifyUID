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
