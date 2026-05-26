import builtins

from LiveNotifyUID.config import (
    CONFIG_DEFAULT,
    LiveNotifySettings,
    _should_swallow_optional_gscore_import_error,
    coerce_bool,
    coerce_int,
    get_settings,
    settings_from_mapping,
)


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


def test_config_defaults_are_module_level_for_gscore_console():
    assert set(CONFIG_DEFAULT) >= {
        "youtube_api_key",
        "discord_channel_id",
        "poll_interval_seconds",
        "batch_size",
        "max_concurrency",
        "request_timeout_seconds",
        "failure_backoff_minutes",
        "embed_enabled",
        "notify_on_startup_live",
    }


def test_config_import_guard_only_swallows_missing_gscore_root():
    assert _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="gsuid_core")
    )
    assert not _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="gsuid_core.data_store")
    )
    assert not _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="other_package")
    )


def test_coerce_int_clamps_bad_values_to_default():
    assert coerce_int("12", default=5, minimum=1) == 12
    assert coerce_int("0", default=5, minimum=1) == 5
    assert coerce_int("abc", default=5, minimum=1) == 5


def test_settings_from_mapping_handles_none_strings_and_boolean_values():
    settings = settings_from_mapping(
        {
            "youtube_api_key": None,
            "discord_channel_id": None,
            "embed_enabled": "false",
            "notify_on_startup_live": "yes",
        }
    )

    assert settings.youtube_api_key == ""
    assert settings.discord_channel_id == ""
    assert settings.embed_enabled is False
    assert settings.notify_on_startup_live is True


def test_coerce_bool_parses_true_false_and_default_values():
    assert coerce_bool(True, default=False) is True
    assert coerce_bool(False, default=True) is False
    assert coerce_bool("true", default=False) is True
    assert coerce_bool("1", default=False) is True
    assert coerce_bool("yes", default=False) is True
    assert coerce_bool("on", default=False) is True
    assert coerce_bool("false", default=True) is False
    assert coerce_bool("0", default=True) is False
    assert coerce_bool("no", default=True) is False
    assert coerce_bool("off", default=True) is False
    assert coerce_bool("maybe", default=True) is True
    assert coerce_bool(None, default=False) is False


def test_get_settings_returns_defaults_when_gscore_is_unavailable(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("gsuid_core"):
            raise ModuleNotFoundError(
                "No module named 'gsuid_core'", name="gsuid_core"
            )
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert get_settings() == LiveNotifySettings()
