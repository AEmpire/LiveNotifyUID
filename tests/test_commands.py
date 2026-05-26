import pytest

from LiveNotifyUID.config import LiveNotifySettings
from LiveNotifyUID.commands import (
    LIVE_COMMAND_TRIGGER,
    build_command_response,
    execute_live_command,
    normalize_live_handler_text,
    _should_swallow_optional_gscore_import_error,
    parse_live_command,
)
from LiveNotifyUID.providers.youtube import ResolvedYouTubeChannel
from LiveNotifyUID.types import LiveState, LiveStatus, Platform


class FakeProvider:
    def __init__(self, status: LiveStatus):
        self.status = status
        self.checked: list[str] = []

    async def check_channel(
        self, external_id: str, *, timeout_seconds: float
    ) -> LiveStatus:
        self.checked.append(external_id)
        return self.status


class FakeResolvingYouTubeProvider(FakeProvider):
    def __init__(self, status: LiveStatus, resolved: ResolvedYouTubeChannel):
        super().__init__(status)
        self.resolved = resolved
        self.references: list[str] = []

    async def resolve_channel_reference(
        self, reference: str, *, timeout_seconds: float
    ) -> ResolvedYouTubeChannel:
        self.references.append(reference)
        return self.resolved


def test_parse_add_bilibili_command():
    parsed = parse_live_command("add bili 12345 主播A")

    assert parsed.action == "add"
    assert parsed.platform == "bili"
    assert parsed.external_id == "12345"
    assert parsed.display_name == "主播A"


def test_parse_remove_command():
    parsed = parse_live_command("remove 12")

    assert parsed.action == "remove"
    assert parsed.subscription_id == 12


def test_parse_list_command():
    parsed = parse_live_command("list")

    assert parsed.action == "list"


def test_empty_command_returns_help():
    parsed = parse_live_command("")

    assert parsed.action == "help"


def test_invalid_command_returns_invalid():
    parsed = parse_live_command("subscribe bili 12345")

    assert parsed.action == "invalid"


def test_parse_add_youtube_command_with_display_name_spaces():
    parsed = parse_live_command("add youtube UC1 Channel Name")

    assert parsed.action == "add"
    assert parsed.platform == "youtube"
    assert parsed.external_id == "UC1"
    assert parsed.display_name == "Channel Name"


def test_non_numeric_remove_returns_invalid():
    parsed = parse_live_command("remove nope")

    assert parsed.action == "invalid"


def test_enable_disable_check_parse_ids():
    enabled = parse_live_command("enable 1")
    disabled = parse_live_command("disable 2")
    checked = parse_live_command("check 3")

    assert enabled.action == "enable"
    assert enabled.subscription_id == 1
    assert disabled.action == "disable"
    assert disabled.subscription_id == 2
    assert checked.action == "check"
    assert checked.subscription_id == 3


def test_optional_gscore_import_guard_only_swallows_missing_root_package():
    assert _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="gsuid_core")
    )

    assert not _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="gsuid_core.bot")
    )
    assert not _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="gsuid_core.data_store")
    )
    assert not _should_swallow_optional_gscore_import_error(
        ModuleNotFoundError(name="other_package")
    )


def test_optional_gscore_import_guard_reraises_submodule_errors():
    error = ModuleNotFoundError(name="gsuid_core.bot")

    with pytest.raises(ModuleNotFoundError) as raised:
        if not _should_swallow_optional_gscore_import_error(error):
            raise error

    assert raised.value.name == "gsuid_core.bot"


def test_normalize_live_handler_text_rejects_prefix_like_command_matches():
    assert normalize_live_handler_text("add bili 12345 主播A") == "add bili 12345 主播A"
    assert normalize_live_handler_text("live add bili 12345 主播A") == "add bili 12345 主播A"
    assert normalize_live_handler_text("/live status") == "status"
    assert normalize_live_handler_text(" live   list ") == "list"
    assert normalize_live_handler_text("liveadd bili 12345") is None
    assert normalize_live_handler_text("/liveadd bili 12345") is None
    assert normalize_live_handler_text("liveXYZ") is None


def test_normalize_live_handler_text_rejects_empty_trigger_prefix_collisions():
    assert (
        normalize_live_handler_text(
            "add bili 12345 主播A",
            raw_text="live add bili 12345 主播A",
        )
        == "add bili 12345 主播A"
    )
    assert normalize_live_handler_text("status", raw_text="/live status") == "status"
    assert (
        normalize_live_handler_text("add bili 12345", raw_text="liveadd bili 12345")
        is None
    )
    assert (
        normalize_live_handler_text("add bili 12345", raw_text="/liveadd bili 12345")
        is None
    )


def test_gscore_force_prefix_uses_base_live_command_trigger():
    assert LIVE_COMMAND_TRIGGER == ""


def test_build_command_response_adds_and_lists_subscription(session):
    response = build_command_response(
        session,
        parse_live_command("add bili 12345 主播A"),
        LiveNotifySettings(),
    )
    listed = build_command_response(
        session,
        parse_live_command("list"),
        LiveNotifySettings(),
    )

    assert response == "已添加直播监听 #1: bili 12345"
    assert "#1 bili 主播A 启用，状态 unknown" in listed


def test_build_command_response_rolls_back_duplicate_add(session):
    settings = LiveNotifySettings()
    parsed = parse_live_command("add youtube UC1 Channel")

    build_command_response(session, parsed, settings)
    duplicate = build_command_response(session, parsed, settings)
    listed = build_command_response(session, parse_live_command("list"), settings)

    assert duplicate == "该直播监听已存在"
    assert listed.count("youtube") == 1


def test_build_command_response_removes_subscription(session):
    settings = LiveNotifySettings()
    added = build_command_response(
        session,
        parse_live_command("add bili 12345 主播A"),
        settings,
    )
    subscription_id = int(added.split("#", 1)[1].split(":", 1)[0])

    removed = build_command_response(
        session,
        parse_live_command(f"remove {subscription_id}"),
        settings,
    )
    listed = build_command_response(session, parse_live_command("list"), settings)

    assert removed == "已删除直播监听"
    assert listed == "当前没有直播监听"


def test_build_command_response_checks_subscription_status(session):
    settings = LiveNotifySettings()
    build_command_response(
        session,
        parse_live_command("add bili 12345 主播A"),
        settings,
    )

    checked = build_command_response(session, parse_live_command("check 1"), settings)

    assert "直播监听 #1" in checked
    assert "平台：bili" in checked
    assert "目标：主播A" in checked
    assert "状态：unknown" in checked


@pytest.mark.asyncio
async def test_execute_live_command_add_performs_initial_check_without_notification(
    session,
):
    settings = LiveNotifySettings()
    provider = FakeProvider(
        LiveStatus(
            platform=Platform.BILI,
            external_id="12345",
            state=LiveState.LIVE,
            live_id="678:2026-05-25 01:00:00",
            title="Bili Live",
            room_url="https://live.bilibili.com/678",
        )
    )

    response = await execute_live_command(
        session,
        parse_live_command("add bili 12345 主播A"),
        settings,
        providers={Platform.BILI: provider},
    )
    listed = build_command_response(
        session,
        parse_live_command("list"),
        settings,
    )

    assert response == "已添加直播监听 #1: bili 12345\n初始状态：live"
    assert provider.checked == ["12345"]
    assert "#1 bili 主播A 启用，状态 live" in listed


@pytest.mark.asyncio
async def test_execute_live_command_add_resolves_youtube_handle_url(session):
    settings = LiveNotifySettings(youtube_api_key="token")
    provider = FakeResolvingYouTubeProvider(
        LiveStatus(
            platform=Platform.YOUTUBE,
            external_id="UCresolved",
            state=LiveState.OFFLINE,
        ),
        ResolvedYouTubeChannel(channel_id="UCresolved", display_name="Utano"),
    )

    response = await execute_live_command(
        session,
        parse_live_command("add youtube https://www.youtube.com/@UTANOch/posts"),
        settings,
        providers={Platform.YOUTUBE: provider},
    )
    listed = build_command_response(session, parse_live_command("list"), settings)

    assert provider.references == ["https://www.youtube.com/@UTANOch/posts"]
    assert provider.checked == ["UCresolved"]
    assert response == "已添加直播监听 #1: youtube UCresolved\n初始状态：offline"
    assert "#1 youtube Utano 启用，状态 offline" in listed


@pytest.mark.asyncio
async def test_execute_live_command_check_fetches_current_status_without_notification(
    session,
):
    settings = LiveNotifySettings()
    build_command_response(
        session,
        parse_live_command("add bili 12345 主播A"),
        settings,
    )
    provider = FakeProvider(
        LiveStatus(
            platform=Platform.BILI,
            external_id="12345",
            state=LiveState.LIVE,
            live_id="678:2026-05-25 01:00:00",
            title="Bili Live",
        )
    )

    checked = await execute_live_command(
        session,
        parse_live_command("check 1"),
        settings,
        providers={Platform.BILI: provider},
    )

    assert provider.checked == ["12345"]
    assert "直播监听 #1" in checked
    assert "状态：live" in checked
    assert "最近直播：Bili Live" in checked


def test_build_command_response_reports_status(session):
    settings = LiveNotifySettings(youtube_api_key="token")
    build_command_response(
        session,
        parse_live_command("add bili 12345 主播A"),
        settings,
    )
    build_command_response(session, parse_live_command("disable 1"), settings)

    response = build_command_response(session, parse_live_command("status"), settings)

    assert response == "直播监听状态：总数 1，启用 0，失败 0，YouTube API Key 已配置"
