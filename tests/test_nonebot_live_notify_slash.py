from types import SimpleNamespace

from integrations.nonebot_live_notify_slash import (
    build_command_text,
    extract_slash_command,
)


def option(name, value=None, options=None):
    data = {"name": name}
    if value is not None:
        data["value"] = value
    if options is not None:
        data["options"] = options
    return SimpleNamespace(**data)


def test_build_command_text_for_add_with_optional_name():
    assert (
        build_command_text(
            "add",
            {
                "platform": "youtube",
                "target": "https://www.youtube.com/@UTANOch/posts",
                "name": "Utano",
            },
        )
        == "add youtube https://www.youtube.com/@UTANOch/posts Utano"
    )


def test_build_command_text_for_id_commands():
    assert build_command_text("remove", {"id": 4}) == "remove 4"
    assert build_command_text("check", {"id": 5}) == "check 5"


def test_extract_slash_command_from_nested_discord_options():
    action, values = extract_slash_command(
        [
            option(
                "add",
                options=[
                    option("platform", "bili"),
                    option("target", "3494372800727907"),
                ],
            )
        ]
    )

    assert action == "add"
    assert values == {"platform": "bili", "target": "3494372800727907"}
