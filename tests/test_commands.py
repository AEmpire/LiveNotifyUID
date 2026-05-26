from LiveNotifyUID.commands import parse_live_command


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
