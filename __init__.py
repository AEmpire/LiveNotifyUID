from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_INNER_PACKAGE = _PACKAGE_ROOT / "LiveNotifyUID"
_INNER_INIT = _INNER_PACKAGE / "__init__.py"

if not _INNER_INIT.is_file():
    raise ImportError(f"Cannot find inner LiveNotifyUID package at {_INNER_INIT}")

# GsCore imports plugins from gsuid_core/plugins/<plugin_name>.  When this
# repository is cloned there, the repository root is the import package.
# Point submodule imports at the existing inner implementation package so
# `LiveNotifyUID.types` and relative imports resolve to one module tree.
__path__ = [str(_INNER_PACKAGE)]

with _INNER_INIT.open("rb") as _inner_init_file:
    exec(compile(_inner_init_file.read(), str(_INNER_INIT), "exec"), globals())
