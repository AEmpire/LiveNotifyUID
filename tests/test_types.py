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
