import pytest

from LiveNotifyUID import _should_swallow_optional_runtime_import_error


def test_package_import_guard_only_swallows_missing_gscore_root():
    assert _should_swallow_optional_runtime_import_error(
        ModuleNotFoundError(name="gsuid_core")
    )

    assert not _should_swallow_optional_runtime_import_error(
        ModuleNotFoundError(name="gsuid_core.sv")
    )
    assert not _should_swallow_optional_runtime_import_error(
        ModuleNotFoundError(name="httpx")
    )
    assert not _should_swallow_optional_runtime_import_error(ImportError("bad import"))


def test_package_import_guard_reraises_nested_import_errors():
    error = ModuleNotFoundError(name="httpx")

    with pytest.raises(ModuleNotFoundError) as raised:
        if not _should_swallow_optional_runtime_import_error(error):
            raise error

    assert raised.value.name == "httpx"
