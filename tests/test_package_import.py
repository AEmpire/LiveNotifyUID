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
from pathlib import Path
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
plugins_config_pkg = types.ModuleType("gsuid_core.utils.plugins_config")
gs_config = types.ModuleType("gsuid_core.utils.plugins_config.gs_config")
config_models = types.ModuleType("gsuid_core.utils.plugins_config.models")

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

class ConfigModel:
    def __init__(self, title, desc, data):
        self.title = title
        self.desc = desc
        self.data = data

class StringConfig:
    def __init__(self, name, path, defaults):
        self.name = name
        self.path = path
        self.defaults = defaults

    def get_config(self, key):
        return self.defaults[key]

def get_res_path(*args, **kwargs):
    return Path(".")

def on_core_start(func):
    return func

sv.SV = SV
bot.Bot = Bot
data_store.get_res_path = get_res_path
models.Event = Event
aps.scheduler = Scheduler()
server.on_core_start = on_core_start
gs_config.StringConfig = StringConfig
config_models.GSC = ConfigModel
config_models.GsBoolConfig = ConfigModel
config_models.GsIntConfig = ConfigModel
config_models.GsStrConfig = ConfigModel

sys.modules["gsuid_core"] = gsuid_core
sys.modules["gsuid_core.sv"] = sv
sys.modules["gsuid_core.bot"] = bot
sys.modules["gsuid_core.data_store"] = data_store
sys.modules["gsuid_core.models"] = models
sys.modules["gsuid_core.aps"] = aps
sys.modules["gsuid_core.server"] = server
sys.modules["gsuid_core.utils.plugins_config"] = plugins_config_pkg
sys.modules["gsuid_core.utils.plugins_config.gs_config"] = gs_config
sys.modules["gsuid_core.utils.plugins_config.models"] = config_models

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
            "force_prefix": ["live", "/live"],
            "allow_empty_prefix": False,
            "alias": ["livenotify", "直播监听"],
        }
    ]


def test_database_can_be_imported_from_root_and_inner_package_paths():
    import LiveNotifyUID.database as root_database
    import LiveNotifyUID.types as root_types
    import importlib.util
    import types

    database_path = Path(root_database.__file__)
    package_name = "DuplicateLiveNotifyUID"
    duplicate_package = types.ModuleType(package_name)
    duplicate_package.__path__ = [str(database_path.parent)]
    sys.modules[package_name] = duplicate_package
    sys.modules[f"{package_name}.types"] = root_types

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.database",
        database_path,
    )
    assert spec is not None
    assert spec.loader is not None
    duplicate_database = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = duplicate_database
    spec.loader.exec_module(duplicate_database)

    assert duplicate_database.LiveSubscription.__tablename__ == "live_subscriptions"
    assert root_database.LiveSubscription.__tablename__ == "live_subscriptions"
