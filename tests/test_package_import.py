import json
import os
from pathlib import Path
import subprocess
import sys

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


def test_gscore_plugins_parent_import_executes_registration(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "LiveNotifyUID").symlink_to(repo_root, target_is_directory=True)

    script = """
import json
import sys
import types

registrations = []
gsuid_core = types.ModuleType("gsuid_core")
gsuid_core.__path__ = []
sv = types.ModuleType("gsuid_core.sv")
bot = types.ModuleType("gsuid_core.bot")
data_store = types.ModuleType("gsuid_core.data_store")
models = types.ModuleType("gsuid_core.models")
aps = types.ModuleType("gsuid_core.aps")
server = types.ModuleType("gsuid_core.server")

class Plugins:
    def __init__(self, **kwargs):
        registrations.append(kwargs)

sv.Plugins = Plugins

class SV:
    def __init__(self, *args, **kwargs):
        pass

    def on_command(self, *args, **kwargs):
        def decorate(func):
            return func

        return decorate

class Bot:
    pass

class Event:
    pass

class Scheduler:
    def add_job(self, *args, **kwargs):
        pass

def get_res_path(*args, **kwargs):
    return "."

def on_core_start(func):
    return func

sv.SV = SV
bot.Bot = Bot
data_store.get_res_path = get_res_path
models.Event = Event
aps.scheduler = Scheduler()
server.on_core_start = on_core_start

sys.modules["gsuid_core"] = gsuid_core
sys.modules["gsuid_core.sv"] = sv
sys.modules["gsuid_core.bot"] = bot
sys.modules["gsuid_core.data_store"] = data_store
sys.modules["gsuid_core.models"] = models
sys.modules["gsuid_core.aps"] = aps
sys.modules["gsuid_core.server"] = server

import LiveNotifyUID

print(json.dumps({
    "file": getattr(LiveNotifyUID, "__file__", None),
    "path": list(getattr(LiveNotifyUID, "__path__", [])),
    "registrations": registrations,
}, ensure_ascii=False))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(plugins_dir)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    imported = json.loads(result.stdout)

    assert imported["file"]
    assert imported["file"].endswith("__init__.py")
    assert imported["registrations"] == [
        {
            "name": "LiveNotifyUID",
            "pm": 3,
            "force_prefix": ["live"],
            "allow_empty_prefix": False,
            "alias": ["livenotify", "直播监听"],
        }
    ]
