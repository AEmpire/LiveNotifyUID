try:
    from gsuid_core.sv import Plugins
except ImportError:
    Plugins = None
else:
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
