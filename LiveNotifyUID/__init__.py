def _should_swallow_optional_runtime_import_error(exc: BaseException) -> bool:
    return isinstance(exc, ModuleNotFoundError) and exc.name == "gsuid_core"


try:
    from gsuid_core.sv import Plugins
except ModuleNotFoundError as exc:
    if not _should_swallow_optional_runtime_import_error(exc):
        raise
    Plugins = None
else:
    Plugins(
        name="LiveNotifyUID",
        pm=6,
        force_prefix=["live", "/live"],
        allow_empty_prefix=False,
        alias=["livenotify", "直播监听"],
    )

    try:
        from . import commands as commands  # noqa: F401
        from . import scheduler as scheduler  # noqa: F401
    except ModuleNotFoundError as exc:
        # Local unit tests can import the package without a full GsCore runtime.
        if not _should_swallow_optional_runtime_import_error(exc):
            raise
