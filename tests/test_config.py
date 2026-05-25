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
